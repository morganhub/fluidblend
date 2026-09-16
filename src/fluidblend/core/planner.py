"""Planning an operation without mutating anything: resources, budget, stop conditions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.contracts.common import ErrorCode, ErrorRecord, StrictModel
from fluidblend.contracts.operations import OperationRequest, OperationSpec
from fluidblend.contracts.tasks import Plan
from fluidblend.core import budgets
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.permissions import operation_allowed
from fluidblend.core.project import Project, ProjectError
from fluidblend.core.revisions import RevisionStore


def _frames_for(project: Project, request: OperationRequest, params: StrictModel) -> int:
    shot_id = request.target.shot_id
    if shot_id:
        try:
            shot = project.shot_manifest(shot_id)
            frames = shot.frame_range.count
        except ProjectError:
            frames = 0
    else:
        frames = 0
    data = params.model_dump()
    if "frames" in data:
        frames = int(data["frames"])
    if data.get("frame_start") is not None and data.get("frame_end_exclusive") is not None:
        frames = max(0, int(data["frame_end_exclusive"]) - int(data["frame_start"]))
    step = int(data.get("step", 1) or 1)
    return max(0, -(-frames // step))


def estimate_for(
    project: Project, request: OperationRequest, params: StrictModel, spec: OperationSpec
) -> dict[str, float]:
    root = project.root
    data = params.model_dump()
    if spec.name == "shot.preview":
        engine = data.get("engine") or project.manifest.preview.engine
        return budgets.estimate_render(root, engine, _frames_for(project, request, params))
    if spec.name == "animation.retime":
        samples = int(data.get("preview_samples", 0)) * 2
        est = budgets.estimate_render(root, "WORKBENCH", samples)
        est["frames"] = samples
        est["seconds"] += budgets.BLENDER_STARTUP_SECONDS
        est["disk_mib"] += 8.0
        return est
    if spec.name == "scene.build":
        return {"frames": 0, "seconds": budgets.BLENDER_STARTUP_SECONDS + 3.0, "disk_mib": 6.0}
    if spec.name == "game.export":
        return {
            "frames": 0,
            "seconds": budgets.BLENDER_STARTUP_SECONDS + budgets.GLB_EXPORT_SECONDS,
            "disk_mib": 4.0,
        }
    if spec.backend == "blender":
        return {"frames": 0, "seconds": budgets.BLENDER_STARTUP_SECONDS + 2.0, "disk_mib": 1.0}
    return {"frames": 0, "seconds": 2.0, "disk_mib": 1.0}


def make_plan(
    project: Project,
    request: OperationRequest,
    params: StrictModel,
    spec: OperationSpec,
    *,
    save: bool = True,
) -> Plan:
    allowed, reason = operation_allowed(project.permissions, spec)
    estimate = estimate_for(project, request, params, spec)
    blocking: list[ErrorRecord] = []
    warnings: list[str] = []
    if not spec.available:
        blocking.append(
            ErrorRecord(
                code=ErrorCode.UNSUPPORTED_CAPABILITY,
                message=f"{spec.name} is not implemented in this batch ({spec.lot})",
                recovery="see docs/roadmap.md; no execution is simulated",
            )
        )
    if not allowed:
        blocking.append(
            ErrorRecord(
                code=ErrorCode.PERMISSION_REQUIRED,
                message=reason or "operation not allowed",
                recovery="update config/permissions.json (user decision)",
            )
        )
    blocking.extend(budgets.check_budget(project.manifest.budgets, estimate))

    resources: list[str] = []
    if spec.backend == "blender":
        resources.append(f"blender:{project.local.blender_executable or 'auto-discovery'}")
    if spec.name in ("shot.preview", "film.assemble"):
        resources.append(f"ffmpeg:{project.local.ffmpeg_executable or 'PATH'}")
        resources.append(f"ffprobe:{project.local.ffprobe_executable or 'PATH'}")
    if spec.name == "game.export":
        resources.append(
            f"gltf_validator:{project.local.gltf_validator_executable or 'PATH (optional, otherwise not_run)'}"
        )

    steps: list[str] = ["validate the request and the permissions"]
    if spec.op_class != "read":
        steps.append("check the expected revision and the absence of manual changes")
        steps.append("lock the project, create the task folder and a checkpoint of the source")
    steps.append(f"run {spec.name} ({spec.backend})")
    steps.append("validate the artifacts (existence, hash, metrics), then publish and journal")

    if request.target.shot_id and spec.op_class != "read":
        check = RevisionStore(project.root).check(
            f"shot:{request.target.shot_id}", request.target.expected_revision
        )
        if not check.ok:
            warnings.append(f"revision: {check.reason} (the run stays blocked until this is resolved)")

    plan = Plan(
        operation_id=request.operation_id,
        operation=spec.name,
        backend=spec.backend,
        op_class=spec.op_class,
        lot=spec.lot,
        available=spec.available,
        permission_ok=allowed,
        estimated_seconds=round(float(estimate["seconds"]), 1),
        estimated_new_disk_mib=round(float(estimate["disk_mib"]), 1),
        resources=resources,
        budget=project.manifest.budgets.model_dump(),
        stop_conditions=[
            "time or disk budget exceeded",
            "expected revision different from the current revision",
            "protected source or missing permission",
            f"{project.manifest.autonomy.max_repair_attempts} repair attempts without improvement",
        ],
        steps=steps,
        warnings=warnings,
        blocking_errors=blocking,
    )
    if save:
        path = project.root / "state" / "plans" / f"{request.operation_id}.json"
        atomic_write_json(path, plan.model_dump(mode="json"))
        project.journal().append(
            "plan_created", operation_id=request.operation_id, path=path.relative_to(project.root).as_posix()
        )
    return plan


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return plan.model_dump(mode="json")


def plans_dir(root: Path) -> Path:
    return root / "state" / "plans"
