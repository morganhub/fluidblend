"""animation.retime: new slower/faster clip variant; the source stays untouched (acceptance A08).

`duration_scale = 1.2` -> duration x 1.2 (slower). The contact markers follow the keys.
"""

from __future__ import annotations

import bpy

from fluidblend_runtime import RUNTIME_VERSION, blendio, render
from fluidblend_runtime.anim import slotted
from fluidblend_runtime.errors import OpError


def _duration(action) -> float | None:
    extent = slotted.key_extent(action, slotted.is_pose_channel)
    return None if extent is None else extent[1] - extent[0]


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    target = request["target"]
    scale = float(params["duration_scale"])
    variant = params["output_variant"]
    samples = int(params.get("preview_samples", 8))
    instance_id = target.get("instance_id")
    clip_id = target.get("clip_id")
    if not instance_id or not clip_id:
        raise OpError("VALIDATION_FAILED", "animation.retime requires target.instance_id and target.clip_id")

    obj = blendio.find_instance_object(instance_id)
    if obj is None:
        raise OpError("VALIDATION_FAILED", f"instance not found in the scene: {instance_id}")
    anim = obj.animation_data
    if anim is None or anim.action is None:
        raise OpError("VALIDATION_FAILED", f"{instance_id} has no Action assigned")
    source = anim.action
    if source.get("fluidblend_clip_id") != clip_id:
        raise OpError(
            "SCENE_CONFLICT",
            f"assigned clip {source.get('fluidblend_clip_id')!r} != requested clip {clip_id!r}",
            recovery="inspect the scene (scene.inspect) and fix target.clip_id",
        )
    source_slot = anim.action_slot
    if source_slot is None:
        raise OpError("VALIDATION_FAILED", "Action without an assigned slot")

    scene = bpy.context.scene
    frame_start, frame_end = scene.frame_start, scene.frame_end
    before = {
        "action": source.name,
        "duration_frames": _duration(source),
        "markers": [{"name": m.name, "frame": m.frame} for m in source.pose_markers],
        "source_sha": None,
    }
    if samples:
        render.configure(
            scene,
            engine="WORKBENCH",
            width=max(160, ctx.preview_width // 2),
            height=max(90, ctx.preview_height // 2),
            fps_numerator=ctx.fps_numerator,
            fps_denominator=ctx.fps_denominator,
        )
        before_dir = ctx.out("review", "before", "x")
        before_dir = before_dir[: -len("x")]
        before["preview"] = render.render_samples(
            scene, before_dir, render.sample_frames(frame_start, frame_end, samples)
        )

    origin = slotted.key_extent(source)[0]
    variant_action = source.copy()
    variant_action.name = f"{instance_id}.{variant}"
    stats = slotted.scale_time(variant_action, scale, origin)
    variant_action["fluidblend_clip_id"] = variant
    variant_action["fluidblend_source_clip"] = clip_id
    variant_action["fluidblend_source_action"] = source.name
    variant_action["fluidblend_duration_scale"] = scale
    variant_action.use_fake_user = True

    new_slot = None
    for slot in variant_action.slots:
        if slot.identifier == source_slot.identifier:
            new_slot = slot
    if new_slot is None:
        raise OpError("INTERNAL_ERROR", "slot not found again after copying the Action")
    anim.action = variant_action
    anim.action_slot = new_slot
    source.use_fake_user = True  # the source stays in the file, untouched

    after = {
        "action": variant_action.name,
        "duration_frames": _duration(variant_action),
        "markers": [{"name": m.name, "frame": m.frame} for m in variant_action.pose_markers],
    }
    if samples:
        after_dir = ctx.out("review", "after", "x")[: -len("x")]
        after["preview"] = render.render_samples(
            scene, after_dir, render.sample_frames(frame_start, frame_end, samples)
        )

    expected = (before["duration_frames"] or 0) * scale
    error_frames = abs((after["duration_frames"] or 0) - expected)
    report = {
        "instance_id": instance_id,
        "source_clip": clip_id,
        "output_variant": variant,
        "duration_scale": scale,
        "convention": "duration_scale multiplies the duration; 1.2 = slower (playback speed x 1/1.2)",
        "before": before,
        "after": after,
        "expected_duration_frames": expected,
        "duration_error_frames": error_frames,
        "markers_preserved": len(before["markers"]) == len(after["markers"]),
        "scaled": stats,
        "source_action_intact": source.name in bpy.data.actions
        and _duration(source) == before["duration_frames"],
    }
    if error_frames > 0.5:
        raise OpError(
            "VALIDATION_FAILED",
            f"duration after retime {after['duration_frames']} != expected {expected}",
            details=report,
        )

    identity = blendio.read_identity(scene)
    blendio.set_identity(
        scene,
        project_id=ctx.project_id,
        shot_id=identity.get("shot_id") or (ctx.shot or {}).get("shot_id"),
        revision=int(identity.get("revision") or 0) + 1,
        runtime_version=RUNTIME_VERSION,
    )
    shot_id = (ctx.shot or {}).get("shot_id") or identity.get("shot_id") or "shot"
    blend_path = ctx.out(f"{shot_id}.blend")
    # Live mode: the open file stays untouched, the new version is a copy (the engine reloads it after publishing).
    (blendio.save_copy if ctx.live else blendio.save_as)(blend_path)
    builder.add_file("blend", blend_path)
    builder.write_report("retime-report.json", report)
    if samples:
        builder.add_dir("frames", before_dir, role="before")
        builder.add_dir("frames", after_dir, role="after")
    builder.changed("clip", variant_action.name, "created")
    builder.changed("instance", instance_id, "modified")
    builder.changed("shot", shot_id, "versioned")
    builder.metrics.update(
        {
            "duration_before_frames": before["duration_frames"],
            "duration_after_frames": after["duration_frames"],
            "duration_scale": scale,
            "duration_error_frames": error_frames,
            "markers_before": len(before["markers"]),
            "markers_after": len(after["markers"]),
            "source_action_intact": report["source_action_intact"],
        }
    )
    builder.next_safe_actions.extend(["shot.preview", "scene.inspect"])
