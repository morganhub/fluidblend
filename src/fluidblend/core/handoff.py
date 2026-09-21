"""Build the hand-off bundle published beside a GLB export (the fluidunreal transfer contract).

The bundle joins what only this kit knows (which asset, which version, which licence, which clip,
which reference pose) to the GLB an engine-side kit will import. It is written from the runtime's
`export-report.json` and the project's own manifests, never from a guess: an instance whose licence
cannot be read is either a hard stop (Unreal preset) or is left out with a warning, and a clip whose
glTF animation cannot be matched by name is reported rather than attributed to the wrong instance.

This module never imports `bpy`.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fluidblend import __version__
from fluidblend.contracts.common import Artifact, FrameRange, OperationResult
from fluidblend.contracts.handoff import (
    AxisConvention,
    BundleClip,
    BundleFile,
    BundleInstance,
    BundleProducer,
    BundleValidation,
    HandoffBundle,
)
from fluidblend.contracts.operations import OperationRequest
from fluidblend.contracts.production import AssetManifest, ClipIndex
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import now_iso, sha256_file
from fluidblend.core.paths import resolve_inside

VERSION_DIR = re.compile(r"^v(\d{3,})$")
DEFAULT_AXES = {"blender": {"up": "+Z", "forward": "-Y"}, "gltf": {"up": "+Y", "forward": "+Z"}}


class LicenceUnknown(Exception):
    """An instance is about to be redistributed without a readable licence."""

    def __init__(self, instance_id: str, detail: str):
        super().__init__(f"unknown license for a planned redistribution: {instance_id} ({detail})")
        self.instance_id = instance_id
        self.detail = detail


@dataclass
class BundleOutcome:
    """`bundle is None` means: nothing was published, and `warnings` says why."""

    bundle: HandoffBundle | None
    warnings: list[str]


def _asset_manifest(root: Path, asset_id: str, version: int | None) -> tuple[AssetManifest, list[str]]:
    """The manifest of the exact asset version, or the highest one with a warning."""
    warnings: list[str] = []
    candidates: list[tuple[int, Path]] = []
    for kind_dir in sorted(p for p in (root / "assets").glob("*") if p.is_dir()):
        asset_dir = kind_dir / asset_id
        if not asset_dir.is_dir():
            continue
        for entry in sorted(asset_dir.iterdir()):
            match = VERSION_DIR.fullmatch(entry.name)
            if entry.is_dir() and match and (entry / "asset.json").is_file():
                candidates.append((int(match.group(1)), entry / "asset.json"))
    if not candidates:
        raise LicenceUnknown(asset_id, f"no asset manifest under assets/*/{asset_id}/v*/asset.json")
    candidates.sort()
    chosen = next((p for v, p in candidates if v == version), None)
    if chosen is None:
        chosen = candidates[-1][1]
        warnings.append(
            f"asset {asset_id}: the scene does not say which version it carries "
            f"(built before 0.6.0); read {chosen.parent.name} instead"
        )
    return AssetManifest.model_validate(read_json(chosen)), warnings


def _licence_file(root: Path, manifest: AssetManifest, instance_id: str) -> Path:
    try:
        path = resolve_inside(root, manifest.license_path)
    except (ValueError, OSError) as exc:
        raise LicenceUnknown(instance_id, f"license_path is not inside the project: {exc}") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise LicenceUnknown(instance_id, f"license_path is empty or missing: {manifest.license_path}")
    return path


def _clip_indexes(root: Path) -> dict[str, ClipIndex]:
    clips: dict[str, ClipIndex] = {}
    for path in sorted((root / "animation" / "clips").glob("*/clip.json")):
        try:
            index = ClipIndex.model_validate(read_json(path))
        except (ValueError, OSError):
            continue
        clips[index.clip_id] = index
    return clips


def _khronos_status(result: OperationResult) -> str:
    """`not_run` is a result of its own: it is never rounded up to `passed`."""
    validation = result.metrics.get("khronos_validation")
    if isinstance(validation, dict):
        return "passed" if validation.get("passed") else "failed"
    return "not_run"


def _describe_instances(
    root: Path, report: dict[str, Any], strict: bool, warnings: list[str], limits: list[str]
) -> tuple[list[BundleInstance], dict[str, str]]:
    instances: list[BundleInstance] = []
    licences: dict[str, str] = {}
    for row in report.get("instances", []):
        instance_id = row["instance_id"]
        asset_id = row.get("asset_id")
        if not asset_id:
            warnings.append(f"instance {instance_id} carries no asset_id: left out of the bundle")
            continue
        try:
            manifest, notes = _asset_manifest(root, asset_id, row.get("asset_version"))
            warnings.extend(notes)
            licence_path = _licence_file(root, manifest, instance_id)
        except LicenceUnknown as exc:
            if strict:
                raise
            warnings.append(f"{exc}: instance left out of the bundle")
            continue
        relative = f"licenses/{licence_path.name}"
        licences[relative] = str(licence_path)
        if row.get("gltf_node_name_verified") is False:
            limits.append(f"instance {instance_id}: the glTF node name was not confirmed by a re-import")
        instances.append(
            BundleInstance(
                instance_id=instance_id,
                kind=row.get("kind", "character"),
                asset_id=asset_id,
                asset_version=manifest.version,
                license=manifest.license,
                license_file=relative,
                rig_profile=row.get("rig_profile"),
                armature=row.get("armature"),
                skinned=bool(row.get("skinned")),
                baked=bool(row.get("baked")),
                export_def_bones=bool(row.get("export_def_bones")),
                bone_count=int(row.get("bone_count") or 0),
                gltf_node_name=row.get("gltf_node_name") or instance_id,
                reference_pose=row.get("reference_pose") or [],
                grips=row.get("grips") or manifest.grips,
            )
        )
    return instances, licences


def _describe_clips(
    root: Path, report: dict[str, Any], instances: list[BundleInstance], warnings: list[str]
) -> list[BundleClip]:
    """Match `<node>.<clip_id>` exactly: a near-miss is reported, never attributed to a guess."""
    by_node = {i.gltf_node_name: i for i in instances}
    known = _clip_indexes(root)
    # The bundle describes the GLB, not the Blender scene: with slide_to_zero the exported
    # animation starts at frame 0, and a consumer measuring its length must be told that range.
    slid = bool(report.get("settings", {}).get("export_anim_slide_to_zero", True))
    clips: list[BundleClip] = []
    for action in report.get("exported", {}).get("actions", []):
        node, _, clip_id = action.partition(".")
        instance, index = by_node.get(node), known.get(clip_id)
        if instance is None or index is None:
            warnings.append(
                f"animation {action!r} was exported but could not be matched to an instance and a clip"
            )
            continue
        span = index.frame_range
        if slid and span.start != 0:
            span = FrameRange(start=0, end_exclusive=span.count)
        clips.append(
            BundleClip(
                clip_id=index.clip_id,
                instance_id=instance.instance_id,
                gltf_animation_name=action,
                frame_range=span,
                loop=index.loop,
                root_motion=index.root_motion,
                stride_m=index.stride_m,
                repetitions=index.repetitions,
                contacts=[c.model_dump(mode="json") for c in index.contacts],
                events=[e.model_dump(mode="json") for e in index.events],
                measurements=[m.model_dump(mode="json") for m in index.measurements],
            )
        )
    return clips


def _describe_files(out_dir: Path, result: OperationResult, licences: dict[str, str]) -> list[BundleFile]:
    glb = next((a for a in result.artifacts if a.kind == "glb"), None)
    if glb is None:
        raise ValueError("no GLB artifact to build a bundle from")
    files = [BundleFile(role="model", path=glb.path, format="glb", sha256=glb.sha256, bytes=glb.bytes)]
    reports = (("export-report.json", "export_report"), ("gltf-validator.json", "khronos_report"))
    for name, role in reports:
        path = out_dir / name
        if path.is_file():
            files.append(
                BundleFile(
                    role=role,
                    path=name,
                    format="json",
                    sha256=sha256_file(path),
                    bytes=path.stat().st_size,
                )
            )
    for relative in sorted(licences):
        path = out_dir / relative
        files.append(
            BundleFile(
                role="license",
                path=relative,
                format="md" if path.suffix == ".md" else "txt",
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
            )
        )
    return files


def build_bundle(
    *,
    root: Path,
    request: OperationRequest,
    parameters: Any,
    out_dir: Path,
    result: OperationResult,
    fps: Any,
    source_revision: int = 0,
) -> BundleOutcome:
    """Join the export report, the asset manifests and the clip index into one bundle."""
    report = read_json(out_dir / "export-report.json")
    strict = getattr(parameters, "export_preset", "none") == "unreal"
    warnings: list[str] = []
    limits: list[str] = []

    instances, licences = _describe_instances(root, report, strict, warnings, limits)
    clips = _describe_clips(root, report, instances, warnings)

    # Copy each licence beside the bundle: a consumer never reaches back into this project.
    for relative, source in licences.items():
        destination = out_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    if not licences:
        # No licence could be established: the GLB stays a task artifact and no bundle is published.
        # A bundle is a redistribution format; it never travels without the licence of what it carries.
        warnings.append(
            "no hand-off bundle was published: no instance had a readable licence, "
            "and a bundle never redistributes an asset without one"
        )
        return BundleOutcome(bundle=None, warnings=warnings)

    files = _describe_files(out_dir, result, licences)
    reimport = report.get("reimport")
    fidelity = None
    if isinstance(reimport, dict) and isinstance(reimport.get("skeleton_fidelity"), dict):
        fidelity = reimport["skeleton_fidelity"].get("max_error_m")
    if reimport is None:
        limits.append("no control re-import was run: the glTF node names are unverified")
    if not instances:
        limits.append("no instance could be described: the bundle carries the GLB only")

    bundle = HandoffBundle(
        bundle_id=request.operation_id,
        producer=BundleProducer(
            kit="fluidblend",
            version=__version__,
            operation=request.operation,
            operation_id=request.operation_id,
            project_id=request.project_id,
            shot_id=request.target.shot_id,
            source_revision=source_revision,
            created_at=now_iso(),
        ),
        fps=fps,
        axis_convention=AxisConvention.model_validate(report.get("axis_convention") or DEFAULT_AXES),
        files=files,
        validation=BundleValidation(
            khronos=_khronos_status(result),
            reimport_passed=None if reimport is None else bool(reimport.get("passed")),
            skeleton_fidelity_max_error_m=fidelity,
        ),
        instances=instances,
        clips=clips,
        warnings=[*result.warnings, *warnings],
        limits=limits,
    )
    return BundleOutcome(bundle=bundle, warnings=warnings)


def bundle_artifact(out_dir: Path) -> Artifact:
    path = out_dir / "handoff-bundle.json"
    return Artifact(
        kind="bundle",
        path="handoff-bundle.json",
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
    )
