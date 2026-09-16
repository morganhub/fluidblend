"""Atomic writes and append-only journal.

On Windows, `os.replace` on the same volume is the best tool available; the JSONL journal
stays the source of truth (append + fsync), the compact state is only a projection.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _fsync_dir(path: Path) -> None:
    # Windows does not allow opening a directory for fsync; skipped cleanly.
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def dumps_pretty(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str) + "\n"


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, dumps_pretty(data))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=False, default=str) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                # A truncated line (write interrupted) is reported, not hidden.
                yield {"event": "journal_corrupt_line", "line_no": line_no, "error": str(exc)}
