"""Canonical hashing, identifiers and timestamps."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(data: Any) -> str:
    return sha256_bytes(canonical_json(data).encode("utf-8"))


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(3)}"
