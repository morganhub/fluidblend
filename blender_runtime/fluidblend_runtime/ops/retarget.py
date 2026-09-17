"""Bounded retargeting between two known rig profiles (§10.4): one preset, a new library clip.

Rotations are transferred as deltas from each rig's own rest pose, in character space, so different
rest poses (arms down against an A-pose) need no manual alignment. The source is only evaluated,
never edited. A few poses are transferred and measured before the whole range is.
"""

import math

import bpy
from mathutils import Matrix

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import measures, slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.ops.animation_library import (
    channels,
    evaluated_alone,
    key_world_offsets,
    refuse_failed,
    require_new,
    require_roles,
    write_manifest,
)
from fluidblend_runtime.production import character, controls_for, save_version


def delta(rig, bone_name):
    """Armature-space rotation of a pose bone relative to its own rest pose."""
    bone = rig.pose.bones[bone_name]
    return bone.matrix.to_quaternion() @ bone.bone.matrix_local.to_quaternion().inverted()


def pose_target(source, target, controls, pairs):
    """Give every mapped target control the source bone's delta, parents first."""
    for source_bone, role in pairs:
        control = controls[role]
        wanted = delta(source, source_bone) @ control.bone.matrix_local.to_quaternion()
        current = control.matrix
        control.matrix = Matrix.LocRotScale(current.translation, wanted, current.to_scale())
        # Children read their parent's evaluated pose: update before going down the chain.
        bpy.context.view_layer.update()


def limb_errors(source, controls, limbs, roles):
    """Angle between where the source deltas send each limb's end and where the target's deform end is."""
    errors = {}
    for name, first, second, _end, end_role in limbs:
        first_control, second_control = controls[roles[first]], controls[roles[second]]
        end = controls[end_role]
        rest_upper = second_control.bone.head_local - first_control.bone.head_local
        rest_lower = end.bone.head_local - second_control.bone.head_local
        predicted = delta(source, first) @ rest_upper + delta(source, second) @ rest_lower
        actual = end.head - first_control.head
        errors[name] = math.degrees(predicted.angle(actual)) if predicted.length and actual.length else 180.0
    return errors


def run(ctx, request, builder):
    preset, params = ctx.inputs["retarget_preset"], request["parameters"]
    target = character(request)
    source = blendio.find_instance_object(params["source_instance_id"])
    if source is None or source.type != "ARMATURE" or source == target:
        raise OpError("VALIDATION_FAILED", "source_instance_id must identify another armature of the scene")
    for rig, key, side in ((source, "source_profile", "source"), (target, "target_profile", "target")):
        if rig.get("fluidblend_rig_profile") != preset[key]:
            raise OpError(
                "RIG_MAPPING_REQUIRED",
                f"this preset needs a {preset[key]} {side}; no other pair of rigs is qualified",
                details={side: rig.get("fluidblend_rig_profile"), "expected": preset[key]},
            )
    if target.get("fluidblend_baked"):
        raise OpError("UNSUPPORTED_CAPABILITY", "a baked export skeleton has no FK control to key")
    action_in = source.animation_data.action if source.animation_data else None
    if action_in is None or action_in.get("fluidblend_clip_id") != params["source_clip"]:
        raise OpError(
            "SCENE_CONFLICT",
            "the source instance does not play the requested clip",
            details={"assigned": action_in.get("fluidblend_clip_id") if action_in else None},
        )
    require_new(params["output_clip"])
    controls = controls_for(ctx, target)
    pairs = [tuple(pair) for pair in preset["bones"]]
    limbs = [tuple(limb) for limb in preset["limbs"]]
    require_roles(
        controls, [role for _, role in pairs] + [limb[4] for limb in limbs] + preset["fk_switches"] + ["root"]
    )
    missing = [name for name, _ in pairs if name not in source.pose.bones]
    unqualified = [role for _, role in pairs if controls[role].rotation_mode != "QUATERNION"]
    if missing or unqualified:
        raise OpError(
            "RIG_MAPPING_REQUIRED",
            "mapped bones are missing or not quaternion controls",
            details={"missing_source_bones": missing, "non_quaternion_roles": unqualified},
        )
    roles = dict(pairs)
    start, end = params["frame_range"]["start"], params["frame_range"]["end_exclusive"]
    frames = list(range(start, end))
    scene = bpy.context.scene
    tolerance = ctx.quality.get("retarget_limb_error_max_deg", 3.0)
    touched = [controls[role] for _, role in pairs] + [controls["root"]]
    saved_pose = [(bone, bone.matrix_basis.copy()) for bone in touched]
    switches = [controls[role] for role in preset["fk_switches"]]
    saved_switches = [(bone, bone.get("IK_FK")) for bone in switches]
    anim = target.animation_data or target.animation_data_create()
    saved_anim = anim.action, anim.action_slot, [(track, track.mute) for track in anim.nla_tracks]
    current = scene.frame_current
    rotations = {role: [] for _, role in pairs}
    travel = []
    try:
        # Evaluate the target bare and in FK: nothing else may pose the controls being keyed.
        anim.action = None
        for track, _ in saved_anim[2]:
            track.mute = True
        for bone in switches:
            bone["IK_FK"] = 1.0
        count = params.get("test_poses", 3)
        tests = sorted({frames[round(i * (len(frames) - 1) / (count - 1))] for i in range(count)})
        tested = []
        for frame in tests:
            scene.frame_set(frame)
            pose_target(source, target, controls, pairs)
            errors = limb_errors(source, controls, limbs, roles)
            tested.append({"frame": frame, "limb_error_deg": errors})
            if max(errors.values()) > tolerance:
                raise OpError(
                    "VALIDATION_FAILED",
                    "test pose does not transfer within tolerance; the full range was not attempted",
                    details={"frame": frame, "limb_error_deg": errors, "tolerance_deg": tolerance},
                )
        origin = None
        for frame in frames:
            scene.frame_set(frame)
            pose_target(source, target, controls, pairs)
            for _, role in pairs:
                quaternion = controls[role].rotation_quaternion.copy()
                previous = rotations[role][-1][1] if rotations[role] else None
                if previous is not None and previous.dot(quaternion) < 0:
                    quaternion.negate()  # same rotation, no flip through the long way round
                rotations[role].append((frame, quaternion))
            location = source.matrix_world.translation.copy()
            origin = origin if origin is not None else location
            travel.append((frame, source.matrix_world.to_3x3().inverted() @ (location - origin)))
    finally:
        for bone, basis in saved_pose:
            bone.matrix_basis = basis
        for bone, value in saved_switches:
            if value is not None:
                bone["IK_FK"] = value
        anim.action = saved_anim[0]
        if saved_anim[1] is not None:
            anim.action_slot = saved_anim[1]
        for track, mute in saved_anim[2]:
            track.mute = mute
        scene.frame_set(current)
    ratio = _leg(target, controls, preset["target_leg"]) / _leg_source(source, preset["source_leg"])
    action, _slot, bag = slotted.ensure_action(target, f"{target.name}.{params['output_clip']}")
    anim.action = saved_anim[0]
    if saved_anim[1] is not None:
        anim.action_slot = saved_anim[1]
    for role, keys in rotations.items():
        path = controls[role].path_from_id("rotation_quaternion")
        for component in range(4):
            slotted.set_keys(
                slotted.fcurve(bag, path, component),
                [(f, q[component]) for f, q in keys],
                interpolation="LINEAR",
            )
    for bone in switches:
        curve = slotted.fcurve(bag, bone.path_from_id() + '["IK_FK"]')
        slotted.set_keys(curve, [(start, 1), (end - 1, 1)], interpolation="CONSTANT")
    orient = target.matrix_world.to_3x3()
    key_world_offsets(bag, target, controls["root"], [(f, orient @ (d * ratio)) for f, d in travel], "LINEAR")
    swing = 0.0
    with evaluated_alone(target, action):
        worst = {limb[0]: 0.0 for limb in limbs}
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            swing = max(swing, *(math.degrees(delta(source, limb[1]).angle) for limb in limbs))
            for name, value in limb_errors(source, controls, limbs, roles).items():
                worst[name] = max(worst[name], value)
        scene.frame_set(current)
    records = [
        measures.record(
            "retarget_limb_direction",
            effector=limb[0],
            control_point=controls[limb[4]].name,
            space="armature",
            frame_range=params["frame_range"],
            step=1,
            value=worst[limb[0]],
            unit="deg",
            tolerance=tolerance,
        )
        for limb in limbs
    ]
    refuse_failed(records, "retargeted clip does not follow the source within tolerance")
    if swing < 1.0:
        # A source that does not move would pass every direction check with a perfect zero.
        raise OpError(
            "VALIDATION_FAILED",
            "the source clip does not move the mapped limbs over this range; nothing to retarget",
            details={"source_limb_swing_deg": swing},
        )
    root_path = controls["root"].path_from_id("location")
    events = [
        {"name": marker.name.lower().replace("_", "-"), "frame": marker.frame}
        for marker in action_in.pose_markers
        if start <= marker.frame < end
    ]
    manifest = write_manifest(
        action,
        target,
        params["output_clip"],
        start,
        end - 1,
        "retarget",
        preset=f"retarget:{params.get('preset', 'simple_biped_to_rigify')}",
        loop=False,
        root_motion="root_bone",
        root_motion_channels=[[root_path, index] for index in range(3)],
        source_clip=params["source_clip"],
        events=events,
        measurements=records,
        limits=[
            "one preset between two known profiles; any other pair of rigs is refused",
            f"source bones without a target are dropped: {', '.join(preset['unmapped_source_bones'])}",
            "FK rotations only: feet are not re-planted, so foot slide is neither measured nor promised",
            "root travel is scaled by the leg-length ratio; fingers, face and props are not transferred",
            "technical transfer check, not an approval of the motion on the new character",
        ],
    )
    save_version(ctx, request, builder)
    builder.write_report("clip.json", manifest)
    builder.write_report(
        "retarget-report.json",
        {
            "preset": params.get("preset", "simple_biped_to_rigify"),
            "source": {"instance_id": params["source_instance_id"], "clip": params["source_clip"]},
            "target_instance_id": request["target"]["instance_id"],
            "mapping": [list(pair) for pair in pairs],
            "unmapped_source_bones": preset["unmapped_source_bones"],
            "test_poses": tested,
            "leg_length_ratio": ratio,
            "root_travel_m": (travel[-1][1] * ratio).length,
            "measurements": records,
            "source_preserved": True,
            "visual_review": "pending",
        },
    )
    builder.metrics.update(
        {
            "clip_id": params["output_clip"],
            "channels": len(channels(action)),
            "frames": len(frames),
            "limb_error_max_deg": max(worst.values()),
            "source_limb_swing_deg": swing,
            "leg_length_ratio": ratio,
        }
    )


def _leg(rig, controls, roles):
    return (controls[roles[1]].bone.head_local - controls[roles[0]].bone.head_local).length * (
        rig.matrix_world.median_scale
    )


def _leg_source(rig, bones):
    first, second = (rig.data.bones[name] for name in bones)
    return (second.head_local - first.head_local).length * rig.matrix_world.median_scale
