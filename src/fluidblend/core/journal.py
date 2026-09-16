"""Append-only JSONL journal of the project (`state/journal.jsonl`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.core.atomic import append_jsonl, iter_jsonl
from fluidblend.core.hashing import now_iso

REDACTED_KEYS = {"secret", "token", "password", "api_key", "apikey", "authorization"}


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: ("***" if str(key).lower() in REDACTED_KEYS else _redact(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact(item) for item in data]
    return data


class Journal:
    def __init__(self, path: Path):
        self.path = path

    def append(self, event: str, **data: Any) -> dict[str, Any]:
        record = {"ts": now_iso(), "event": event, **_redact(data)}
        append_jsonl(self.path, record)
        return record

    def events(self) -> list[dict[str, Any]]:
        return list(iter_jsonl(self.path))

    def tail(self, count: int = 20) -> list[dict[str, Any]]:
        return self.events()[-count:]
