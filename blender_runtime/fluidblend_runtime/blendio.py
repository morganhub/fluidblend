"""Opening, saving and identity of the .blend files."""

from __future__ import annotations

import os

import bpy

IDENTITY_KEYS = ("fluidblend_project_id", "fluidblend_shot_id", "fluidblend_revision", "fluidblend_runtime")


def new_empty() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def open_blend(path: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    result = bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"open refused: {result}")


def save_as(path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    result = bpy.ops.wm.save_as_mainfile(filepath=path, compress=True, relative_remap=True)
    if "FINISHED" not in result or not os.path.isfile(path):
        raise RuntimeError(f"save failed: {result}")
    return path


def save_copy(path: str) -> str:
    """Snapshot without changing the active file (live mode)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    result = bpy.ops.wm.save_as_mainfile(filepath=path, compress=True, copy=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"copy failed: {result}")
    return path


def set_identity(
    scene, *, project_id: str, shot_id: str | None, revision: int | None, runtime_version: str
) -> None:
    scene["fluidblend_project_id"] = project_id
    scene["fluidblend_shot_id"] = shot_id or ""
    scene["fluidblend_revision"] = int(revision or 0)
    scene["fluidblend_runtime"] = runtime_version


def read_identity(scene) -> dict:
    return {key.removeprefix("fluidblend_"): scene.get(key) for key in IDENTITY_KEYS if key in scene}


def find_instance_object(instance_id: str):
    for obj in bpy.data.objects:
        if obj.get("fluidblend_instance_id") == instance_id:
            return obj
    return None


def instance_objects(kind: str | None = None) -> list:
    found = []
    for obj in bpy.data.objects:
        if obj.get("fluidblend_instance_id") and (kind is None or obj.get("fluidblend_kind") == kind):
            found.append(obj)
    return found


def missing_external_files() -> list[str]:
    """Missing referenced files (images, libraries, caches), through the 5.1+ API when available."""
    missing: list[str] = []
    file_path_map = getattr(bpy.data, "file_path_map", None)
    if callable(file_path_map):
        try:
            for _id, paths in file_path_map(include_libraries=True).items():
                for path in paths:
                    absolute = bpy.path.abspath(path)
                    if path and not os.path.exists(absolute):
                        missing.append(path)
        except TypeError:
            pass
        return sorted(set(missing))
    for image in bpy.data.images:
        if image.filepath and image.source == "FILE" and not os.path.exists(bpy.path.abspath(image.filepath)):
            missing.append(image.filepath)
    for library in bpy.data.libraries:
        if not os.path.exists(bpy.path.abspath(library.filepath)):
            missing.append(library.filepath)
    return sorted(set(missing))
