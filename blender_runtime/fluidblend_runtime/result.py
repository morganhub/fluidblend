"""Building the structured result (§6.5) and writing it atomically."""

from __future__ import annotations

import hashlib
import json
import os
import secrets


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class ResultBuilder:
    def __init__(self, request: dict, ctx) -> None:
        self.request = request
        self.ctx = ctx
        self.changed_entities: list[dict] = []
        self.artifacts: list[dict] = []
        self.warnings: list[str] = []
        self.errors: list[dict] = []
        self.metrics: dict = {}
        self.next_safe_actions: list[str] = []
        self.status = "running"

    def _rel(self, path: str) -> str:
        return os.path.relpath(path, self.ctx.out_dir).replace("\\", "/")

    def add_file(self, kind: str, path: str, **metrics) -> dict:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"artifact declared but missing: {path}")
        artifact = {
            "kind": kind,
            "path": self._rel(path),
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
            "metrics": metrics,
        }
        self.artifacts.append(artifact)
        return artifact

    def add_dir(self, kind: str, path: str, **metrics) -> dict:
        if not os.path.isdir(path):
            raise FileNotFoundError(f"artifact folder missing: {path}")
        files = sorted(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))
        artifact = {
            "kind": kind,
            "path": self._rel(path),
            "sha256": None,
            "bytes": sum(os.path.getsize(os.path.join(path, f)) for f in files),
            "metrics": {"file_count": len(files), **metrics},
        }
        self.artifacts.append(artifact)
        return artifact

    def write_report(self, name: str, data: dict, kind: str = "report") -> dict:
        path = self.ctx.out(name)
        write_json_atomic(path, data)
        return self.add_file(kind, path)

    def changed(self, kind: str, entity_id: str, change: str) -> None:
        self.changed_entities.append({"kind": kind, "id": entity_id, "change": change})

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def fail(
        self, code: str, message: str, *, recovery: str | None = None, details: dict | None = None
    ) -> None:
        self.errors.append({"code": code, "message": message, "recovery": recovery, "details": details or {}})
        self.status = "failed"

    def finish(self) -> None:
        self.status = "failed" if self.errors else "succeeded"

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "operation_id": self.request["operation_id"],
            "operation": self.request["operation"],
            "task_id": self.ctx.task_id,
            "status": self.status,
            "changed_entities": self.changed_entities,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "errors": self.errors,
            "metrics": self.metrics,
            "checkpoint_id": None,
            "new_revision": None,
            "next_safe_actions": self.next_safe_actions,
        }
