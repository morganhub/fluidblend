"""fluidblend runtime executed inside Blender (stdlib + bpy only).

Entry point: `main(request_path, result_path)`. The result is written atomically; a deliberate test
crash (`test_hooks.crash_after_output`) leaves the outputs without a `result.json`, which the engine
treats as an `unknown` state to reconcile.
"""

from __future__ import annotations

import json
import os
import traceback

from fluidblend_runtime.envelope import Context, load_envelope
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.result import ResultBuilder, write_json_atomic

RUNTIME_VERSION = "0.2.0"
SUPPORTED_BLENDER_SERIES = (5, 2)
LIVE_ONLY_OPERATIONS = {"scene.checkpoint"}
BATCH_ONLY_OPERATIONS = {
    "animation.create",
    "animation.apply",
    "animation.loop",
    "animation.bake",
    "scene.build",
    "shot.preview",
    "game.export",
    "shot.build",
    "character.inspect",
    "rig.validate",
}

# Blender add-on metadata: the runtime is installed and enabled for live mode (operators in addon.py).
bl_info = {
    "name": "fluidblend runtime",
    "author": "fluidblend",
    "version": (0, 2, 0),
    "blender": (5, 2, 0),
    "location": "no UI - operators bpy.ops.fluidblend.* for the fluidblend engine",
    "description": "Approved fluidblend runtime: typed operations on the open scene (live mode)",
    "category": "System",
}


def register() -> None:
    from fluidblend_runtime import addon

    addon.register()


def unregister() -> None:
    from fluidblend_runtime import addon

    addon.unregister()


def identity() -> dict:
    """Session identity: project, shot, revision and runtime version (live mode, §7.2)."""
    import bpy

    from fluidblend_runtime import blendio, live_state

    scene = bpy.context.scene
    return {
        **live_state.snapshot(),
        "runtime_version": RUNTIME_VERSION,
        "blender_version": bpy.app.version_string,
        "blender_executable": bpy.app.binary_path,
        "blend_path": bpy.data.filepath,
        "is_dirty": bpy.data.is_dirty,
        "background": bpy.app.background,
        **blendio.read_identity(scene),
    }


def _check_blender() -> None:
    import bpy

    if tuple(bpy.app.version[:2]) != SUPPORTED_BLENDER_SERIES:
        raise OpError(
            "UNSUPPORTED_CAPABILITY",
            f"runtime {RUNTIME_VERSION} validated for Blender {SUPPORTED_BLENDER_SERIES[0]}.{SUPPORTED_BLENDER_SERIES[1]}, "
            f"session {bpy.app.version_string}",
            recovery="use the locked Blender, or re-validate the runtime on this version",
        )


def run_envelope(envelope: dict) -> dict:
    from fluidblend_runtime import blendio
    from fluidblend_runtime.dispatch import HANDLERS

    request = envelope["request"]
    ctx = Context.from_envelope(envelope)
    builder = ResultBuilder(request, ctx)
    try:
        _check_blender()
        if ctx.runtime_expected_version and ctx.runtime_expected_version != RUNTIME_VERSION:
            raise OpError(
                "VALIDATION_FAILED",
                f"expected runtime {ctx.runtime_expected_version}, loaded {RUNTIME_VERSION}",
                recovery="reinstall/update the kit; the runtime must be an approved version",
            )
        handler = HANDLERS.get(request["operation"])
        if ctx.live and request["operation"] in BATCH_ONLY_OPERATIONS:
            raise OpError(
                "UNSUPPORTED_CAPABILITY",
                f"{request['operation']} runs in batch mode only (it needs a dedicated Blender process)",
                recovery="run it without --mode live; it works on the published work version",
            )
        if not ctx.live and request["operation"] in LIVE_ONLY_OPERATIONS:
            raise OpError("UNSUPPORTED_CAPABILITY", f"{request['operation']} runtime handler is live-only")
        if handler is None:
            raise OpError(
                "UNSUPPORTED_CAPABILITY", f"operation without a runtime handler: {request['operation']}"
            )
        if ctx.work_blend:
            blendio.open_blend(ctx.work_blend)
        if ctx.live:
            from fluidblend_runtime import live_state

            expected = envelope["context"].get("expected_live_identity")
            current = identity()
            if not live_state.matches(expected) or any(
                current.get(key) != expected.get(key)
                for key in ("blend_path", "project_id", "shot_id", "revision", "is_dirty")
            ):
                raise OpError(
                    "SCENE_CONFLICT", "live identity changed before execution; human edits preserved"
                )
            with live_state.engine_operation():
                handler(ctx, request, builder)
            builder.metrics["live_completion_identity"] = identity()
        else:
            handler(ctx, request, builder)
        if ctx.test_hooks.get("sleep_before_result_s"):
            # Simulates a task that runs too long (time budget / unknown state test).
            import time

            time.sleep(float(ctx.test_hooks["sleep_before_result_s"]))
        if ctx.test_hooks.get("crash_after_output"):
            # Simulates an interruption (acceptance A06): outputs written, no result.json.
            os._exit(3)
        builder.finish()
    except OpError as exc:
        builder.fail(exc.code, str(exc), recovery=exc.recovery, details=exc.details)
    except Exception as exc:  # noqa: BLE001 - the failure must be reported to the engine, not lost
        builder.fail(
            "INTERNAL_ERROR",
            f"{type(exc).__name__}: {exc}",
            details={"traceback": traceback.format_exc()[-4000:]},
        )
    return builder.to_dict()


def main(request_path: str, result_path: str) -> None:
    envelope = load_envelope(request_path)
    result = run_envelope(envelope)
    write_json_atomic(result_path, result)
    print(
        "FLUIDBLEND_RESULT="
        + json.dumps({"operation_id": result["operation_id"], "status": result["status"]})
    )
