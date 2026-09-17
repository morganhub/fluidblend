"""Dispatch table of the runtime operations (business name -> handler)."""

from __future__ import annotations

from fluidblend_runtime.ops import (
    animation_library,
    animation_retime,
    character_inspect,
    game_export,
    rig_validate,
    scene_audit,
    scene_build,
    scene_checkpoint,
    scene_inspect,
    shot_build,
    shot_preview,
)

HANDLERS = {
    "animation.create": animation_library.create,
    "animation.apply": animation_library.apply,
    "animation.loop": animation_library.loop,
    "animation.bake": animation_library.bake,
    "character.inspect": character_inspect.run,
    "rig.validate": rig_validate.run,
    "shot.build": shot_build.run,
    "scene.build": scene_build.run,
    "scene.inspect": scene_inspect.run,
    "scene.audit": scene_audit.run,
    "scene.checkpoint": scene_checkpoint.run,
    "animation.retime": animation_retime.run,
    "shot.preview": shot_preview.run,
    "game.export": game_export.run,
}
