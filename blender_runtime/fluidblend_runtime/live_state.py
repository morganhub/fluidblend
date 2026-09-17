"""Process-local edit generation; never persisted into a user's scene or reset by undo."""

import secrets
from contextlib import contextmanager

import bpy
from bpy.app.handlers import persistent

SESSION = secrets.token_hex(16)
generation = 0
last_signal = "enabled"
_engine_depth = 0


def _advance(signal):
    global generation, last_signal
    generation += 1
    last_signal = signal


@persistent
def edited(*_args):
    if not _engine_depth:
        _advance("depsgraph")


@persistent
def undone(*_args):
    _advance("undo")


@persistent
def redone(*_args):
    _advance("redo")


@persistent
def loaded(*_args):
    _advance("load")


def snapshot():
    # Flush deferred property edits before taking or comparing an identity.
    bpy.context.view_layer.update()
    return {"session_id": SESSION, "edit_generation": generation, "last_edit_signal": last_signal}


def matches(expected):
    current = snapshot()
    return bool(expected) and all(
        current.get(key) == expected.get(key) for key in ("session_id", "edit_generation")
    )


@contextmanager
def engine_operation():
    global _engine_depth
    _engine_depth += 1
    try:
        yield
    finally:
        # Account for our own deferred updates while still in the engine scope.
        bpy.context.view_layer.update()
        _engine_depth -= 1


HOOKS = (
    (bpy.app.handlers.depsgraph_update_post, edited),
    (bpy.app.handlers.undo_post, undone),
    (bpy.app.handlers.redo_post, redone),
    (bpy.app.handlers.load_post, loaded),
)


def register():
    for handlers, callback in HOOKS:
        if callback not in handlers:
            handlers.append(callback)


def unregister():
    for handlers, callback in HOOKS:
        if callback in handlers:
            handlers.remove(callback)
