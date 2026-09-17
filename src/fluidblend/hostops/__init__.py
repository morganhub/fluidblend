"""Operations run on the host side (without Blender): checkpoint, shot validation, film assembly, providers."""

from __future__ import annotations

from fluidblend.hostops import (
    audio,
    film_assemble,
    game,
    interaction_plan,
    providers_check,
    rig_map,
    scene_checkpoint,
    shot_validate,
    tools,
)

HOST_HANDLERS = {
    "audio.prepare": audio.prepare,
    "lipsync.analyze": audio.analyze,
    "interaction.plan": interaction_plan.run,
    "rig.map": rig_map.run,
    "scene.checkpoint": scene_checkpoint.run,
    "shot.validate": shot_validate.run,
    "film.assemble": film_assemble.run,
    "game.import_test": game.import_test,
    "game.smoke_test": game.smoke_test,
    "providers.check": providers_check.run,
    "tool.inspect": tools.inspect,
    "tool.register": tools.register,
}

__all__ = ["HOST_HANDLERS"]
