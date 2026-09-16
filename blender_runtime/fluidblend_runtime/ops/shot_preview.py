"""shot.preview: preview PNG sequence, idempotent (no existing frame is rewritten)."""

from __future__ import annotations

import bpy

from fluidblend_runtime import render
from fluidblend_runtime.errors import OpError


def run(ctx, request, builder) -> None:
    params = request["parameters"]
    scene = bpy.context.scene
    if scene.camera is None:
        raise OpError("VALIDATION_FAILED", "no active camera: preview impossible")
    frame_start = int(params.get("frame_start") or scene.frame_start)
    end_exclusive = params.get("frame_end_exclusive")
    frame_end = int(end_exclusive) - 1 if end_exclusive is not None else scene.frame_end
    if frame_end < frame_start:
        raise OpError("VALIDATION_FAILED", "empty frame range")
    step = int(params.get("step", 1))
    engine = params.get("engine") or ctx.preview_engine
    width = int(params.get("width") or ctx.preview_width)
    height = int(params.get("height") or ctx.preview_height)
    expected = len(range(frame_start, frame_end + 1, step))
    max_frames = int(ctx.budgets.get("max_preview_frames", expected))
    if expected > max_frames:
        raise OpError("BUDGET_EXCEEDED", f"{expected} frames > max_preview_frames={max_frames}")

    render.configure(
        scene,
        engine=engine,
        width=width,
        height=height,
        fps_numerator=ctx.fps_numerator,
        fps_denominator=ctx.fps_denominator,
    )
    frames_dir = ctx.out("frames", "x")[: -len("x")]
    report = render.render_sequence(
        scene, frames_dir, frame_start=frame_start, frame_end_inclusive=frame_end, step=step
    )
    report.update(
        {
            "engine": engine,
            "width": width,
            "height": height,
            "frame_start": frame_start,
            "frame_end_inclusive": frame_end,
            "frame_end_exclusive": frame_end + 1,
            "step": step,
            "fps": {"numerator": ctx.fps_numerator, "denominator": ctx.fps_denominator},
            "pattern": "frame_%04d.png",
            "camera": scene.camera.name,
        }
    )
    builder.add_dir(
        "frames", frames_dir, expected=report["expected_frames"], produced=report["produced_frames"]
    )
    builder.write_report("render-report.json", report)
    builder.metrics.update(
        {
            "frames_expected": report["expected_frames"],
            "frames_produced": report["produced_frames"],
            "frames_missing": len(report["missing_frames"]),
            "render_seconds": report["seconds"],
            "seconds_per_frame": report["seconds_per_frame"],
            "engine": engine,
        }
    )
    if report["missing_frames"]:
        raise OpError(
            "VALIDATION_FAILED",
            f"{len(report['missing_frames'])} missing frame(s)",
            details={"missing": report["missing_frames"][:50]},
        )
