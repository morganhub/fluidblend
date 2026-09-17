"""Bounded Rigify clip authoring, channel-partitioned NLA application and export baking."""

import contextlib
import json
import math
import random

import bpy
from mathutils import Quaternion, Vector

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import measures, slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.production import (
    character,
    controls_for,
    grip_local,
    grip_world,
    prop_object,
    save_version,
)


def channels(action):
    return {(fc.data_path, fc.array_index) for fc in slotted.iter_fcurves(action)}


def find_clip(clip_id):
    found = [a for a in bpy.data.actions if a.get("fluidblend_clip_id") == clip_id]
    if len(found) != 1:
        raise OpError("VALIDATION_FAILED", "clip must identify exactly one library Action")
    return found[0]


def require_new(clip_id):
    if any(a.get("fluidblend_clip_id") == clip_id for a in bpy.data.actions):
        raise OpError("SCENE_CONFLICT", "clip already exists; choose a new variant id")


def write_manifest(action, rig, clip_id, start, end, layer, **extra):
    action["fluidblend_clip_id"] = clip_id
    action["fluidblend_rig_profile"] = rig.get("fluidblend_rig_profile", "")
    action.use_fake_user = True
    manifest = {
        "schema_version": "1.0",
        "clip_id": clip_id,
        "action": action.name,
        "slot": action.slots[0].identifier,
        "rig_profile": rig.get("fluidblend_rig_profile"),
        "frame_range": {"start": start, "end_exclusive": end},
        "root_motion": "in_place",
        "contacts": [],
        "events": [],
        "layer": layer,
        "owned_channels": [[path, index] for path, index in sorted(channels(action))],
        **extra,
    }
    action["fluidblend_manifest"] = json.dumps(manifest)
    return manifest


@contextlib.contextmanager
def evaluated_alone(rig, action):
    """Evaluate `action` on `rig` without the NLA stack, then restore the previous assignment."""
    anim = rig.animation_data or rig.animation_data_create()
    previous, previous_slot = anim.action, anim.action_slot
    muted = [(track, track.mute) for track in anim.nla_tracks]
    try:
        for track, _ in muted:
            track.mute = True
        anim.action = action
        anim.action_slot = action.slots[0]
        yield
    finally:
        anim.action = previous
        if previous_slot is not None:
            anim.action_slot = previous_slot
        for track, state in muted:
            track.mute = state


def require_roles(controls, roles):
    missing = [role for role in roles if role not in controls]
    if missing:
        raise OpError(
            "RIG_MAPPING_REQUIRED",
            "rig profile lacks roles needed by this recipe; run rig.map again",
            details={"missing": missing},
        )


def loop_point_bones(controls):
    return [controls[role].name for role in measures.LOOP_POINT_ROLES if role in controls]


def refuse_failed(records, message):
    failed = measures.failures(records)
    if failed:
        raise OpError("VALIDATION_FAILED", message, details={"measurements": failed})


def key_world_offsets(bag, rig, bone, keys, interpolation):
    """Key `bone.location` from world-space offsets; pose locations live in the bone's rest axes."""
    to_local = (rig.matrix_world.to_3x3() @ bone.bone.matrix_local.to_3x3()).inverted()
    local = [(frame, to_local @ offset, *own) for frame, offset, *own in keys]
    for index in range(3):
        fc = slotted.fcurve(bag, bone.path_from_id("location"), index)
        slotted.set_keys(
            fc, [(frame, value[index], *own) for frame, value, *own in local], interpolation=interpolation
        )


HAND_ROLE_SUFFIXES = ("hand_ik", "arm_switch", "hand_deform", "upper_arm_fk", "forearm_fk")


def hand_point(controls, side):
    """Mid-hand control point: the palm sits halfway along the hand deform bone, not at the wrist."""
    return controls[f"{side}_hand_deform"].name + "@0.5"


def author_hand_reach(rig, controls, bag, side, target, start, hold_start, hold_end, end):
    """Bring the palm to the world point `target`, hold it still, then return to the rest offset.

    The IK control keeps its orientation, so the palm is a constant offset from it: the key is the
    palm displacement. Reach is refused beyond 95 % of the arm, where IK would stretch or fall short.
    """
    require_roles(controls, [f"{side}_{suffix}" for suffix in HAND_ROLE_SUFFIXES])
    if not start < hold_start < hold_end < end:
        raise OpError("VALIDATION_FAILED", "hand reach needs start < hold_start < hold_end < end")
    scene = bpy.context.scene
    control, switch = controls[f"{side}_hand_ik"], controls[f"{side}_arm_switch"]
    current, pose = scene.frame_current, (control.location.copy(), switch.get("IK_FK"))
    try:
        # The rest palm is read where the hold starts, with IK on and no offset, so root motion
        # already applied to the character is part of the reference.
        scene.frame_set(int(hold_start))
        control.location = (0, 0, 0)
        switch["IK_FK"] = 0.0
        bpy.context.view_layer.update()
        palm = measures.bone_point(rig, hand_point(controls, side))
        shoulder = rig.matrix_world @ controls[f"{side}_upper_arm_fk"].head
    finally:
        control.location = pose[0]
        if pose[1] is not None:
            switch["IK_FK"] = pose[1]
        scene.frame_set(current)
    scale = rig.matrix_world.median_scale
    arm = (controls[f"{side}_upper_arm_fk"].length + controls[f"{side}_forearm_fk"].length) * scale
    wrist_target = Vector(target) - (palm - rig.matrix_world @ controls[f"{side}_hand_deform"].head)
    needed = (wrist_target - shoulder).length
    if needed > 0.95 * arm:
        raise OpError(
            "VALIDATION_FAILED",
            "target is beyond the arm's reach; move the character closer first",
            details={"needed_m": needed, "arm_m": arm, "side": side},
        )
    delta = Vector(target) - palm
    zero = Vector((0, 0, 0))
    keys = [(start, zero, "BEZIER"), (hold_start, delta, "LINEAR"), (hold_end, delta, "BEZIER"), (end, zero)]
    key_world_offsets(bag, rig, control, keys, "BEZIER")
    curve = slotted.fcurve(bag, switch.path_from_id() + '["IK_FK"]')
    slotted.set_keys(curve, [(start, 0), (end, 0)], interpolation="CONSTANT")
    return {"reach_m": needed, "arm_m": arm}


def author_prop_recipe(ctx, rig, controls, action, bag, params, start, end, stage):
    """`take_prop` reaches a static prop's primary grip; `give_prop` extends the hand to a world point."""
    if stage == "blocking":
        raise OpError("VALIDATION_FAILED", "hand contacts need continuous interpolation, not blocking")
    if end - start < 16:
        raise OpError("VALIDATION_FAILED", "hand recipes need at least 16 frames")
    side, preset = params.get("hand", "right"), params["preset"]
    hold_start, hold_end = start + (end - start) * 3 // 8, start + (end - start) * 5 // 8
    prop_id = params.get("prop_instance_id")
    support = prop_object(prop_id) if prop_id else None
    target = grip_world(support, "primary") if preset == "take_prop" else Vector(params["target_point"])
    point = hand_point(controls, side)
    window = {"start": hold_start, "end_exclusive": hold_end + 1}
    contacts, records = [], []
    # A library clip is authored and measured in isolation, like walk: same reference for both.
    with evaluated_alone(rig, action):
        reach = author_hand_reach(rig, controls, bag, side, target, start, hold_start, hold_end, end)
        if support is not None:
            contacts.append(
                {
                    "effector": f"{side}_hand",
                    "control_point": point,
                    "support_instance_id": prop_id,
                    "frame_range": window,
                    "anchor": list(grip_local(support, "primary")),
                }
            )
            records = measures.contact_records(
                rig, contacts, quality=ctx.quality, supports={prop_id: support}
            )
        else:
            points = measures.sample(rig, [point], measures.window_frames(window))[point]
            records.append(
                measures.record(
                    "contact_error",
                    effector=f"{side}_hand",
                    control_point=point,
                    space="world",
                    frame_range=window,
                    step=1,
                    value=measures.max_anchor_error(points, tuple(target)),
                    unit="m",
                    tolerance=ctx.quality.get("contact_error_max_m", 0.02),
                )
            )
    refuse_failed(records, f"{preset} does not bring the hand to its target")
    return "hands", {
        "loop": False,
        "contacts": contacts,
        "events": [{"name": "contact", "frame": hold_start}, {"name": "release", "frame": hold_end}],
        "measurements": records,
        "limits": [
            f"{side} palm control point, stationary character and static target; reach {reach['reach_m']:.3f} m "
            f"of a {reach['arm_m']:.3f} m arm",
            "the hand moves, the prop does not: ownership transfer belongs to interaction.apply",
            "no finger pose, no wrist orientation change; technical reach measurement, not an approved gesture",
        ],
    }


WALK_ROLES = (
    "root",
    "torso",
    "left_foot_ik",
    "right_foot_ik",
    "left_leg_switch",
    "right_leg_switch",
    "left_thigh_fk",
    "left_foot_deform",
    "right_foot_deform",
)


def author_walk(ctx, rig, controls, action, bag, start, end, amplitude, stage):
    """One root-motion walk cycle on IK feet. Stance keys cancel the root translation exactly, and
    the result is measured on the deform bones rather than trusted."""
    require_roles(controls, WALK_ROLES)
    period = end - start
    if stage == "blocking":
        raise OpError("VALIDATION_FAILED", "walk contacts need continuous interpolation, not blocking")
    if period < 16 or period % 2:
        raise OpError("VALIDATION_FAILED", "walk needs an even cycle of at least 16 frames")
    if amplitude < 0.05:
        raise OpError("VALIDATION_FAILED", "walk needs amplitude >= 0.05 (stride = 2 x amplitude)")
    stride, lift = 2 * amplitude, 0.25 * amplitude
    world = rig.matrix_world
    hip = world @ controls["left_thigh_fk"].head
    ankle = world @ controls["left_foot_deform"].head
    leg, reach = (hip - ankle).length, stride / 4
    if reach >= 0.9 * leg:
        raise OpError(
            "VALIDATION_FAILED", "stride exceeds the leg reach", details={"leg_m": leg, "stride_m": stride}
        )
    # Lower the pelvis so the planted leg stays inside its IK reach instead of stretching.
    drop = leg - math.sqrt(leg * leg - reach * reach) + 0.02
    forward = (world.to_3x3() @ Vector((0, -1, 0))).normalized()
    up = (world.to_3x3() @ Vector((0, 0, 1))).normalized()

    def at(t):
        return start + period * t

    swing = [
        (u, forward * (-reach + 2 * reach * u) + up * (lift * math.sin(math.pi * u)))
        for u in (0.25, 0.5, 0.75)
    ]
    planted_front, planted_back = forward * reach, forward * -reach
    left = [(at(0), planted_front), (at(0.5), planted_back)]
    left += [(at(0.5 + u / 2), offset) for u, offset in swing] + [(at(1), planted_front)]
    right = [(at(0), planted_back)] + [(at(u / 2), offset) for u, offset in swing]
    right += [(at(0.5), planted_front), (at(1), planted_back)]
    key_world_offsets(bag, rig, controls["left_foot_ik"], left, "LINEAR")
    key_world_offsets(bag, rig, controls["right_foot_ik"], right, "LINEAR")
    root = controls["root"]
    key_world_offsets(bag, rig, root, [(at(0), forward * 0), (at(1), forward * stride)], "LINEAR")
    bob = 0.1 * lift
    torso = [(at(i / 8), up * -(drop + bob * (1 - math.cos(4 * math.pi * i / 8)) / 2)) for i in range(9)]
    key_world_offsets(bag, rig, controls["torso"], torso, "BEZIER")
    for side in ("left", "right"):
        switch = controls[f"{side}_leg_switch"]
        curve = slotted.fcurve(bag, switch.path_from_id() + '["IK_FK"]')
        slotted.set_keys(curve, [(start, 0), (end, 0)], interpolation="CONSTANT")
    mid = start + period // 2
    windows = (
        ("left_foot", "left_foot_deform", start, mid + 1),
        ("right_foot", "right_foot_deform", mid, end + 1),
    )
    with evaluated_alone(rig, action):
        contacts = []
        for effector, role, first, stop in windows:
            bone = controls[role].name
            anchor = world.inverted() @ Vector(measures.sample(rig, [bone], [first])[bone][0])
            contacts.append(
                {
                    "effector": effector,
                    "control_point": bone,
                    "support_instance_id": None,
                    "frame_range": {"start": first, "end_exclusive": stop},
                    "anchor": list(anchor),
                }
            )
        records = measures.contact_records(rig, contacts, quality=ctx.quality)
        records += measures.loop_records(
            rig,
            loop_point_bones(controls),
            root.name,
            start,
            end,
            pose_tolerance=ctx.quality.get("loop_pose_error_max", 0.001),
        )
    refuse_failed(records, "walk recipe failed its own contact or loop measurement")
    root_path = root.path_from_id("location")
    return "locomotion", {
        "loop": True,
        "root_motion": "root_bone",
        "root_motion_channels": [[root_path, index] for index in range(3)],
        "stride_m": stride,
        "contacts": contacts,
        "events": [
            {"name": "contact-left", "frame": start},
            {"name": "contact-right", "frame": mid},
        ],
        "measurements": records,
        "limits": [
            "straight walk on flat static ground; feet measured at the ankle deform bone, world space",
            "linear stance/swing keys: seam velocity is reported, not gated; no heel roll or arm swing",
            "technical contact measurement, not an artistic approval of the gait",
        ],
    }


def create(ctx, request, builder):
    rig = character(request)
    if rig.get("fluidblend_baked"):
        raise OpError("UNSUPPORTED_CAPABILITY", "baked export skeleton cannot author control-rig clips")
    controls = controls_for(ctx, rig)
    params = request["parameters"]
    clip_id, preset = params["output_clip"], params["preset"]
    require_new(clip_id)
    interval = params.get("frame_range", {"start": 1, "end_exclusive": 49})
    start, end = interval["start"], interval["end_exclusive"]
    amplitude = params.get("amplitude", 0.3)
    seed = params.get("seed", 0)
    stage = params.get("stage", "spline")
    phase = random.Random(seed).uniform(-0.15, 0.15)
    previous = rig.animation_data.action if rig.animation_data else None
    previous_slot = rig.animation_data.action_slot if rig.animation_data else None
    action, _slot, bag = slotted.ensure_action(rig, f"{rig.name}.{clip_id}")
    if preset == "walk":
        layer, extra = author_walk(ctx, rig, controls, action, bag, start, end, amplitude, stage)
    elif preset in ("take_prop", "give_prop"):
        layer, extra = author_prop_recipe(ctx, rig, controls, action, bag, params, start, end, stage)
    else:
        layer, extra = author_single_channel(controls, bag, preset, start, end, amplitude, stage, phase)
    manifest = write_manifest(
        action,
        rig,
        clip_id,
        start,
        end,
        layer,
        preset=preset,
        seed=seed,
        amplitude=amplitude,
        stage=stage,
        **extra,
    )
    rig.animation_data.action = previous
    if previous_slot is not None:
        rig.animation_data.action_slot = previous_slot
    save_version(ctx, request, builder)
    builder.write_report("clip.json", manifest)
    builder.metrics.update({"clip_id": clip_id, "channels": len(channels(action)), "preset": preset})
    slides = [m["value"] for m in manifest.get("measurements", []) if m["kind"] == "foot_slide"]
    if slides:
        builder.metrics["foot_slide_max_m"] = max(slides)


def author_single_channel(controls, bag, preset, start, end, amplitude, stage, phase):
    definitions = {
        "idle_neutral": ("torso", "location", 2, 0.02, "body"),
        "turn": ("root", "rotation_euler", 2, 1.0, "global"),
        "look_at": ("head", "rotation_euler", 1, 1.0, "gaze"),
        "reach": ("left_upper_arm_fk", "rotation_euler", 0, 1.0, "upper"),
        "react": ("chest", "rotation_euler", 0, 0.5, "upper"),
    }
    role, prop, axis, multiplier, layer = definitions[preset]
    bone = controls[role]
    values = []
    for i in range(9):
        t = i / 8
        if preset == "turn":
            value = t
        elif preset == "idle_neutral":
            value = math.sin(2 * math.pi * t + phase) - math.sin(phase)
        else:
            value = math.sin(math.pi * t) ** 2
        values.append((start + (end - start) * t, value * amplitude * multiplier))
    interpolation = "CONSTANT" if stage == "blocking" else "BEZIER"
    if prop == "rotation_euler" and bone.rotation_mode == "QUATERNION":
        direction = Vector(tuple(1 if i == axis else 0 for i in range(3)))
        for component in range(4):
            fc = slotted.fcurve(bag, bone.path_from_id("rotation_quaternion"), component)
            slotted.set_keys(
                fc,
                [(frame, Quaternion(direction, value)[component]) for frame, value in values],
                interpolation=interpolation,
            )
    elif prop == "rotation_euler" and bone.rotation_mode == "AXIS_ANGLE":
        raise OpError("RIG_MAPPING_REQUIRED", "axis-angle control recipes are not qualified")
    else:
        fc = slotted.fcurve(bag, bone.path_from_id(prop), axis)
        slotted.set_keys(fc, values, interpolation=interpolation)
    if preset == "reach":
        switch = controls["left_arm_switch"]
        switch_curve = slotted.fcurve(bag, switch.path_from_id() + '["IK_FK"]')
        slotted.set_keys(switch_curve, [(start, 1), (end, 1)], interpolation="CONSTANT")
    return layer, {
        "loop": preset != "turn",
        "limits": ["bounded control recipe; no contact or locomotion guarantee"],
    }


def refuse_overlap(rig, action):
    anim = rig.animation_data or rig.animation_data_create()
    occupied = set()
    if anim.action and anim.action != action:
        occupied.update(channels(anim.action))
    for track in anim.nla_tracks:
        if not track.mute:
            for strip in track.strips:
                if strip.action:
                    occupied.update(channels(strip.action))
    overlap = occupied & channels(action)
    if overlap:
        raise OpError(
            "SCENE_CONFLICT",
            "NLA channels already owned; no implicit priority or double transform",
            details={"overlapping_channels": [list(c) for c in sorted(overlap)]},
        )


def add_strip(rig, action, layer, name, start_frame, frame_range):
    track = rig.animation_data.nla_tracks.new()
    track.name = f"fluidblend.{layer}.{name}"
    strip = track.strips.new(name, int(start_frame), action)
    strip.action_slot = action.slots[0]
    strip.action_frame_start = frame_range["start"]
    strip.action_frame_end = frame_range["end_exclusive"]
    strip.blend_type = "REPLACE"
    strip.extrapolation = "NOTHING"
    return track, strip


def apply(ctx, request, builder):
    rig = character(request)
    params = request["parameters"]
    action = find_clip(params["clip_id"])
    manifest = json.loads(action["fluidblend_manifest"])
    if manifest["rig_profile"] != rig.get("fluidblend_rig_profile") or rig.get("fluidblend_baked"):
        raise OpError("RIG_MAPPING_REQUIRED", "clip and target control rig are incompatible")
    refuse_overlap(rig, action)
    track, strip = add_strip(
        rig,
        action,
        manifest["layer"],
        params["clip_id"],
        params.get("start_frame", 1),
        manifest["frame_range"],
    )
    repetitions = manifest.get("repetitions", 1)
    period = manifest["frame_range"]["end_exclusive"] - manifest["frame_range"]["start"]
    if manifest.get("root_motion", "in_place") == "in_place":
        strip.repeat = repetitions
    else:
        # NLA repeat rewinds action time, which would snap the root back every cycle. Play the
        # extended range once and let the REPEAT_OFFSET F-modifiers accumulate the displacement.
        strip.action_frame_end = manifest["frame_range"]["start"] + period * repetitions
        strip.extrapolation = "HOLD_FORWARD"
    bpy.context.view_layer.update()
    supports = {obj["fluidblend_instance_id"]: obj for obj in blendio.instance_objects()}
    records = []
    try:
        for cycle in range(repetitions):
            records += measures.contact_records(
                rig,
                manifest.get("contacts", []),
                offset=int(strip.frame_start) - manifest["frame_range"]["start"] + cycle * period,
                quality=ctx.quality,
                supports=supports,
            )
    except ValueError as exc:
        raise OpError("VALIDATION_FAILED", str(exc)) from exc
    refuse_failed(records, "applied clip breaks its declared contacts in this scene")
    travel = None
    if manifest.get("stride_m"):
        # Zero slide is only meaningful if the character really advanced.
        root_bone = rig.path_resolve(manifest["root_motion_channels"][0][0].rsplit(".", 1)[0]).name
        ends = measures.sample(rig, [root_bone], [int(strip.frame_start), int(strip.frame_end)])[root_bone]
        travel = measures.distance(*ends)
        expected = manifest["stride_m"] * repetitions
        if abs(travel - expected) > ctx.quality.get("foot_slide_max_m", 0.02):
            raise OpError(
                "VALIDATION_FAILED",
                "root travel differs from the declared stride",
                details={"travel_m": travel, "expected_m": expected},
            )
    save_version(ctx, request, builder)
    builder.write_report(
        "animation-apply.json",
        {
            "clip_id": params["clip_id"],
            "track": track.name,
            "frame_start": strip.frame_start,
            "frame_end": strip.frame_end,
            "owned_channels": manifest["owned_channels"],
            "overlap": False,
            "measurements": records,
            "root_travel_m": travel,
        },
    )
    builder.metrics["clip_id"] = params["clip_id"]
    if travel is not None:
        builder.metrics["root_travel_m"] = travel
    slides = [r["value"] for r in records if r["kind"] in ("foot_slide", "contact_slide")]
    if slides:
        builder.metrics["contact_slide_max_m"] = max(slides)
        builder.metrics["measured_contact_windows"] = len(slides)
    errors = [r["value"] for r in records if r["kind"] == "contact_error"]
    if errors:
        builder.metrics["contact_error_max_m"] = max(errors)


def loop(ctx, request, builder):
    rig = character(request)
    source = find_clip(request["target"].get("clip_id"))
    manifest = json.loads(source["fluidblend_manifest"])
    if manifest["rig_profile"] != rig.get("fluidblend_rig_profile"):
        raise OpError("RIG_MAPPING_REQUIRED", "loop source and target rig profiles differ")
    start, end = (manifest["frame_range"][k] for k in ("start", "end_exclusive"))
    # Root-motion channels advance by design; they repeat with an offset instead of matching ends.
    travelling = {(path, index) for path, index in manifest.get("root_motion_channels", [])}
    error = max(
        (
            abs(fc.evaluate(start) - fc.evaluate(end))
            for fc in slotted.iter_fcurves(source)
            if (fc.data_path, fc.array_index) not in travelling
        ),
        default=0.0,
    )
    tolerance = ctx.quality.get("loop_pose_error_max", 0.001)
    if error > tolerance:
        raise OpError("VALIDATION_FAILED", "clip endpoints are discontinuous", details={"loop_error": error})
    # `animation.loop` takes no profile_path: a rig mapped only through an explicit profile keeps
    # the curve check and says the geometric one was not run.
    try:
        controls = controls_for(ctx, rig)
    except OpError:
        controls = {}
    records = []
    if "root" in controls and loop_point_bones(controls):
        with evaluated_alone(rig, source):
            records = measures.loop_records(
                rig, loop_point_bones(controls), controls["root"].name, start, end, pose_tolerance=tolerance
            )
        refuse_failed(records, "evaluated pose differs across the loop seam")
    else:
        builder.warn("geometric loop measurement not_run: no semantic rig profile available")
    output = request["parameters"]["output_clip"]
    require_new(output)
    action = source.copy()
    action.name = f"{rig.name}.{output}"
    for fc in slotted.iter_fcurves(action):
        slotted.add_cycles(fc, offset=(fc.data_path, fc.array_index) in travelling)
    repetitions = request["parameters"].get("repetitions", 2)
    loop_manifest = write_manifest(
        action,
        rig,
        output,
        start,
        end,
        manifest["layer"],
        **{
            **{
                key: value
                for key, value in manifest.items()
                if key
                not in {
                    "schema_version",
                    "clip_id",
                    "action",
                    "slot",
                    "rig_profile",
                    "frame_range",
                    "layer",
                    "owned_channels",
                }
            },
            "loop": True,
            "repetitions": repetitions,
            "source_clip": manifest["clip_id"],
            "loop_error": error,
            "measurements": [m for m in manifest.get("measurements", []) if not m["kind"].startswith("loop_")]
            + records,
        },
    )
    # Applying the loop is explicit; library authoring does not replace existing strips.
    save_version(ctx, request, builder)
    builder.write_report("clip.json", loop_manifest)
    builder.metrics.update({"loop_error": error, "repetitions": repetitions})


def bake(ctx, request, builder):
    rig = character(request)
    if rig.library or rig.override_library:
        raise OpError("UNSUPPORTED_CAPABILITY", "bake requires a local control-rig copy")
    params = request["parameters"]
    require_new(params["output_clip"])
    interval = params["frame_range"]
    if rig.animation_data is None:
        raise OpError("VALIDATION_FAILED", "no animation to bake")
    if rig.animation_data.action:
        rig.animation_data.action.use_fake_user = True
    from fluidblend_runtime.ops.rig_validate import positions
    from fluidblend_runtime.production import meshes_for

    meshes = meshes_for(rig)
    sample_frames = sorted(
        {
            interval["start"],
            (interval["start"] + interval["end_exclusive"] - 1) // 2,
            interval["end_exclusive"] - 1,
        }
    )
    before = {}
    for frame in sample_frames:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        before[frame] = positions(meshes)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    result = bpy.ops.nla.bake(
        frame_start=interval["start"],
        frame_end=interval["end_exclusive"] - 1,
        step=params.get("step", 1),
        only_selected=False,
        visual_keying=True,
        clear_constraints=True,
        clear_parents=False,
        use_current_action=False,
        bake_types={"POSE", "OBJECT"},
    )
    if "FINISHED" not in result or rig.animation_data.action is None:
        raise OpError("VALIDATION_FAILED", "Blender bake did not produce an Action")
    for track in rig.animation_data.nla_tracks:
        track.mute = True
    # Blender's bake leaves constraints tagged is_override_data in place even
    # on this admitted local append. Explicitly remove them from the export
    # variant so sampled transforms cannot be applied a second time.
    for bone in rig.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
    for constraint in list(rig.constraints):
        rig.constraints.remove(constraint)
    # Driver expressions must not override the sampled B-Bone/custom-property keys
    # once the control constraints have been removed from the export variant.
    for driver in list(rig.animation_data.drivers):
        rig.driver_remove(driver.data_path, driver.array_index)
    error = 0.0
    for frame in sample_frames:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        after = positions(meshes)
        error = max(
            error, max(((a - b).length for a, b in zip(before[frame], after, strict=True)), default=0.0)
        )
    if error > 0.001:
        raise OpError("VALIDATION_FAILED", "bake changed evaluated geometry", details={"max_error_m": error})
    action = rig.animation_data.action
    rig["fluidblend_baked"] = True
    manifest = write_manifest(
        action,
        rig,
        params["output_clip"],
        interval["start"],
        interval["end_exclusive"],
        "baked",
        loop=False,
        limits=["export skeleton variant; control rig constraints removed in this new work version"],
    )
    save_version(ctx, request, builder)
    builder.write_report("clip.json", manifest)
    builder.metrics.update(
        {
            "baked": True,
            "channels": len(channels(action)),
            "max_geometry_error_m": error,
            "sample_frames": sample_frames,
        }
    )
