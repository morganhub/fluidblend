"""Preview rendering: idempotent image sequence (no overwrite) and sample frames."""

from __future__ import annotations

import os
import time

import bpy

ENGINES = {"WORKBENCH": "BLENDER_WORKBENCH", "EEVEE": "BLENDER_EEVEE"}


def configure(
    scene, *, engine: str, width: int, height: int, fps_numerator: int, fps_denominator: int
) -> None:
    render = scene.render
    render.engine = ENGINES[engine]
    render.resolution_x = width
    render.resolution_y = height
    render.resolution_percentage = 100
    render.fps = fps_numerator
    render.fps_base = float(fps_denominator)
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    render.image_settings.color_depth = "8"
    render.use_file_extension = True
    render.use_overwrite = False
    render.use_placeholder = True
    render.film_transparent = False
    if engine == "WORKBENCH":
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "MATERIAL"
        shading.show_shadows = True
        shading.show_cavity = False


def render_sequence(
    scene, out_dir: str, *, frame_start: int, frame_end_inclusive: int, step: int, prefix: str = "frame_"
) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    scene.frame_start = frame_start
    scene.frame_end = frame_end_inclusive
    scene.frame_step = step
    scene.render.filepath = os.path.join(out_dir, prefix)
    started = time.perf_counter()
    result = bpy.ops.render.render(animation=True)
    elapsed = time.perf_counter() - started
    expected = list(range(frame_start, frame_end_inclusive + 1, step))
    produced = sorted(f for f in os.listdir(out_dir) if f.startswith(prefix) and f.endswith(".png"))
    missing = [f for f in expected if f"{prefix}{f:04d}.png" not in produced]
    return {
        "result": list(result),
        "expected_frames": len(expected),
        "produced_frames": len(produced),
        "missing_frames": missing,
        "seconds": round(elapsed, 3),
        "seconds_per_frame": round(elapsed / max(1, len(expected)), 4),
        "first_file": produced[0] if produced else None,
        "last_file": produced[-1] if produced else None,
    }


def render_samples(scene, out_dir: str, frames: list[int], *, prefix: str = "frame_") -> dict:
    os.makedirs(out_dir, exist_ok=True)
    started = time.perf_counter()
    written = []
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(out_dir, f"{prefix}{frame:04d}")
        bpy.ops.render.render(write_still=True)
        written.append(f"{prefix}{frame:04d}.png")
    return {"frames": frames, "files": written, "seconds": round(time.perf_counter() - started, 3)}


def sample_frames(frame_start: int, frame_end_inclusive: int, count: int) -> list[int]:
    if count <= 0:
        return []
    if count == 1:
        return [frame_start]
    span = frame_end_inclusive - frame_start
    return sorted({frame_start + round(i * span / (count - 1)) for i in range(count)})
