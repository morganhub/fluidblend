"""game.export: explicit GLB (Y-up, sampled actions), then a control re-import into a fresh scene."""

from __future__ import annotations

import os

import bpy

from fluidblend_runtime import blendio
from fluidblend_runtime.errors import OpError

AXIS_CONVENTION = {"blender": {"up": "+Z", "forward": "-Y"}, "gltf": {"up": "+Y", "forward": "+Z"}}


def _select_export_set(instance_ids):
    for obj in bpy.data.objects:
        obj.select_set(False)
    chosen = []
    instances = blendio.instance_objects()
    if instance_ids:
        wanted = set(instance_ids)
        instances = [o for o in instances if o.get("fluidblend_instance_id") in wanted]
        missing = wanted - {o.get("fluidblend_instance_id") for o in instances}
        if missing:
            raise OpError("VALIDATION_FAILED", f"missing instances: {sorted(missing)}")
    # A held prop is both an instance and a child of a character: de-duplicate by name.
    seen: dict[str, object] = {}
    for obj in instances:
        seen.setdefault(obj.name, obj)
        for child in obj.children_recursive:
            seen.setdefault(child.name, child)
    chosen = list(seen.values())
    for obj in chosen:
        obj.select_set(True)
    return chosen


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    name = params["output_name"]
    chosen = _select_export_set(params.get("instance_ids"))
    if not chosen:
        raise OpError("VALIDATION_FAILED", "no instance object to export")
    armatures = [o for o in chosen if o.type == "ARMATURE"]
    expected_actions = sorted(
        {o.animation_data.action.name for o in armatures if o.animation_data and o.animation_data.action}
    )
    glb_path = ctx.out(f"{name}.glb")
    settings = {
        "filepath": glb_path,
        "export_format": "GLB",
        "use_selection": True,
        "export_yup": True,
        "export_apply": False,
        "export_animations": True,
        "export_animation_mode": params.get("animation_mode", "ACTIONS"),
        "export_force_sampling": True,
        "export_optimize_animation_size": True,
        "export_anim_slide_to_zero": bool(params.get("slide_to_zero", True)),
        "export_reset_pose_bones": True,
        "export_skins": True,
        "export_def_bones": bool(params.get("export_def_bones", False)),
        "export_influence_nb": int(params.get("export_influence_nb", 4)),
        "export_cameras": bool(params.get("include_cameras", False)),
        "export_lights": bool(params.get("include_lights", False)),
        "export_extras": True,
        "export_frame_range": True,
    }
    result = bpy.ops.export_scene.gltf(**settings)
    if "FINISHED" not in result or not os.path.isfile(glb_path):
        raise OpError("VALIDATION_FAILED", f"glTF export did not finish: {result}")
    exported = {
        "objects": [o.name for o in chosen],
        "armatures": {o.name: len(o.data.bones) for o in armatures},
        "actions": expected_actions,
        "meshes": sum(1 for o in chosen if o.type == "MESH"),
    }
    report = {
        "glb": os.path.basename(glb_path),
        "bytes": os.path.getsize(glb_path),
        "settings": {k: v for k, v in settings.items() if k != "filepath"},
        "axis_convention": AXIS_CONVENTION,
        "exported": exported,
        "reimport": None,
    }
    if params.get("reimport_check", True):
        blendio.new_empty()
        # disable_bone_shape: otherwise the importer adds "Icosphere" bone-shape meshes.
        imp = bpy.ops.import_scene.gltf(filepath=glb_path, bone_heuristic="BLENDER", disable_bone_shape=True)
        reimport = {
            "result": list(imp),
            "objects": len(bpy.data.objects),
            "armatures": {o.name: len(o.data.bones) for o in bpy.data.objects if o.type == "ARMATURE"},
            "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
            "actions": len(bpy.data.actions),
            "action_names": sorted(a.name for a in bpy.data.actions),
            "extras_instance_ids": sorted(
                {o.get("fluidblend_instance_id") for o in bpy.data.objects if o.get("fluidblend_instance_id")}
            ),
        }
        checks = {
            "armature_count": len(reimport["armatures"]) == len(exported["armatures"]),
            "bone_counts": sorted(reimport["armatures"].values()) == sorted(exported["armatures"].values()),
            "mesh_count": reimport["meshes"] == exported["meshes"],
            "animations_present": reimport["actions"] >= len(exported["actions"])
            if exported["actions"]
            else True,
        }
        reimport["checks"] = checks
        reimport["passed"] = all(checks.values())
        report["reimport"] = reimport
        if not reimport["passed"]:
            builder.write_report("export-report.json", report)
            raise OpError("VALIDATION_FAILED", "GLB re-import inconsistent with the export", details=checks)
    builder.add_file("glb", glb_path, actions=len(expected_actions), armatures=len(armatures))
    builder.write_report("export-report.json", report)
    builder.metrics.update(
        {
            "glb_bytes": report["bytes"],
            "armatures": len(armatures),
            "actions": len(expected_actions),
            "reimport_passed": None if report["reimport"] is None else report["reimport"]["passed"],
        }
    )
    builder.warn(
        "the GLB carries neither constraints nor drivers; P0 characters are not skinned (bone parenting)"
    )
