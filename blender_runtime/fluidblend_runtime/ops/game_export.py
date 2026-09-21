"""game.export: explicit GLB (Y-up, sampled actions), then a control re-import into a fresh scene."""

from __future__ import annotations

import json
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


# Bones a consumer can find again on the other side, plus the extremes that reveal height and up axis.
REFERENCE_BONES = ("DEF-spine", "DEF-head", "DEF-hand.L", "DEF-foot.L", "DEF-upper_arm.L")


def _reference_pose(rig, limit=5):
    """World head of a few deform bones at REST, in metres.

    This is what lets an engine-side kit *measure* the scale and the up axis it really got instead
    of assuming a conversion factor. `head_local` is the rest head, so nothing in the scene moves.
    """
    deform = [b for b in rig.data.bones if b.use_deform]
    if not deform:
        return []
    chosen = [b for b in deform if b.name in REFERENCE_BONES][:limit]
    ranked = sorted(deform, key=lambda b: (rig.matrix_world @ b.head_local).z)
    for bone in (ranked[0], ranked[-1]):
        if bone not in chosen:
            chosen.append(bone)
    chosen = sorted({b.name: b for b in chosen}.values(), key=lambda b: b.name)[:limit]
    return [
        {"bone": b.name, "head_m": [round(v, 6) for v in (rig.matrix_world @ b.head_local)]} for b in chosen
    ]


def _instance_report(chosen, exported, expected_actions, export_def_bones):
    """Per-instance facts the hand-off bundle needs, read from the scene before the re-import."""
    skinned_by_instance = {}
    for obj in chosen:
        if obj.type != "MESH":
            continue
        owner = obj.get("fluidblend_instance_id") or obj.get("fluidblend_part_of")
        if owner and any(m.type == "ARMATURE" for m in obj.modifiers):
            skinned_by_instance[owner] = True
    rows = []
    for obj in chosen:
        instance_id = obj.get("fluidblend_instance_id")
        if not instance_id:
            continue
        is_rig = obj.type == "ARMATURE"
        node = obj.name
        rows.append(
            {
                "instance_id": instance_id,
                "asset_id": obj.get("fluidblend_asset_id"),
                "asset_version": obj.get("fluidblend_asset_version"),
                "kind": obj.get("fluidblend_kind", "character"),
                "rig_profile": obj.get("fluidblend_rig_profile"),
                "armature": node if is_rig else None,
                "skinned": bool(skinned_by_instance.get(instance_id, False)),
                "baked": bool(obj.get("fluidblend_baked")),
                "export_def_bones": bool(export_def_bones),
                "bone_count": int(exported["armatures"].get(node, 0)),
                "gltf_node_name": node,
                "grips": json.loads(obj.get("fluidblend_grips", "{}")),
                "animations": [a for a in expected_actions if a.startswith(node + ".")],
                "reference_pose": _reference_pose(obj) if is_rig else [],
            }
        )
    return rows


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
        "node_names": [o.name for o in chosen],
        "instances": _instance_report(chosen, exported, expected_actions, settings["export_def_bones"]),
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
        # The bundle names glTF nodes; if the exporter renamed one, say so rather than assume.
        seen_rigs = set(reimport["armatures"])
        for row in report["instances"]:
            if row["armature"] and row["gltf_node_name"] not in seen_rigs:
                builder.warn(
                    f"the exporter renamed node {row['gltf_node_name']!r}: "
                    f"the re-import shows {sorted(seen_rigs)}"
                )
                row["gltf_node_name_verified"] = False
            elif row["armature"]:
                row["gltf_node_name_verified"] = True
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
