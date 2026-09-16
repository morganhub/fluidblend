"""scene.build: P0 demonstration scene (two stylized bipeds, one lantern, camera, set)."""

from __future__ import annotations

import os

import bpy

from fluidblend_runtime import RUNTIME_VERSION, blendio, render
from fluidblend_runtime.build import biped
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.ops import scene_audit, scene_inspect

COLORS = [
    (0.20, 0.45, 0.85, 1.0),
    (0.90, 0.50, 0.20, 1.0),
    (0.40, 0.75, 0.35, 1.0),
    (0.75, 0.30, 0.65, 1.0),
]


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    shot = ctx.shot
    if not shot:
        raise OpError("VALIDATION_FAILED", "scene.build requires the shot manifest in the context")
    shot_id = shot["shot_id"]
    frames = int(params.get("frames", shot["frame_range"]["end_exclusive"] - shot["frame_range"]["start"]))
    frame_start = int(shot["frame_range"]["start"])
    frame_end = frame_start + frames - 1

    blendio.new_empty()
    scene = bpy.context.scene
    scene.name = shot_id
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    render.configure(
        scene,
        engine=ctx.preview_engine,
        width=ctx.preview_width,
        height=ctx.preview_height,
        fps_numerator=ctx.fps_numerator,
        fps_denominator=ctx.fps_denominator,
    )
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.55, 0.65, 0.80)

    characters = biped.ensure_collection("Characters")
    props = biped.ensure_collection("Props")
    set_coll = biped.ensure_collection("Set")
    camera_coll = biped.ensure_collection("Camera")

    built = []
    for index, instance in enumerate(shot.get("instances", [])):
        arm, parts, action = biped.build_character(
            instance, frames=frames, collection=characters, color=COLORS[index % len(COLORS)]
        )
        built.append((instance, arm, parts, action))
        builder.changed("instance", instance["instance_id"], "created")
        builder.changed("clip", action.name, "created")
    if not built:
        raise OpError("VALIDATION_FAILED", "the shot declares no character instance")

    for prop in shot.get("props", []):
        holder = built[0][1]
        obj = biped.build_prop_lantern(prop, holder, collection=props)
        builder.changed("instance", obj["fluidblend_instance_id"], "created")
    biped.build_ground(set_coll)
    biped.build_camera(shot.get("camera", {}), camera_coll)
    biped.build_light(set_coll)

    blendio.set_identity(
        scene, project_id=ctx.project_id, shot_id=shot_id, revision=1, runtime_version=RUNTIME_VERSION
    )

    blend_path = ctx.out(f"{shot_id}.blend")
    blendio.save_as(blend_path)
    # Immediate re-open: proof that the file reopens and holds what is announced.
    blendio.open_blend(blend_path)
    summary = scene_inspect.summarize(include_actions=True, include_bones=True)
    audit_report = scene_audit.audit()
    builder.add_file(
        "blend", blend_path, objects=summary["counts"]["objects"], actions=summary["counts"]["actions"]
    )
    builder.write_report("scene-summary.json", summary)
    builder.write_report("audit.json", audit_report)
    builder.changed("shot", shot_id, "versioned")
    builder.metrics.update(
        {
            "frames": frames,
            "frame_start": frame_start,
            "frame_end_inclusive": frame_end,
            "fps": ctx.fps_float,
            "objects": summary["counts"]["objects"],
            "armatures": summary["counts"]["armatures"],
            "actions": summary["counts"]["actions"],
            "audit_passed": audit_report["passed"],
            "reopened": os.path.isfile(blend_path),
            "blend_bytes": os.path.getsize(blend_path),
        }
    )
    if not audit_report["passed"]:
        raise OpError(
            "VALIDATION_FAILED",
            f"audit of the built scene: {audit_report['error_count']} error(s)",
            details=audit_report,
        )
    builder.next_safe_actions.extend(["shot.preview", "scene.inspect", "animation.retime", "game.export"])
