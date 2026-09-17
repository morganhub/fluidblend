"""Shared contact and loop measurements (§16.1).

A figure is never reported bare: every record states its space, support window, sampling step,
control point and tolerance. The arithmetic is pure Python so it is unit-tested without Blender;
only `sample` and the helpers built on it touch `bpy`.
"""

from __future__ import annotations

import math

# Body points compared across the loop seam, as semantic roles of the rig profile.
LOOP_POINT_ROLES = (
    "left_foot_deform",
    "right_foot_deform",
    "left_hand_deform",
    "right_hand_deform",
    "head",
    "pelvis",
)


def window_frames(frame_range: dict, step: int = 1) -> list[int]:
    return list(range(int(frame_range["start"]), int(frame_range["end_exclusive"]), max(1, int(step))))


def distance(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def max_drift(points) -> float:
    """Largest 3D distance from the first sample of a support window (slide)."""
    return max((distance(points[0], p) for p in points), default=0.0)


def max_anchor_error(points, anchor) -> float:
    return max((distance(p, anchor) for p in points), default=0.0)


def pose_error(first, last) -> float:
    return max((distance(a, b) for a, b in zip(first, last, strict=True)), default=0.0)


def velocity_error(start_pair, end_pair) -> float:
    """Seam velocity mismatch in m/frame: forward difference at the start against the backward
    difference at the end, per control point."""
    (s0, s1), (e0, e1) = start_pair, end_pair
    worst = 0.0
    for a0, a1, b0, b1 in zip(s0, s1, e0, e1, strict=True):
        start_v = [y - x for x, y in zip(a0, a1, strict=True)]
        end_v = [y - x for x, y in zip(b0, b1, strict=True)]
        worst = max(worst, distance(start_v, end_v))
    return worst


def record(kind, *, effector, control_point, space, frame_range, step, value, unit, tolerance=None) -> dict:
    if not math.isfinite(value):
        raise ValueError(f"{kind} measurement is not finite")
    return {
        "kind": kind,
        "effector": effector,
        "control_point": control_point,
        "space": space,
        "frame_range": {
            "start": int(frame_range["start"]),
            "end_exclusive": int(frame_range["end_exclusive"]),
        },
        "sampling_step": int(step),
        "value": value,
        "unit": unit,
        "tolerance": tolerance,
        # An ungated figure is informative only; it must never read as a pass.
        "passed": None if tolerance is None else value <= tolerance,
    }


def failures(records) -> list[dict]:
    return [r for r in records if r["passed"] is False]


# --- Blender sampling ---------------------------------------------------------------------------


def bone_point(rig, control_point):
    """World position of a control point: `bone` is its head, `bone@0.5` halfway to its tail."""
    name, _, fraction = control_point.partition("@")
    bone = rig.pose.bones[name]
    local = bone.head + (bone.tail - bone.head) * float(fraction) if fraction else bone.head
    return rig.matrix_world @ local


def sample(rig, bone_names, frames, *, support=None, relative_to=None):
    """Evaluated control points per frame: {control_point: [(x, y, z), ...]}.

    `support` expresses the points in that object's local space (a moving prop or platform);
    `relative_to` subtracts the head of that pose bone (root motion removed). Default: world.
    """
    import bpy

    scene = bpy.context.scene
    current = scene.frame_current
    out = {name: [] for name in bone_names}
    try:
        for frame in frames:
            scene.frame_set(int(frame))
            bpy.context.view_layer.update()
            origin = rig.matrix_world @ rig.pose.bones[relative_to].head if relative_to else None
            inverse = support.matrix_world.inverted() if support is not None else None
            for name in bone_names:
                point = bone_point(rig, name)
                if origin is not None:
                    point = point - origin
                if inverse is not None:
                    point = inverse @ point
                out[name].append(tuple(point))
    finally:
        scene.frame_set(current)
    return out


def contact_records(rig, contacts, *, quality, offset=0, supports=None, step=1) -> list[dict]:
    """Slide of each declared contact window, shifted by `offset` frames (strip placement, repetition).

    `quality` is the project's thresholds: feet use `foot_slide_max_m`, other effectors
    `contact_error_max_m`.
    """
    records = []
    for contact in contacts:
        window = {
            "start": contact["frame_range"]["start"] + offset,
            "end_exclusive": contact["frame_range"]["end_exclusive"] + offset,
        }
        support_id = contact.get("support_instance_id")
        support = (supports or {}).get(support_id) if support_id else None
        if support_id and support is None:
            raise ValueError(f"contact support is not in the scene: {support_id}")
        bone = contact["control_point"]
        points = sample(rig, [bone], window_frames(window, step), support=support)[bone]
        is_foot = contact["effector"].endswith("_foot")
        tolerance = quality.get("foot_slide_max_m" if is_foot else "contact_error_max_m", 0.02)
        common = {
            "effector": contact["effector"],
            "control_point": bone,
            "space": f"support:{support_id}" if support_id else "world",
            "frame_range": window,
            "step": step,
            "unit": "m",
            "tolerance": tolerance,
        }
        records.append(
            record(
                "foot_slide" if is_foot else "contact_slide",
                value=max_drift(points),
                **common,
            )
        )
        if support is not None:
            # A world anchor moves with the character; only a support-space anchor is a fixed target.
            records.append(
                record("contact_error", value=max_anchor_error(points, contact["anchor"]), **common)
            )
    return records


def object_jump_records(obj, frames, *, effector, position_tolerance, rotation_tolerance) -> list[dict]:
    """Largest frame-to-frame world displacement and rotation of `obj` across consecutive `frames`."""
    import bpy

    scene = bpy.context.scene
    current = scene.frame_current
    poses = []
    try:
        for frame in frames:
            scene.frame_set(int(frame))
            bpy.context.view_layer.update()
            location, rotation, _scale = obj.matrix_world.decompose()
            poses.append((tuple(location), rotation.copy()))
    finally:
        scene.frame_set(current)
    pairs = list(zip(poses, poses[1:], strict=False))
    common = {
        "effector": effector,
        "control_point": "object origin",
        "space": "world",
        "frame_range": {"start": frames[0], "end_exclusive": frames[-1] + 1},
        "step": 1,
    }
    return [
        record(
            "handoff_jump",
            value=max((distance(a[0], b[0]) for a, b in pairs), default=0.0),
            unit="m",
            tolerance=position_tolerance,
            **common,
        ),
        record(
            "handoff_rotation_jump",
            value=max((a[1].rotation_difference(b[1]).angle for a, b in pairs), default=0.0),
            unit="rad",
            tolerance=rotation_tolerance,
            **common,
        ),
    ]


def loop_records(rig, bones, root_bone, start, end, *, pose_tolerance) -> list[dict]:
    """Pose and seam velocity across [start, end], root motion removed. Velocity is not gated."""
    names = list(bones)
    frames = [start, start + 1, end - 1, end]
    sampled = sample(rig, names, frames, relative_to=root_bone)
    at = [[sampled[name][i] for name in names] for i in range(4)]
    interval = {"start": start, "end_exclusive": end + 1}
    common = {
        "effector": "body",
        "control_point": ",".join(names),
        "space": f"relative_to:{root_bone}",
        "frame_range": interval,
        "step": 1,
    }
    return [
        record("loop_pose", value=pose_error(at[0], at[3]), unit="m", tolerance=pose_tolerance, **common),
        record(
            "loop_velocity", value=velocity_error((at[0], at[1]), (at[2], at[3])), unit="m/frame", **common
        ),
    ]
