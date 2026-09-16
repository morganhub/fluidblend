"""Running an operation: validation -> permissions -> budget -> idempotency -> revision -> lock ->
checkpoint -> backend (Blender batch or host) -> post-processing -> validation -> publication -> journal.

Exit codes: see `fluidblend.exit_codes`.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from fluidblend import __version__
from fluidblend.adapters import blender_batch, blender_discovery, blender_live
from fluidblend.adapters import ffmpeg as ff
from fluidblend.adapters import gltf_validator as gltfv
from fluidblend.contracts.common import (
    Artifact,
    ChangedEntity,
    ErrorCode,
    ErrorRecord,
    OperationResult,
    OperationStatus,
)
from fluidblend.contracts.operations import (
    OperationRequest,
    OperationSpec,
    RequestValidationError,
    StrictModel,
    validate_request,
)
from fluidblend.contracts.tasks import TaskRecord, WorkerInfo
from fluidblend.core import budgets as budget_mod
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.checkpoints import create_file_checkpoint
from fluidblend.core.hashing import fingerprint, new_id, now_iso, sha256_file
from fluidblend.core.locks import LockBusy, ProjectLocks
from fluidblend.core.paths import PathRejected, assert_not_protected, relpath_posix, resolve_inside
from fluidblend.core.permissions import operation_allowed
from fluidblend.core.planner import estimate_for
from fluidblend.core.project import Project, ProjectError
from fluidblend.core.revisions import RevisionStore
from fluidblend.core.state import StateStore
from fluidblend.hostops import HOST_HANDLERS
from fluidblend.hostops.context import HostContext, HostOpError

LIVE_OPERATIONS = {"scene.inspect", "scene.audit", "animation.retime", "scene.checkpoint"}
PATH_PARAMS = ("audio_path", "request_path")
BLOCKED_EXIT = {
    ErrorCode.PERMISSION_REQUIRED: exit_codes.BLOCKED,
    ErrorCode.UNSUPPORTED_CAPABILITY: exit_codes.BLOCKED,
    ErrorCode.MISSING_DEPENDENCY: exit_codes.BLOCKED,
    ErrorCode.BUDGET_EXCEEDED: exit_codes.BUDGET_EXCEEDED,
    ErrorCode.SCENE_CONFLICT: exit_codes.CONFLICT,
    ErrorCode.TIMEOUT_UNKNOWN_STATE: exit_codes.UNKNOWN_STATE,
    ErrorCode.VALIDATION_FAILED: exit_codes.INVALID,
    ErrorCode.INTERNAL_ERROR: exit_codes.FAILED,
    ErrorCode.RIG_MAPPING_REQUIRED: exit_codes.BLOCKED,
}


class TaskAbort(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        recovery: str | None = None,
        details: dict[str, Any] | None = None,
        status: OperationStatus = OperationStatus.blocked,
    ):
        super().__init__(message)
        self.error = ErrorRecord(code=code, message=message, recovery=recovery, details=details or {})
        self.status = status


@dataclass
class RunOutcome:
    result: OperationResult
    exit_code: int
    task: TaskRecord | None = None
    replayed: bool = False


class TaskRunner:
    def __init__(
        self,
        project: Project,
        *,
        test_hooks: dict[str, Any] | None = None,
        allow_unlocked_blender: bool = False,
        mode: str = "batch",
    ):
        if mode not in ("batch", "live"):
            raise ValueError(f"unknown mode: {mode}")
        self.mode = mode
        self.project = project
        self.state = StateStore(project.root)
        self.revisions = RevisionStore(project.root)
        self.locks = ProjectLocks(project.root)
        self.test_hooks = test_hooks or {}
        self.allow_unlocked_blender = allow_unlocked_blender

    # --- Public API ---------------------------------------------------------------------

    def run(self, payload: dict[str, Any], *, force_dry_run: bool = False) -> RunOutcome:
        try:
            request, params, spec = validate_request(payload)
        except RequestValidationError as exc:
            result = self._rejected(
                payload, ErrorCode.VALIDATION_FAILED, str(exc), details={"errors": exc.details}
            )
            return RunOutcome(result, exit_codes.INVALID)
        if force_dry_run:
            request = request.model_copy(update={"dry_run": True})
        task: TaskRecord | None = None
        try:
            self._preflight(request, params, spec)
            replay = self._idempotency(request, spec)
            if replay is not None:
                return RunOutcome(replay, exit_codes.OK, replayed=True)
            source = self._resolve_source(request, spec)
            self._check_revision(request, spec)
            instance_lock = (
                self.locks.hold("blender-instance", purpose=f"live {spec.name} {request.operation_id}")
                if self.mode == "live" and spec.name in LIVE_OPERATIONS
                else contextlib.nullcontext()
            )
            with self.locks.hold("project", purpose=f"{spec.name} {request.operation_id}"), instance_lock:
                task = self._create_task(request, spec)
                if request.dry_run:
                    result = self._dry_run_result(request, spec, task)
                    task.status = OperationStatus.planned
                    task.result_path = self._save_result(task, result)
                    self.state.upsert_task(task)
                    return RunOutcome(result, exit_codes.OK, task)
                if spec.op_class == "write" and source is not None and spec.name != "scene.checkpoint":
                    manifest = create_file_checkpoint(
                        self.project.root, source, label=spec.name, task_id=task.task_id
                    )
                    task.checkpoint_id = manifest["checkpoint_id"]
                    self.project.journal().append(
                        "checkpoint_created",
                        **{k: manifest[k] for k in ("checkpoint_id", "source", "sha256")},
                        task_id=task.task_id,
                    )
                task.status = OperationStatus.running
                task.attempts += 1
                self.state.upsert_task(task)
                result = self._execute(request, params, spec, task, source)
                if result.status != OperationStatus.succeeded:
                    return self._finish_failed(task, result)
                task.status = OperationStatus.validating
                self.state.upsert_task(task)
                result = self._postprocess(request, params, spec, task, result)
                if result.status != OperationStatus.succeeded:
                    return self._finish_failed(task, result)
                self._verify_artifacts(task, result)
                result = self._publish(request, spec, task, result)
                if self.mode == "live" and spec.name in LIVE_OPERATIONS and spec.creates_version:
                    self._live_reload(request, task, result)
                task.status = OperationStatus.succeeded
                task.artifacts = result.artifacts
                task.new_revision = result.new_revision
                task.result_path = self._save_result(task, result)
                self.state.upsert_task(task)
                return RunOutcome(result, exit_codes.OK, task)
        except LockBusy as exc:
            abort = TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                str(exc),
                recovery="wait for the other writer to finish, or check state/locks/*.owner.json",
            )
            return self._aborted(request, spec, task, abort)
        except TaskAbort as abort:
            return self._aborted(request, spec, task, abort)

    def status(self, task_id: str) -> dict[str, Any]:
        task = self.state.task(task_id)
        if task is None:
            raise ProjectError(f"unknown task: {task_id}")
        task_dir = self._task_dir(task_id)
        info = task.model_dump(mode="json")
        stderr = task_dir / "blender.stderr.log"
        if stderr.exists():
            info["stderr_tail"] = stderr.read_text(encoding="utf-8", errors="replace")[-1500:]
        if task.worker:
            line = blender_batch.worker_command_line(task.worker.pid)
            info["worker_alive"] = bool(line and task.task_id in line)
        return info

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self.state.task(task_id)
        if task is None:
            raise ProjectError(f"unknown task: {task_id}")
        if task.status not in (
            OperationStatus.running,
            OperationStatus.validating,
            OperationStatus.unknown,
            OperationStatus.queued,
        ):
            return {
                "task_id": task_id,
                "status": task.status,
                "cancelled": False,
                "reason": "task already finished",
            }
        killed, message = (False, "no worker recorded")
        if task.worker:
            killed, message = blender_batch.kill_worker(task.worker.pid, task.task_id)
        task.status = OperationStatus.cancelled
        task.partial_effects = self._partial_effects(task_id)
        self.state.upsert_task(task)
        self.project.journal().append(
            "task_cancelled", task_id=task_id, worker_killed=killed, message=message
        )
        return {
            "task_id": task_id,
            "status": task.status,
            "cancelled": True,
            "worker_killed": killed,
            "message": message,
            "partial_effects": task.partial_effects,
        }

    def reconcile(self, task_id: str) -> dict[str, Any]:
        """Task in an uncertain state: inspect the task folder before any new attempt."""
        task = self.state.task(task_id)
        if task is None:
            raise ProjectError(f"unknown task: {task_id}")
        report: dict[str, Any] = {"task_id": task_id, "previous_status": task.status}
        if task.status in (
            OperationStatus.succeeded,
            OperationStatus.failed,
            OperationStatus.cancelled,
            OperationStatus.blocked,
            OperationStatus.planned,
        ):
            report.update({"status": task.status, "action": "none", "reason": "already in a terminal state"})
            return report
        if task.worker:
            line = blender_batch.worker_command_line(task.worker.pid)
            if line and task.task_id in line:
                report.update({"status": task.status, "action": "wait", "reason": "worker still running"})
                return report
        task_dir = self._task_dir(task_id)
        result_path = task_dir / "result.json"
        published = [p for p in self.state.rebuild(save=False)["published"] if p.get("task_id") == task_id]
        if task.status == OperationStatus.validating and published:
            # Publication started: all or nothing depending on the files actually present.
            missing = [p["path"] for p in published if not (self.project.root / p["path"]).exists()]
            if not missing:
                task.status = OperationStatus.succeeded
                report.update({"status": task.status, "action": "confirmed_published"})
            else:
                task.status = OperationStatus.failed
                task.partial_effects = [f"partially published, missing: {m}" for m in missing]
                report.update({"status": task.status, "action": "partial_publish", "missing": missing})
        elif result_path.exists():
            task.status = OperationStatus.failed
            task.partial_effects = self._partial_effects(task_id)
            report.update(
                {
                    "status": task.status,
                    "action": "result_found_not_committed",
                    "reason": "result produced but never validated/published; sources untouched; run the operation again",
                }
            )
        else:
            task.status = OperationStatus.failed
            task.partial_effects = self._partial_effects(task_id)
            task.errors.append(
                ErrorRecord(
                    code=ErrorCode.TIMEOUT_UNKNOWN_STATE,
                    message="worker interrupted before result.json",
                    recovery="partial outputs listed; sources untouched; run again with the same operation_id",
                )
            )
            report.update(
                {"status": task.status, "action": "marked_failed", "partial_effects": task.partial_effects}
            )
        self.state.upsert_task(task)
        self.project.journal().append(
            "reconciled", task_id=task_id, **{k: v for k, v in report.items() if k != "task_id"}
        )
        return report

    # --- Steps ----------------------------------------------------------------------------

    def _preflight(self, request: OperationRequest, params: StrictModel, spec: OperationSpec) -> None:
        if request.project_id != self.project.project_id:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"project_id {request.project_id!r} does not match project {self.project.project_id!r}",
                status=OperationStatus.failed,
            )
        data = params.model_dump()
        for key in PATH_PARAMS:
            value = data.get(key)
            if value:
                try:
                    resolved = resolve_inside(self.project.root, value)
                    assert_not_protected(
                        relpath_posix(self.project.root, resolved), self.project.permissions.protected_paths
                    )
                except PathRejected as exc:
                    # Outside the approved scope: blocked (exit 2), no effect.
                    raise TaskAbort(
                        ErrorCode.PERMISSION_REQUIRED,
                        str(exc),
                        recovery="provide a path relative to the project, outside the protected patterns",
                        details={"parameter": key, "reason": exc.reason},
                        status=OperationStatus.blocked,
                    ) from exc
        if spec.backend == "host" and spec.name not in HOST_HANDLERS:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"{spec.name} does not run through `fluidblend run`",
                recovery=f"use the dedicated subcommand: {spec.cli_command or 'see fluidblend --help'}",
                status=OperationStatus.failed,
            )
        if not spec.available:
            raise TaskAbort(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                f"{spec.name} is not available in this batch ({spec.lot})",
                recovery="see docs/roadmap.md",
            )
        allowed, reason = operation_allowed(self.project.permissions, spec)
        if not allowed:
            raise TaskAbort(
                ErrorCode.PERMISSION_REQUIRED,
                reason or "operation not allowed",
                recovery="update config/permissions.json (user decision), then run again",
            )
        estimate = estimate_for(self.project, request, params, spec)
        errors = budget_mod.check_budget(self.project.manifest.budgets, estimate)
        if errors:
            first = errors[0]
            raise TaskAbort(
                first.code,
                first.message,
                recovery=first.recovery,
                details={"estimate": estimate, "all": [e.model_dump() for e in errors]},
            )
        if spec.requires_shot:
            try:
                self.project.shot_manifest(request.target.shot_id or "")
            except ProjectError as exc:
                raise TaskAbort(ErrorCode.VALIDATION_FAILED, str(exc), status=OperationStatus.failed) from exc

    def _idempotency(self, request: OperationRequest, spec: OperationSpec) -> OperationResult | None:
        entry = self.state.ledger_entry(request.operation_id)
        if entry is None:
            return None
        fp = self._fingerprint(request)
        status = entry["status"]
        if status == OperationStatus.succeeded:
            if entry["fingerprint"] != fp:
                raise TaskAbort(
                    ErrorCode.SCENE_CONFLICT,
                    f"operation_id {request.operation_id} already ran with different parameters",
                    recovery="use a new operation_id",
                    details={"previous_task": entry["task_id"]},
                )
            path = self.project.root / entry["result_path"] if entry.get("result_path") else None
            if path and path.exists():
                self.project.journal().append(
                    "replayed", operation_id=request.operation_id, task_id=entry["task_id"]
                )
                return OperationResult.model_validate(read_json(path))
            raise TaskAbort(
                ErrorCode.TIMEOUT_UNKNOWN_STATE,
                "published result not found",
                recovery=f"fluidblend task reconcile --id {entry['task_id']}",
            )
        if status in (
            OperationStatus.running,
            OperationStatus.validating,
            OperationStatus.unknown,
            OperationStatus.queued,
        ):
            raise TaskAbort(
                ErrorCode.TIMEOUT_UNKNOWN_STATE,
                f"operation_id {request.operation_id} has a task in state {status}",
                recovery=f"fluidblend task reconcile --id {entry['task_id']} before any new attempt",
                details={"previous_task": entry["task_id"]},
            )
        return None

    def _resolve_source(self, request: OperationRequest, spec: OperationSpec) -> Path | None:
        if not spec.requires_shot:
            return None
        shot_id = request.target.shot_id or ""
        latest = self.project.latest_work_blend(shot_id)
        if latest is None:
            if spec.name == "scene.build":
                return None
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"no work version for {shot_id}",
                recovery="run scene.build first",
                status=OperationStatus.failed,
            )
        return latest[1]

    def _check_revision(self, request: OperationRequest, spec: OperationSpec) -> None:
        if spec.op_class == "read" or not request.target.shot_id:
            return
        target = f"shot:{request.target.shot_id}"
        check = self.revisions.check(target, request.target.expected_revision)
        if check.ok:
            return
        recovery = {
            "external_change": f"manual change detected and preserved; accept it with `fluidblend revision accept --project . --target {request.target.shot_id}` then run again",
            "revision_mismatch": f"current revision {check.current.revision if check.current else '?'}; re-read `fluidblend inspect` and fix target.expected_revision",
            "source_missing": "the recorded source has disappeared; restore it from checkpoints/",
            "revision_unknown": "no revision recorded for this target; omit expected_revision",
        }[check.reason or "revision_unknown"]
        raise TaskAbort(
            ErrorCode.SCENE_CONFLICT,
            f"revision of {target}: {check.reason}",
            recovery=recovery,
            details={
                "expected_revision": request.target.expected_revision,
                "current_revision": check.current.revision if check.current else None,
                "recorded_sha256": check.current.sha256 if check.current else None,
                "observed_sha256": check.observed_sha256,
            },
        )

    def _create_task(self, request: OperationRequest, spec: OperationSpec) -> TaskRecord:
        previous = self.state.ledger_entry(request.operation_id)
        attempts = 0
        if previous:
            prior = self.state.task(previous["task_id"])
            attempts = prior.attempts if prior else 0
        task = TaskRecord(
            task_id=new_id("task"),
            operation_id=request.operation_id,
            operation=spec.name,
            project_id=request.project_id,
            status=OperationStatus.queued,
            fingerprint=self._fingerprint(request),
            expected_revision=request.target.expected_revision,
            target=request.target.model_dump(exclude_none=True),
            budget=self.project.manifest.budgets.model_dump(),
            attempts=attempts,
            created_at=now_iso(),
            updated_at=now_iso(),
            mode=self.mode if spec.name in LIVE_OPERATIONS else "batch",
        )
        self._task_dir(task.task_id).mkdir(parents=True, exist_ok=False)
        (self._task_dir(task.task_id) / "out").mkdir()
        self.state.upsert_task(task)
        return task

    def _execute(
        self,
        request: OperationRequest,
        params: StrictModel,
        spec: OperationSpec,
        task: TaskRecord,
        source: Path | None,
    ) -> OperationResult:
        task_dir = self._task_dir(task.task_id)
        out_dir = task_dir / "out"
        if self.mode == "live" and spec.name in LIVE_OPERATIONS:
            return self._execute_live(request, spec, task, source, task_dir, out_dir)
        if spec.backend == "host":
            handler = HOST_HANDLERS.get(spec.name)
            if handler is None:
                raise TaskAbort(ErrorCode.UNSUPPORTED_CAPABILITY, f"no host handler for {spec.name}")
            ctx = HostContext(
                project=self.project,
                request=request,
                params=params,
                task_id=task.task_id,
                task_dir=task_dir,
                out_dir=out_dir,
            )
            try:
                handler(ctx)
            except HostOpError as exc:
                return ctx.result(
                    OperationStatus.failed,
                    [
                        ErrorRecord(
                            code=exc.code, message=str(exc), recovery=exc.recovery, details=exc.details
                        )
                    ],
                )
            return ctx.result()

        executable = self._blender_executable()
        envelope = self._envelope(request, spec, task, source, task_dir, out_dir, live=False)
        timeout = float(
            self.test_hooks.get("timeout_s") or self.project.manifest.budgets.max_task_minutes * 60
        )

        def on_started(info: dict[str, Any]) -> None:
            task.worker = WorkerInfo(**info)
            self.state.upsert_task(task)

        outcome = blender_batch.run_operation(
            executable,
            envelope,
            task_dir,
            task_id=task.task_id,
            timeout_s=timeout,
            on_worker_started=on_started,
        )
        if outcome.result is None:
            code = ErrorCode.TIMEOUT_UNKNOWN_STATE
            message = (
                "time budget exceeded, worker stopped"
                if outcome.timed_out
                else f"worker exited (exit {outcome.exit_code}) without result.json"
            )
            task.status = OperationStatus.unknown
            task.errors.append(
                ErrorRecord(
                    code=code,
                    message=message,
                    recovery=f"fluidblend task reconcile --project . --id {task.task_id}",
                    details={"stderr_tail": outcome.stderr_tail, "error": outcome.error},
                )
            )
            task.partial_effects = self._partial_effects(task.task_id)
            self.state.upsert_task(task)
            raise TaskAbort(
                code,
                message,
                recovery=task.errors[-1].recovery,
                details=task.errors[-1].details,
                status=OperationStatus.unknown,
            )
        try:
            result = OperationResult.model_validate(outcome.result)
        except ValidationError as exc:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"result.json does not conform: {exc}",
                status=OperationStatus.failed,
            ) from exc
        result.metrics["blender_elapsed_s"] = round(outcome.elapsed_s, 2)
        result.metrics["blender_exit_code"] = outcome.exit_code
        return result

    def _envelope(
        self,
        request: OperationRequest,
        spec: OperationSpec,
        task: TaskRecord,
        source: Path | None,
        task_dir: Path,
        out_dir: Path,
        *,
        live: bool,
    ) -> dict[str, Any]:
        shot = None
        if request.target.shot_id:
            shot = self.project.shot_manifest(request.target.shot_id).model_dump(mode="json")
        return {
            "schema_version": "1.0",
            "task_id": task.task_id,
            "request": request.model_dump(mode="json"),
            "context": {
                "project_root": str(self.project.root),
                "task_dir": str(task_dir),
                "out_dir": str(out_dir),
                "work_blend": None
                if live
                else (str(source) if source and spec.name != "scene.build" else None),
                "live": live,
                "shot": shot,
                "fps": self.project.manifest.fps.model_dump(),
                "preview": self.project.manifest.preview.model_dump(),
                "budgets": self.project.manifest.budgets.model_dump(),
                "quality": self.project.quality.model_dump(),
                "runtime_expected_version": __version__,
                "test_hooks": self.test_hooks,
            },
        }

    def _execute_live(
        self,
        request: OperationRequest,
        spec: OperationSpec,
        task: TaskRecord,
        source: Path | None,
        task_dir: Path,
        out_dir: Path,
    ) -> OperationResult:
        """Run the operation on the open Blender session (identity checked, approved runtime operators only)."""
        config = blender_live.server_config_for(self.project)
        try:
            ident = blender_live.identity(config)
        except blender_live.LiveError as exc:
            code = (
                ErrorCode.UNSUPPORTED_CAPABILITY
                if exc.kind == "tool_missing"
                else ErrorCode.MISSING_DEPENDENCY
            )
            raise TaskAbort(
                code,
                str(exc),
                recovery=(
                    "open Blender 5.2 (GUI) on the shot's latest work version with the MCP add-on server "
                    "started, and enable the runtime add-on (`fluidblend runtime install --enable`)"
                ),
                details={"kind": exc.kind, "server": config.source},
            ) from exc
        expected = source if spec.requires_shot else None
        problems = blender_live.check_identity(
            ident, project_id=self.project.project_id, expected_blend=expected, runtime_version=__version__
        )
        if spec.name == "scene.checkpoint":
            # A snapshot of an unsaved scene is precisely what a checkpoint is for.
            problems = [p for p in problems if "unsaved changes" not in p]
        if problems:
            raise TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                "live session does not match the request: " + "; ".join(problems),
                recovery="open the latest work version of the shot in Blender, save or revert pending changes, then retry",
                details={"identity": ident, "expected_blend": str(expected) if expected else None},
            )
        self.project.journal().append("live_identity_checked", task_id=task.task_id, identity=ident)
        envelope = self._envelope(request, spec, task, source, task_dir, out_dir, live=True)
        request_path = task_dir / "request.json"
        result_path = task_dir / "result.json"
        atomic_write_json(request_path, envelope)
        if result_path.exists():
            result_path.unlink()
        timeout = float(self.test_hooks.get("live_call_timeout_s") or config.call_timeout_s)
        try:
            data = blender_live.run_request(
                config,
                request_path,
                result_path,
                what=f"{spec.name} {request.operation_id}",
                timeout_s=timeout,
            )
        except blender_live.LiveError as exc:
            if exc.kind == "timeout":
                task.status = OperationStatus.unknown
                task.errors.append(
                    ErrorRecord(
                        code=ErrorCode.TIMEOUT_UNKNOWN_STATE,
                        message="live call timed out; the open scene may have been modified",
                        recovery=(
                            f"fluidblend task reconcile --project . --id {task.task_id}; "
                            "then reopen the latest work version in Blender before retrying"
                        ),
                    )
                )
                task.partial_effects = self._partial_effects(task.task_id)
                self.state.upsert_task(task)
                raise TaskAbort(
                    ErrorCode.TIMEOUT_UNKNOWN_STATE,
                    task.errors[-1].message,
                    recovery=task.errors[-1].recovery,
                    status=OperationStatus.unknown,
                ) from exc
            code = ErrorCode.INTERNAL_ERROR if exc.kind == "script_error" else ErrorCode.MISSING_DEPENDENCY
            raise TaskAbort(code, str(exc), status=OperationStatus.failed) from exc
        try:
            result = OperationResult.model_validate(data)
        except ValidationError as exc:
            raise TaskAbort(
                ErrorCode.VALIDATION_FAILED,
                f"result.json is not conformant: {exc}",
                status=OperationStatus.failed,
            ) from exc
        result.metrics["mode"] = "live"
        result.metrics["live_identity"] = {
            k: ident.get(k) for k in ("blend_path", "revision", "runtime_version")
        }
        return result

    def _live_reload(self, request: OperationRequest, task: TaskRecord, result: OperationResult) -> None:
        """After publishing a new version from a live write, point the open session at the published file."""
        blend = next((self.project.root / a.path for a in result.artifacts if a.kind == "blend"), None)
        if blend is None:
            return
        config = blender_live.server_config_for(self.project)
        try:
            opened = blender_live.open_file(config, blend)
        except blender_live.LiveError as exc:
            opened = {"ok": False, "error": str(exc)}
        self.project.journal().append(
            "live_session_reloaded",
            task_id=task.task_id,
            path=relpath_posix(self.project.root, blend),
            **opened,
        )
        result.metrics["live_session_reloaded"] = bool(opened.get("ok"))
        if not opened.get("ok"):
            result.warnings.append(
                f"the open Blender session could not be reloaded on {relpath_posix(self.project.root, blend)}; "
                "reopen it manually before saving, otherwise the previous version would be overwritten"
            )

    def _postprocess(
        self,
        request: OperationRequest,
        params: StrictModel,
        spec: OperationSpec,
        task: TaskRecord,
        result: OperationResult,
    ) -> OperationResult:
        out_dir = self._task_dir(task.task_id) / "out"
        if spec.name == "shot.preview":
            return self._assemble_preview(out_dir, result)
        if spec.name == "game.export":
            return self._validate_glb(out_dir, result)
        if spec.name == "animation.retime" and result.metrics.get("duration_scale"):
            result.metrics.setdefault("convention", "duration_scale multiplies the duration")
        return result

    def _assemble_preview(self, out_dir: Path, result: OperationResult) -> OperationResult:
        report = read_json(out_dir / "render-report.json")
        engine = report.get("engine", "WORKBENCH")
        if report.get("seconds_per_frame"):
            budget_mod.record_metric(
                self.project.root, f"render.seconds_per_frame.{engine}", float(report["seconds_per_frame"])
            )
        ffmpeg = ff.find_tool("ffmpeg", self.project.local.ffmpeg_executable)
        ffprobe = ff.find_tool("ffprobe", self.project.local.ffprobe_executable)
        if not ffmpeg or not ffprobe:
            result.warnings.append(
                "ffmpeg/ffprobe missing: frames published without video (capability video_assembly = not_installed)"
            )
            result.metrics["video"] = "not_run"
            return result
        frames_dir = out_dir / "frames"
        video = out_dir / "preview.mp4"
        fps = self.project.manifest.fps
        step = int(report.get("step", 1))
        if step != 1:
            # A sequence with step > 1 is resampled at the project frame rate: documented in the report.
            result.warnings.append(
                f"step={step}: the video plays the rendered frames at {fps.as_float():g} fps, shorter duration"
            )
        assemble = ff.assemble_sequence(
            ffmpeg,
            frames_dir / "frame_%04d.png",
            start_number=int(report["frame_start"]),
            fps=fps,
            output=video,
        )
        if not assemble.ok:
            result.status = OperationStatus.failed
            result.errors.append(
                ErrorRecord(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="FFmpeg assembly failed",
                    details={"stderr": assemble.stderr_tail},
                )
            )
            return result
        probe = ff.probe(ffprobe, video)
        atomic_write_json(out_dir / "ffprobe.json", probe)
        observed = (probe.get("video") or {}).get("nb_read_frames")
        expected = int(report["produced_frames"])
        rate_ok = ff.frame_rate_matches((probe.get("video") or {}).get("r_frame_rate"), fps)
        result.artifacts.append(
            Artifact(
                kind="video",
                path="preview.mp4",
                sha256=sha256_file(video),
                bytes=video.stat().st_size,
                metrics={
                    "nb_read_frames": observed,
                    "r_frame_rate": (probe.get("video") or {}).get("r_frame_rate"),
                },
            )
        )
        result.artifacts.append(
            Artifact(
                kind="report",
                path="ffprobe.json",
                sha256=sha256_file(out_dir / "ffprobe.json"),
                bytes=(out_dir / "ffprobe.json").stat().st_size,
            )
        )
        result.metrics.update(
            {
                "video_frames": observed,
                "video_frame_rate_ok": rate_ok,
                "video_duration_s": probe.get("duration_s"),
            }
        )
        if observed != expected or not rate_ok:
            result.status = OperationStatus.failed
            result.errors.append(
                ErrorRecord(
                    code=ErrorCode.VALIDATION_FAILED,
                    message=f"video: {observed} frames / frame rate ok={rate_ok}, expected {expected} at {fps.numerator}/{fps.denominator}",
                )
            )
        return result

    def _validate_glb(self, out_dir: Path, result: OperationResult) -> OperationResult:
        glb = next((a for a in result.artifacts if a.kind == "glb"), None)
        if glb is None:
            return result
        validator = gltfv.find_validator(self.project.local.gltf_validator_executable)
        if not validator:
            result.warnings.append(
                "gltf_validator missing: Khronos validation not_run (capability not_installed)"
            )
            result.metrics["khronos_validation"] = "not_run"
            return result
        try:
            summary = gltfv.validate(validator, out_dir / glb.path, out_dir / "gltf-validator.json")
        except (RuntimeError, ValueError, OSError) as exc:
            result.status = OperationStatus.failed
            result.errors.append(
                ErrorRecord(code=ErrorCode.VALIDATION_FAILED, message=f"glTF validator: {exc}")
            )
            return result
        report_path = out_dir / "gltf-validator.json"
        result.artifacts.append(
            Artifact(
                kind="report",
                path="gltf-validator.json",
                sha256=sha256_file(report_path),
                bytes=report_path.stat().st_size,
            )
        )
        result.metrics["khronos_validation"] = {k: v for k, v in summary.items() if k != "info"}
        result.metrics["khronos_info"] = summary.get("info", {})
        if not summary["passed"]:
            result.status = OperationStatus.failed
            result.errors.append(
                ErrorRecord(
                    code=ErrorCode.VALIDATION_FAILED,
                    message=f"Khronos validation: {summary['num_errors']} error(s)",
                    details={"codes": summary["blocking_errors"]},
                )
            )
        return result

    def _verify_artifacts(self, task: TaskRecord, result: OperationResult) -> None:
        out_dir = self._task_dir(task.task_id) / "out"
        for artifact in result.artifacts:
            path = out_dir / artifact.path
            if not path.exists():
                raise TaskAbort(
                    ErrorCode.VALIDATION_FAILED,
                    f"declared artifact is missing: {artifact.path}",
                    status=OperationStatus.failed,
                )
            if path.is_file() and artifact.sha256 and sha256_file(path) != artifact.sha256:
                raise TaskAbort(
                    ErrorCode.VALIDATION_FAILED,
                    f"hash mismatch for {artifact.path}",
                    status=OperationStatus.failed,
                )

    def _publish(
        self, request: OperationRequest, spec: OperationSpec, task: TaskRecord, result: OperationResult
    ) -> OperationResult:
        out_dir = self._task_dir(task.task_id) / "out"
        shot_id = request.target.shot_id
        journal = self.project.journal()
        if spec.creates_version and shot_id:
            version_no, version_dir = self.project.next_version_dir(shot_id)
            base = self.project.root / "reviews" / shot_id / request.operation_id
        else:
            version_no, version_dir = None, None
            folder = {"render": "renders", "export": "exports"}.get(spec.op_class, "reviews")
            base = self.project.root / folder / (shot_id or "project") / request.operation_id
        if base.exists() and any(base.iterdir()):
            raise TaskAbort(
                ErrorCode.SCENE_CONFLICT,
                f"destination already occupied: {relpath_posix(self.project.root, base)}",
                status=OperationStatus.failed,
            )
        base.mkdir(parents=True, exist_ok=True)
        moved: dict[str, str] = {}
        for entry in sorted(out_dir.iterdir()):
            if version_dir is not None and entry.suffix == ".blend":
                version_dir.mkdir(parents=True, exist_ok=False)
                destination = version_dir / entry.name
            else:
                destination = base / entry.name
            shutil.move(str(entry), str(destination))
            moved[entry.name] = relpath_posix(self.project.root, destination)
        published: list[Artifact] = []
        for artifact in result.artifacts:
            head, _, tail = artifact.path.partition("/")
            new_rel = moved[head] + (f"/{tail}" if tail else "")
            published.append(artifact.model_copy(update={"path": new_rel}))
            journal.append(
                "artifact_published",
                task_id=task.task_id,
                operation_id=request.operation_id,
                kind=artifact.kind,
                path=new_rel,
                sha256=artifact.sha256,
            )
        result.artifacts = published
        if version_dir is not None and shot_id:
            blend = next((self.project.root / a.path for a in published if a.kind == "blend"), None)
            if blend is None:
                raise TaskAbort(
                    ErrorCode.VALIDATION_FAILED,
                    "versioning operation without a published .blend",
                    status=OperationStatus.failed,
                )
            record = self.revisions.record(f"shot:{shot_id}", blend, origin="kit")
            result.new_revision = record.revision
            result.changed_entities.append(ChangedEntity(kind="file", id=record.path, change="created"))
            journal.append(
                "revision_updated",
                target=record.target,
                revision=record.revision,
                path=record.path,
                sha256=record.sha256,
                task_id=task.task_id,
            )
            result.metrics["work_version"] = f"v{version_no:03d}"
        if spec.name == "scene.checkpoint" and self.mode == "live":
            blend = next((self.project.root / a.path for a in published if a.kind == "blend"), None)
            if blend is not None:
                manifest = create_file_checkpoint(
                    self.project.root, blend, label="live", task_id=task.task_id
                )
                task.checkpoint_id = manifest["checkpoint_id"]
                journal.append(
                    "checkpoint_created",
                    **{k: manifest[k] for k in ("checkpoint_id", "source", "sha256")},
                    task_id=task.task_id,
                )
        result.checkpoint_id = task.checkpoint_id
        result.task_id = task.task_id
        return result

    # --- Helpers --------------------------------------------------------------------------

    def _blender_executable(self) -> str:
        local = self.project.local
        if local.blender_executable and Path(local.blender_executable).exists():
            return local.blender_executable
        candidate, _probe, notes = blender_discovery.select_blender(
            local, allow_unlocked=self.allow_unlocked_blender, probe=False
        )
        if candidate is None:
            raise TaskAbort(
                ErrorCode.MISSING_DEPENDENCY,
                f"no Blender {blender_discovery.LOCKED_BLENDER_SERIES} found",
                recovery="run `fluidblend doctor --project .` then set blender_executable in config/local.json",
                details={"notes": notes},
            )
        return candidate.path

    def _fingerprint(self, request: OperationRequest) -> str:
        return fingerprint(
            {
                "operation": request.operation,
                "target": request.target.model_dump(exclude_none=True),
                "parameters": request.parameters,
                "expected_revision": request.target.expected_revision,
            }
        )

    def _task_dir(self, task_id: str) -> Path:
        return self.project.root / "state" / "tasks" / task_id

    def _partial_effects(self, task_id: str) -> list[str]:
        out_dir = self._task_dir(task_id) / "out"
        if not out_dir.exists():
            return []
        return sorted(relpath_posix(self.project.root, p) for p in out_dir.rglob("*") if p.is_file())[:200]

    def _save_result(self, task: TaskRecord, result: OperationResult) -> str:
        path = self._task_dir(task.task_id) / "result.published.json"
        atomic_write_json(path, result.model_dump(mode="json"))
        return relpath_posix(self.project.root, path)

    def _dry_run_result(
        self, request: OperationRequest, spec: OperationSpec, task: TaskRecord
    ) -> OperationResult:
        from fluidblend.core.planner import make_plan

        _req, params, _spec = validate_request(request.model_dump(mode="json"))
        plan = make_plan(self.project, request, params, spec, save=True)
        return OperationResult(
            operation_id=request.operation_id,
            operation=spec.name,
            task_id=task.task_id,
            status=OperationStatus.planned,
            warnings=plan.warnings,
            metrics={"plan": plan.model_dump(mode="json")},
            next_safe_actions=["fluidblend run --project . --operation <same request without dry_run>"],
        )

    def _finish_failed(self, task: TaskRecord, result: OperationResult) -> RunOutcome:
        task.status = OperationStatus.failed
        task.errors = result.errors
        task.partial_effects = self._partial_effects(task.task_id)
        task.result_path = self._save_result(task, result)
        self.state.upsert_task(task)
        result.task_id = task.task_id
        code = (
            BLOCKED_EXIT.get(result.errors[0].code, exit_codes.FAILED) if result.errors else exit_codes.FAILED
        )
        return RunOutcome(result, code if code != exit_codes.INVALID else exit_codes.FAILED, task)

    def _aborted(
        self, request: OperationRequest, spec: OperationSpec, task: TaskRecord | None, abort: TaskAbort
    ) -> RunOutcome:
        result = OperationResult(
            operation_id=request.operation_id,
            operation=spec.name,
            task_id=task.task_id if task else None,
            status=abort.status,
            errors=[abort.error],
            next_safe_actions=[abort.error.recovery] if abort.error.recovery else [],
        )
        if task is not None:
            if abort.status != OperationStatus.unknown:
                task.status = abort.status
            task.errors = [abort.error]
            task.result_path = self._save_result(task, result)
            self.state.upsert_task(task)
        else:
            self.project.journal().append(
                "request_blocked",
                operation_id=request.operation_id,
                operation=spec.name,
                code=abort.error.code,
                message=abort.error.message,
            )
        return RunOutcome(result, BLOCKED_EXIT.get(abort.error.code, exit_codes.FAILED), task)

    def _rejected(
        self, payload: dict[str, Any], code: ErrorCode, message: str, *, details: dict[str, Any]
    ) -> OperationResult:
        operation_id = str(payload.get("operation_id") or "invalid")
        operation = str(payload.get("operation") or "unknown")
        self.project.journal().append(
            "request_rejected", operation_id=operation_id, operation=operation, message=message
        )
        return OperationResult(
            operation_id=operation_id if len(operation_id) >= 3 else "invalid-request",
            operation=operation,
            status=OperationStatus.failed,
            errors=[
                ErrorRecord(
                    code=code,
                    message=message,
                    details=details,
                    recovery="fix the request to match schemas/operation-request.json",
                )
            ],
        )
