"""Operations run on the host side (without Blender): checkpoint, shot validation, film assembly, providers."""

from __future__ import annotations

from fluidblend.hostops import film_assemble, providers_check, scene_checkpoint, shot_validate

HOST_HANDLERS = {
    "scene.checkpoint": scene_checkpoint.run,
    "shot.validate": shot_validate.run,
    "film.assemble": film_assemble.run,
    "providers.check": providers_check.run,
}

__all__ = ["HOST_HANDLERS"]
