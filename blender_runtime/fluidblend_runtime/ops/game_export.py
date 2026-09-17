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


def _deform_heads(armatures, frames):
    """World head of every deform bone, per frame: what a game engine must reproduce."""
    scene = bpy.context.scene
    current, out = scene.frame_current, {}
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for rig in armatures:
            for bone in rig.pose.bones:
                if bone.bone.use_deform:
                    out[(rig.name, bone.name, frame)] = rig.matrix_world @ bone.head
    scene.frame_set(current)
    return out


def _skeleton_fidelity(before, frames, action_by_rig, shift):
    """Replay each re-imported clip and compare deform bone heads, by name, with the exported scene."""
    rigs = {o.name: o for o in bpy.data.objects if o.type == "ARMATURE"}
    for rig in rigs.values():
        action = bpy.data.actions.get(action_by_rig.get(rig.name, ""))
        if action is None or rig.animation_data is None:
            continue
        for track in rig.animation_data.nla_tracks:
            track.mute = True
        rig.animation_data.action = action
        rig.animation_data.action_slot = action.slots[0]
    worst, where, compared = 0.0, None, 0
    for frame in frames:
        # slide_to_zero re-times the exported clip so that it starts at frame 0.
        bpy.context.scene.frame_set(frame - shift)
        bpy.context.view_layer.update()
        for (rig_name, bone_name, at), head in before.items():
            rig = rigs.get(rig_name)
            if at != frame or rig is None or bone_name not in rig.pose.bones:
                continue
            compared += 1
            error = ((rig.matrix_world @ rig.pose.bones[bone_name].head) - head).length
            if error > worst:
                worst, where = error, {"armature": rig_name, "bone": bone_name, "frame": frame}
    return {
        "compared": compared,
        "max_error_m": worst,
        "worst": where,
        "frames": list(frames),
        "shift": shift,
    }


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    name = params["output_name"]
    chosen = _select_export_set(params.get("instance_ids"))
    if not chosen:
        raise OpError("VALIDATION_FAILED", "no instance object to export")
    armatures = [o for o in chosen if o.type == "ARMATURE"]
    # Read now: the control re-import replaces the scene and these objects with it.
    skinned = any(m.type == "ARMATURE" for o in chosen if o.type == "MESH" for m in o.modifiers)
    expected_actions = sorted(
        {o.animation_data.action.name for o in armatures if o.animation_data and o.animation_data.action}
    )
    # A baked skeleton carries one clip and no control layer: it can be replayed after the re-import.
    measurable = bool(armatures) and all(
        o.get("fluidblend_baked") and o.animation_data and o.animation_data.action for o in armatures
    )
    frames = []
    if measurable:
        first, last = (int(v) for v in armatures[0].animation_data.action.frame_range)
        frames = sorted({first + (last - first) * k // 4 for k in range(5)})
    heads = _deform_heads(armatures, frames) if measurable else {}
    action_by_rig = {o.name: o.animation_data.action.name for o in armatures} if measurable else {}
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
        # Blender's default also exports every Action that merely fits the armature: on a baked
        # skeleton that is the control-rig clip, which cannot play on it.
        "export_anim_single_armature": not measurable,
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
        "armatures": {
            o.name: sum(1 for b in o.data.bones if b.use_deform)
            if settings["export_def_bones"]
            else len(o.data.bones)
            for o in armatures
        },
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
            "animations_present": set(exported["actions"]) <= set(reimport["action_names"])
            if measurable
            else reimport["actions"] >= len(exported["actions"]),
        }
        if measurable:
            fidelity = _skeleton_fidelity(
                heads, frames, action_by_rig, frames[0] if settings["export_anim_slide_to_zero"] else 0
            )
            reimport["skeleton_fidelity"] = fidelity
            checks["skeleton_fidelity"] = fidelity["compared"] > 0 and fidelity["max_error_m"] <= 0.001
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
        "the GLB carries neither constraints nor drivers"
        + ("" if skinned else "; P0 characters are not skinned (bone parenting)")
    )
