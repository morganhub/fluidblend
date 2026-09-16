"""Envelope handed over by the engine: typed request + execution context."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

REQUIRED_TOP = ("schema_version", "task_id", "request", "context")
REQUIRED_REQUEST = ("operation", "operation_id", "project_id", "target", "parameters")
REQUIRED_CONTEXT = ("project_root", "task_dir", "out_dir", "fps", "preview")


def load_envelope(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    missing = [k for k in REQUIRED_TOP if k not in data]
    if missing:
        raise ValueError(f"incomplete envelope: {missing}")
    if data["schema_version"] != "1.0":
        raise ValueError(f"unsupported envelope schema_version: {data['schema_version']}")
    req_missing = [k for k in REQUIRED_REQUEST if k not in data["request"]]
    if req_missing:
        raise ValueError(f"incomplete request: {req_missing}")
    ctx_missing = [k for k in REQUIRED_CONTEXT if k not in data["context"]]
    if ctx_missing:
        raise ValueError(f"incomplete context: {ctx_missing}")
    return data


@dataclass
class Context:
    task_id: str
    project_id: str
    project_root: str
    task_dir: str
    out_dir: str
    fps_numerator: int
    fps_denominator: int
    preview_width: int
    preview_height: int
    preview_engine: str
    work_blend: str | None
    shot: dict | None
    budgets: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    runtime_expected_version: str | None = None
    test_hooks: dict = field(default_factory=dict)

    @classmethod
    def from_envelope(cls, envelope: dict) -> Context:
        ctx = envelope["context"]
        fps = ctx["fps"]
        preview = ctx["preview"]
        os.makedirs(ctx["out_dir"], exist_ok=True)
        return cls(
            task_id=envelope["task_id"],
            project_id=envelope["request"]["project_id"],
            project_root=ctx["project_root"],
            task_dir=ctx["task_dir"],
            out_dir=ctx["out_dir"],
            fps_numerator=int(fps["numerator"]),
            fps_denominator=int(fps.get("denominator", 1)),
            preview_width=int(preview.get("width", 640)),
            preview_height=int(preview.get("height", 360)),
            preview_engine=str(preview.get("engine", "WORKBENCH")),
            work_blend=ctx.get("work_blend"),
            shot=ctx.get("shot"),
            budgets=ctx.get("budgets", {}),
            quality=ctx.get("quality", {}),
            runtime_expected_version=ctx.get("runtime_expected_version"),
            test_hooks=ctx.get("test_hooks", {}) or {},
        )

    @property
    def fps_float(self) -> float:
        return self.fps_numerator / self.fps_denominator

    def out(self, *parts: str) -> str:
        path = os.path.join(self.out_dir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path
