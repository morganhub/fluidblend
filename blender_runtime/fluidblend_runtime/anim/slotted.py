"""The only access point to F-curves: `Action -> layers -> strips -> channelbag(slot) -> fcurves`.

`Action.fcurves` / `Action.groups` / `Action.id_root` no longer exist in Blender 5.0+; a guard test
forbids their use anywhere else in the repository.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import bpy

POSE_PREFIX = "pose.bones["


def _slot_for(action, obj):
    identifier = f"OB{obj.name}"
    for slot in action.slots:
        if slot.identifier == identifier:
            return slot
    return action.slots.new(id_type="OBJECT", name=obj.name)


def _keyframe_strip(action):
    layer = action.layers[0] if len(action.layers) else action.layers.new("Layer")
    for strip in layer.strips:
        if strip.type == "KEYFRAME":
            return strip
    return layer.strips.new(type="KEYFRAME")


def ensure_action(obj, name: str):
    """Assign (or create) the Action `name` on `obj` and return (action, slot, channelbag)."""
    anim = obj.animation_data or obj.animation_data_create()
    action = bpy.data.actions.get(name) or bpy.data.actions.new(name)
    slot = _slot_for(action, obj)
    strip = _keyframe_strip(action)
    channelbag = strip.channelbag(slot, ensure=True)
    anim.action = action
    anim.action_slot = slot
    return action, slot, channelbag


def iter_channelbags(action) -> Iterator[tuple[object, object]]:
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            for channelbag in strip.channelbags:
                yield channelbag.slot, channelbag


def channelbag_for(action, slot):
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type == "KEYFRAME":
                bag = strip.channelbag(slot)
                if bag is not None:
                    return bag
    return None


def iter_fcurves(action) -> Iterator[object]:
    for _slot, channelbag in iter_channelbags(action):
        yield from channelbag.fcurves


def fcurve(channelbag, data_path: str, index: int = 0):
    existing = channelbag.fcurves.find(data_path, index=index)
    return existing or channelbag.fcurves.new(data_path, index=index)


def set_keys(fc, keys: list[tuple], *, interpolation: str = "BEZIER") -> None:
    """Keys are `(frame, value)` or `(frame, value, interpolation)` for the segment that follows."""
    for frame, value, *own in keys:
        point = fc.keyframe_points.insert(frame, value, options={"FAST"})
        point.interpolation = own[0] if own else interpolation
    fc.update()


def add_cycles(fc, *, offset: bool = False) -> None:
    """`offset` accumulates the end value each cycle: root motion advances instead of snapping back."""
    if not any(m.type == "CYCLES" for m in fc.modifiers):
        modifier = fc.modifiers.new(type="CYCLES")
        modifier.mode_before = "REPEAT_OFFSET" if offset else "REPEAT"
        modifier.mode_after = "REPEAT_OFFSET" if offset else "REPEAT"


def is_pose_channel(fc) -> bool:
    return fc.data_path.startswith(POSE_PREFIX)


def key_extent(action, predicate: Callable[[object], bool] | None = None) -> tuple[float, float] | None:
    lo, hi = None, None
    for fc in iter_fcurves(action):
        if predicate is not None and not predicate(fc):
            continue
        for point in fc.keyframe_points:
            x = point.co.x
            lo = x if lo is None or x < lo else lo
            hi = x if hi is None or x > hi else hi
    if lo is None:
        return None
    return lo, hi


def scale_time(action, factor: float, origin: float) -> dict:
    """Scale the key times (plus handles, modifier ranges, markers) around `origin`."""
    moved_keys = 0
    for fc in iter_fcurves(action):
        for point in fc.keyframe_points:
            point.co.x = origin + (point.co.x - origin) * factor
            point.handle_left.x = origin + (point.handle_left.x - origin) * factor
            point.handle_right.x = origin + (point.handle_right.x - origin) * factor
            moved_keys += 1
        for modifier in fc.modifiers:
            if modifier.use_restricted_range:
                modifier.frame_start = origin + (modifier.frame_start - origin) * factor
                modifier.frame_end = origin + (modifier.frame_end - origin) * factor
        fc.update()
    moved_markers = 0
    for marker in action.pose_markers:
        marker.frame = round(origin + (marker.frame - origin) * factor)
        moved_markers += 1
    if action.use_frame_range:
        start, end = action.frame_start, action.frame_end
        action.frame_start = origin + (start - origin) * factor
        action.frame_end = origin + (end - origin) * factor
    return {"keys": moved_keys, "markers": moved_markers}


def describe(action) -> dict:
    slots = []
    for slot, channelbag in iter_channelbags(action):
        slots.append(
            {
                "slot": slot.identifier,
                "fcurves": len(channelbag.fcurves),
                "pose_fcurves": sum(1 for fc in channelbag.fcurves if is_pose_channel(fc)),
                "cyclic_fcurves": sum(
                    1 for fc in channelbag.fcurves if any(m.type == "CYCLES" for m in fc.modifiers)
                ),
            }
        )
    extent = key_extent(action)
    pose_extent = key_extent(action, is_pose_channel)
    return {
        "name": action.name,
        "slots": [s.identifier for s in action.slots],
        "channelbags": slots,
        "key_extent": list(extent) if extent else None,
        "pose_key_extent": list(pose_extent) if pose_extent else None,
        "pose_markers": [{"name": m.name, "frame": m.frame} for m in action.pose_markers],
        "custom": {k: action[k] for k in action.keys() if k.startswith("fluidblend_")},
        "users": action.users,
    }
