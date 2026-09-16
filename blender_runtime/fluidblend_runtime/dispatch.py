"""Dispatch table of the runtime operations (business name -> handler)."""

from __future__ import annotations

from fluidblend_runtime.ops import (
    animation_retime,
    game_export,
    scene_audit,
    scene_build,
    scene_inspect,
    shot_preview,
)

HANDLERS = {
    "scene.build": scene_build.run,
    "scene.inspect": scene_inspect.run,
    "scene.audit": scene_audit.run,
    "animation.retime": animation_retime.run,
    "shot.preview": shot_preview.run,
    "game.export": game_export.run,
}
