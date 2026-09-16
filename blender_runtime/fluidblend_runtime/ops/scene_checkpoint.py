"""scene.checkpoint (live mode): snapshot of the open scene with `save_as_mainfile(copy=True)`.

The active file stays untouched (unsaved changes included in the copy); the engine records the copy
under `checkpoints/`. In batch mode the host copies the latest work version instead.
"""

from __future__ import annotations

import os

import bpy

from fluidblend_runtime import blendio


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    label = params.get("label", "manual")
    shot_id = (ctx.shot or {}).get("shot_id") or "scene"
    copy_path = ctx.out(f"{shot_id}.blend")
    was_dirty = bpy.data.is_dirty
    blendio.save_copy(copy_path)
    builder.add_file("blend", copy_path, label=label, was_dirty=was_dirty)
    builder.write_report(
        "checkpoint-live.json",
        {
            "label": label,
            "source_filepath": bpy.data.filepath,
            "was_dirty": was_dirty,
            "identity": blendio.read_identity(bpy.context.scene),
            "bytes": os.path.getsize(copy_path),
        },
    )
    builder.metrics.update({"was_dirty": was_dirty, "bytes": os.path.getsize(copy_path)})
    builder.changed("file", os.path.basename(copy_path), "created")
