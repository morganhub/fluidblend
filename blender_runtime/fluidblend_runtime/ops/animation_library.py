"""Bounded Rigify clip authoring, channel-partitioned NLA application and export baking."""

import json
import math
import random

import bpy
from mathutils import Quaternion, Vector

from fluidblend_runtime.anim import slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.production import character, controls_for, save_version


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
    manifest = write_manifest(
        action,
        rig,
        clip_id,
        start,
        end,
        layer,
        preset=preset,
        loop=preset != "turn",
        seed=seed,
        amplitude=amplitude,
        stage=stage,
        limits=["bounded control recipe; no contact or locomotion guarantee"],
    )
    rig.animation_data.action = previous
    if previous_slot is not None:
        rig.animation_data.action_slot = previous_slot
    save_version(ctx, request, builder)
    builder.write_report("clip.json", manifest)
    builder.metrics.update({"clip_id": clip_id, "channels": len(channels(action)), "preset": preset})


def apply(ctx, request, builder):
    rig = character(request)
    params = request["parameters"]
    action = find_clip(params["clip_id"])
    manifest = json.loads(action["fluidblend_manifest"])
    if manifest["rig_profile"] != rig.get("fluidblend_rig_profile") or rig.get("fluidblend_baked"):
        raise OpError("RIG_MAPPING_REQUIRED", "clip and target control rig are incompatible")
    anim = rig.animation_data or rig.animation_data_create()
    occupied = set()
    if anim.action:
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
    track = anim.nla_tracks.new()
    track.name = f"fluidblend.{manifest['layer']}.{params['clip_id']}"
    strip = track.strips.new(params["clip_id"], int(params.get("start_frame", 1)), action)
    strip.action_slot = action.slots[0]
    strip.action_frame_start = manifest["frame_range"]["start"]
    strip.action_frame_end = manifest["frame_range"]["end_exclusive"]
    strip.blend_type = "REPLACE"
    strip.extrapolation = "NOTHING"
    strip.repeat = manifest.get("repetitions", 1)
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
        },
    )
    builder.metrics["clip_id"] = params["clip_id"]


def loop(ctx, request, builder):
    rig = character(request)
    source = find_clip(request["target"].get("clip_id"))
    manifest = json.loads(source["fluidblend_manifest"])
    if manifest["rig_profile"] != rig.get("fluidblend_rig_profile"):
        raise OpError("RIG_MAPPING_REQUIRED", "loop source and target rig profiles differ")
    start, end = (manifest["frame_range"][k] for k in ("start", "end_exclusive"))
    error = max(abs(fc.evaluate(start) - fc.evaluate(end)) for fc in slotted.iter_fcurves(source))
    if error > ctx.quality.get("loop_pose_error_max", 0.001):
        raise OpError("VALIDATION_FAILED", "clip endpoints are discontinuous", details={"loop_error": error})
    output = request["parameters"]["output_clip"]
    require_new(output)
    action = source.copy()
    action.name = f"{rig.name}.{output}"
    for fc in slotted.iter_fcurves(action):
        slotted.add_cycles(fc)
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
