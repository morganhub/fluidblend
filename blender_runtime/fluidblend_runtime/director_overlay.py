"""Viewport overlay of a previewed adjustment: drawn over the scene, stored nowhere in it.

The Director panel never keys the open session. To still show the fix where the artist looks, the
engine's preview report carries the effector path before and after; this module draws both with the
GPU module. No datablock is created, the file is not dirtied, and closing Blender forgets it.
"""

from __future__ import annotations

import bpy

RED, GREEN, WHITE = (1.0, 0.25, 0.2, 1.0), (0.3, 1.0, 0.4, 1.0), (1.0, 1.0, 1.0, 0.9)
_data: dict | None = None
_handle = None


def load(viewport: dict | None, filepath: str) -> None:
    """Show the paths of a preview report; `None` or an incomplete block clears the overlay."""
    global _data
    keys = ("frames", "before", "after")
    if not viewport or any(not viewport.get(k) for k in keys):
        _data = None
        return
    if not len(viewport["frames"]) == len(viewport["before"]) == len(viewport["after"]):
        _data = None
        return
    # Bound to the file it was computed for: another scene must not inherit these lines.
    _data = {**{k: viewport[k] for k in keys}, "window": viewport.get("window"), "filepath": filepath}
    _ensure_handler()


def clear() -> None:
    global _data
    _data = None


def active() -> bool:
    return _data is not None and _data["filepath"] == bpy.data.filepath


def summary() -> dict | None:
    """What is on screen, for the panel text, the status operator and the tests."""
    if not active():
        return None
    gaps = [
        sum((a - b) ** 2 for a, b in zip(before, after, strict=True)) ** 0.5
        for before, after in zip(_data["before"], _data["after"], strict=True)
    ]
    return {
        "frames": len(_data["frames"]),
        "first_frame": _data["frames"][0],
        "last_frame": _data["frames"][-1],
        "max_gap_m": max(gaps),
        "center": _data["after"][len(_data["after"]) // 2],
        "drawing": _handle is not None,
    }


def _anchor_cross(point, arm=0.12):
    x, y, z = point
    return [(x - arm, y, z), (x + arm, y, z), (x, y - arm, z), (x, y + arm, z)]


def _draw() -> None:
    if not active():
        return
    try:
        _draw_paths()
    except Exception as exc:  # noqa: BLE001 - a draw callback that raises floods the console every redraw
        print(f"fluidblend: viewport overlay disabled ({exc})", flush=True)
        clear()


def _draw_paths() -> None:
    import gpu
    from gpu_extras.batch import batch_for_shader

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    # The paths run inside or under the limb: drawn on top, or they would be hidden by the mesh.
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(3.0)
    gpu.state.point_size_set(12.0)

    def batch(kind, points, color):
        shader.uniform_float("color", color)
        batch_for_shader(shader, kind, {"pos": [tuple(p) for p in points]}).draw(shader)

    window = _data.get("window")
    if window and window["start"] in _data["frames"]:
        batch("LINES", _anchor_cross(_data["before"][_data["frames"].index(window["start"])]), WHITE)
    batch("LINE_STRIP", _data["before"], RED)
    batch("LINE_STRIP", _data["after"], GREEN)
    frame = bpy.context.scene.frame_current
    if frame in _data["frames"]:
        index = _data["frames"].index(frame)
        batch("POINTS", [_data["before"][index]], RED)
        batch("POINTS", [_data["after"][index]], GREEN)
    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.blend_set("NONE")
    gpu.state.depth_test_set("LESS_EQUAL")


def _ensure_handler() -> None:
    global _handle
    # No window, no GPU context: batch runs and tests without a display draw nothing.
    if _handle is None and not bpy.app.background:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def unregister() -> None:
    global _handle
    clear()
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
