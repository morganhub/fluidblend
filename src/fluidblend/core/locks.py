"""Cross-process locks (a single writer per project, per Blender instance, per output)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso


class LockBusy(RuntimeError):
    def __init__(self, name: str, owner: dict[str, Any] | None):
        detail = f" (owner: {owner})" if owner else ""
        super().__init__(f"lock held: {name}{detail}")
        self.name = name
        self.owner = owner


class ProjectLocks:
    def __init__(self, root: Path):
        self.dir = root / "state" / "locks"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _owner_path(self, name: str) -> Path:
        return self.dir / f"{name}.owner.json"

    def owner(self, name: str) -> dict[str, Any] | None:
        path = self._owner_path(name)
        if not path.exists():
            return None
        try:
            return read_json(path)
        except (OSError, ValueError):
            return None

    @contextmanager
    def hold(self, name: str, *, timeout: float = 5.0, purpose: str = "") -> Iterator[None]:
        lock = FileLock(str(self.dir / f"{name}.lock"))
        try:
            lock.acquire(timeout=timeout)
        except Timeout as exc:
            raise LockBusy(name, self.owner(name)) from exc
        try:
            atomic_write_json(
                self._owner_path(name), {"pid": os.getpid(), "since": now_iso(), "purpose": purpose}
            )
            yield
        finally:
            try:
                self._owner_path(name).unlink(missing_ok=True)
            finally:
                lock.release()
