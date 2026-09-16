"""scene.inspect: readable JSON summary of a scene (read-only)."""

from __future__ import annotations

import math

import bpy

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import slotted


def _finite(values) -> bool:
    return all(math.isfinite(float(v)) for v in values)


def summarize(*, include_actions: bool = True, include_bones: bool = False) -> dict:
    scene = bpy.context.scene
    objects = []
    for obj in bpy.data.objects:
        entry = {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "parent_bone": obj.parent_bone or None,
            "location": [round(v, 5) for v in obj.location],
            "finite_transform": _finite(obj.location) and _finite(obj.rotation_euler) and _finite(obj.scale),
            "collections": [c.name for c in obj.users_collection],
            "custom": {k: obj[k] for k in obj.keys() if k.startswith("fluidblend_")},
            "action": obj.animation_data.action.name
            if obj.animation_data and obj.animation_data.action
            else None,
            "action_slot": (
                obj.animation_data.action_slot.identifier
                if obj.animation_data and obj.animation_data.action_slot
                else None
            ),
        }
        if obj.type == "ARMATURE":
            entry["bone_count"] = len(obj.data.bones)
            if include_bones:
                entry["bones"] = [
                    {
                        "name": b.name,
                        "parent": b.parent.name if b.parent else None,
                        "length": round(b.length, 4),
                    }
                    for b in obj.data.bones
                ]
        if obj.type == "MESH":
            entry["vertices"] = len(obj.data.vertices)
            entry["polygons"] = len(obj.data.polygons)
            entry["modifiers"] = [m.type for m in obj.modifiers]
        objects.append(entry)
    summary = {
        "blender": bpy.app.version_string,
        "filepath": bpy.data.filepath,
        "identity": blendio.read_identity(scene),
        "scene": {
            "name": scene.name,
            "fps": scene.render.fps,
            "fps_base": scene.render.fps_base,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_count_inclusive": scene.frame_end - scene.frame_start + 1,
            "resolution": [
                scene.render.resolution_x,
                scene.render.resolution_y,
                scene.render.resolution_percentage,
            ],
            "engine": scene.render.engine,
            "camera": scene.camera.name if scene.camera else None,
            "unit_system": scene.unit_settings.system,
            "unit_scale": scene.unit_settings.scale_length,
        },
        "counts": {
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "armatures": len(bpy.data.armatures),
            "actions": len(bpy.data.actions),
            "materials": len(bpy.data.materials),
            "collections": len(bpy.data.collections),
            "libraries": len(bpy.data.libraries),
            "images": len(bpy.data.images),
        },
        "objects": objects,
        "instances": [
            {
                "instance_id": o.get("fluidblend_instance_id"),
                "kind": o.get("fluidblend_kind"),
                "object": o.name,
            }
            for o in blendio.instance_objects()
        ],
        "missing_files": blendio.missing_external_files(),
    }
    if include_actions:
        summary["actions"] = [slotted.describe(a) for a in bpy.data.actions]
    return summary


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    summary = summarize(
        include_actions=bool(params.get("include_actions", True)),
        include_bones=bool(params.get("include_bones", False)),
    )
    builder.write_report("inspect.json", summary)
    builder.metrics.update(summary["counts"])
    builder.metrics["frame_count_inclusive"] = summary["scene"]["frame_count_inclusive"]
    builder.metrics["identity"] = summary["identity"]
