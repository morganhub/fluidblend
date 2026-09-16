"""Checkpoints: copy of a source before any risky operation (`checkpoints/<id>/`)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import new_id, now_iso, sha256_file
from fluidblend.core.paths import relpath_posix


def create_file_checkpoint(root: Path, source: Path, *, label: str, task_id: str | None) -> dict[str, Any]:
    checkpoint_id = new_id("ckpt")
    target_dir = root / "checkpoints" / checkpoint_id
    target_dir.mkdir(parents=True, exist_ok=False)
    copy = target_dir / source.name
    shutil.copy2(source, copy)
    manifest = {
        "schema_version": "1.0",
        "checkpoint_id": checkpoint_id,
        "label": label,
        "task_id": task_id,
        "source": relpath_posix(root, source),
        "copy": relpath_posix(root, copy),
        "sha256": sha256_file(copy),
        "bytes": copy.stat().st_size,
        "created_at": now_iso(),
    }
    if manifest["sha256"] != sha256_file(source):
        raise RuntimeError("checkpoint does not match the source (file modified during the copy)")
    atomic_write_json(target_dir / "checkpoint.json", manifest)
    return manifest


def list_checkpoints(root: Path) -> list[dict[str, Any]]:
    base = root / "checkpoints"
    if not base.exists():
        return []
    result = []
    for manifest in sorted(base.glob("*/checkpoint.json")):
        try:
            result.append(read_json(manifest))
        except (OSError, ValueError):
            continue
    return result
