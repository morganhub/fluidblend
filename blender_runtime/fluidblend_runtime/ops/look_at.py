"""`look_at_target`: a removable COMBINE layer on the head control, measured on the deform bone."""

import math

import bpy
from mathutils import Quaternion, Vector

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import measures, slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.production import controls_for

MAX_PASSES = 4
# Rigify characters face -Y in armature space.
FRONT = Vector((0, -1, 0))

LIMITS = [
    "head only: eyes, neck share and torso are not driven",
    "a target beyond max_angle_deg is refused; turn the body first",
    "technical measurement, not an artistic approval",
]


def head_bones(ctx, rig):
    """(control, deform bone that carries the skull): the control may turn while the skin does not."""
    controls = controls_for(ctx, rig)
    if "head" not in controls:
        raise OpError(
            "RIG_MAPPING_REQUIRED", "rig profile lacks the head role", details={"missing": ["head"]}
        )
    control = controls["head"]
    if control.rotation_mode != "QUATERNION":
        raise OpError("RIG_MAPPING_REQUIRED", "look_at_target needs a quaternion head control")
    origin = control.bone.head_local
    deform = min(
        (b for b in rig.pose.bones if b.bone.use_deform),
        key=lambda b: (b.bone.head_local - origin).length,
        default=None,
    )
    if deform is None:
        raise OpError("RIG_MAPPING_REQUIRED", "no deform bone found under the head control")
    return control, deform


def target_of(rig, params):
    instance_id = params.get("target_instance_id")
    if instance_id is None:
        point = Vector(params["target_point"])
        return lambda: point
    obj = blendio.find_instance_object(instance_id)
    if obj is None:
        raise OpError("VALIDATION_FAILED", f"target instance is not in the scene: {instance_id}")
    if obj == rig:
        raise OpError("VALIDATION_FAILED", "a character cannot look at itself")
    return lambda: obj.matrix_world.translation.copy()


def gaze(rig, deform):
    """(eye point, unit gaze direction) in world space at the current frame."""
    matrix = rig.matrix_world @ deform.matrix
    forward = deform.bone.matrix_local.to_3x3().inverted() @ FRONT
    return matrix @ Vector((0, deform.length / 2, 0)), (matrix.to_3x3() @ forward).normalized()


def sampled(rig, deform, target, frames):
    scene = bpy.context.scene
    current, out = scene.frame_current, []
    try:
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            eye, direction = gaze(rig, deform)
            out.append((direction, (target() - eye).normalized()))
    finally:
        scene.frame_set(current)
    return out


def records(ctx, rig, deform, params, target):
    """Gaze error over the window, and the largest head turn per frame with the ramps included."""
    window = params["frame_range"]
    blend = params.get("blend_frames", 8)
    inside = sampled(rig, deform, target, measures.window_frames(window))
    wide = {"start": window["start"] - blend, "end_exclusive": window["end_exclusive"] + blend}
    around = [direction for direction, _ in sampled(rig, deform, target, measures.window_frames(wide))]
    common = {"effector": "head", "control_point": deform.name, "space": "world", "step": 1, "unit": "deg"}
    return [
        measures.record(
            "gaze_error",
            frame_range=window,
            value=max(math.degrees(d.angle(wanted)) for d, wanted in inside),
            tolerance=ctx.quality.get("gaze_error_max_deg", 2.0),
            **common,
        ),
        measures.record(
            "gaze_step",
            frame_range=wide,
            value=max(math.degrees(a.angle(b)) for a, b in zip(around, around[1:], strict=False)),
            tolerance=params.get("max_step_deg", 12.0),
            **common,
        ),
    ]


def solve(ctx, rig, params, registry):
    """Add the gaze layer in memory and return (before, after, track, action, control point)."""
    control, deform = head_bones(ctx, rig)
    adjustment_id = params["adjustment_id"]
    if adjustment_id in registry:
        raise OpError("SCENE_CONFLICT", "adjustment id already applied in this scene; choose a new one")
    target = target_of(rig, params)
    frames = measures.window_frames(params["frame_range"])
    before = records(ctx, rig, deform, params, target)
    needed, tolerance = before[0]["value"], before[0]["tolerance"]
    if needed <= tolerance:
        raise OpError(
            "VALIDATION_FAILED",
            "the head already looks at the target; nothing to adjust",
            details={"gaze_error_deg": needed, "tolerance_deg": tolerance},
        )
    limit = params.get("max_angle_deg", 60.0)
    if needed > limit:
        raise OpError(
            "VALIDATION_FAILED",
            "target is beyond max_angle_deg of the current gaze; turn the body first",
            details={"needed_deg": needed, "max_angle_deg": limit},
        )
    blend = params.get("blend_frames", 8)
    anim = rig.animation_data or rig.animation_data_create()
    previous, previous_slot = anim.action, anim.action_slot
    action, _slot, bag = slotted.ensure_action(rig, f"{rig.name}.adjust.{adjustment_id}")
    anim.action = previous
    if previous_slot is not None:
        anim.action_slot = previous_slot
    action.use_fake_user = True
    action["fluidblend_adjustment_id"] = adjustment_id
    curves = [slotted.fcurve(bag, control.path_from_id("rotation_quaternion"), i) for i in range(4)]
    total = {frame: Quaternion() for frame in frames}
    scene = bpy.context.scene
    current = scene.frame_current
    track = None
    after = before
    for _ in range(MAX_PASSES):
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            eye, direction = gaze(rig, deform)
            # Shortest arc: no roll is introduced, so the head cannot flip on its way.
            turn = direction.rotation_difference((target() - eye).normalized())
            world = (rig.matrix_world @ control.matrix).to_quaternion()
            # COMBINE multiplies on the right: the world turn goes into the control's own axes.
            total[frame] = (total[frame] @ (world.inverted() @ turn @ world)).normalized()
        scene.frame_set(current)
        keys, last = [(frames[0] - blend, Quaternion())], Quaternion()
        for frame in frames:
            # q and -q are the same rotation; keep the sign continuous or the curves jump.
            value = total[frame] if total[frame].dot(last) >= 0 else -total[frame]
            keys.append((frame, value))
            last = value
        keys.append((frames[-1] + blend, Quaternion()))
        for index, curve in enumerate(curves):
            curve.keyframe_points.clear()
            slotted.set_keys(curve, [(frame, value[index]) for frame, value in keys], interpolation="LINEAR")
        if track is None:
            track = anim.nla_tracks.new()
            track.name = f"fluidblend.adjust.{adjustment_id}"
            strip = track.strips.new(adjustment_id, frames[0] - blend, action)
            strip.action_slot = action.slots[0]
            strip.action_frame_start, strip.action_frame_end = frames[0] - blend, frames[-1] + blend
            # The layer turns whatever drives the head below it; it owns nothing.
            strip.blend_type = "COMBINE"
            strip.extrapolation = "NOTHING"
        bpy.context.view_layer.update()
        after = records(ctx, rig, deform, params, target)
        if after[0]["passed"]:
            break
    return before, after, track, action, deform.name


def restored(ctx, rig, params):
    _control, deform = head_bones(ctx, rig)
    return records(ctx, rig, deform, params, target_of(rig, params))
