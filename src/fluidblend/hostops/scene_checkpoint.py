"""scene.checkpoint: copy of the latest work version of the shot (batch: the file is the truth)."""

from __future__ import annotations

from fluidblend.contracts.common import ErrorCode
from fluidblend.core.checkpoints import create_file_checkpoint
from fluidblend.hostops.context import HostContext, HostOpError


def run(ctx: HostContext) -> None:
    shot_id = ctx.request.target.shot_id or ""
    latest = ctx.project.latest_work_blend(shot_id)
    if latest is None:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"no work version for {shot_id}",
            recovery="run scene.build",
        )
    version, path = latest
    label = getattr(ctx.params, "label", "manual")
    manifest = create_file_checkpoint(ctx.project.root, path, label=label, task_id=ctx.task_id)
    ctx.checkpoint_id = manifest["checkpoint_id"]
    ctx.metrics.update(
        {"source_version": f"v{version:03d}", "bytes": manifest["bytes"], "sha256": manifest["sha256"]}
    )
    ctx.write_report("checkpoint.json", manifest)
    ctx.project.journal().append(
        "checkpoint_created", checkpoint_id=ctx.checkpoint_id, source=manifest["source"], task_id=ctx.task_id
    )
