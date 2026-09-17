"""Tasks, plans and worker information."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from fluidblend.contracts.common import SCHEMA_VERSION, Artifact, ErrorRecord, OperationStatus, StrictModel


class WorkerInfo(StrictModel):
    pid: int
    executable: str
    started_at: str
    task_marker: str = Field(description="Identifier present in the worker command line")


class TaskRecord(StrictModel):
    schema_version: str = SCHEMA_VERSION
    task_id: str
    operation_id: str
    operation: str
    project_id: str
    status: OperationStatus
    fingerprint: str = Field(
        description="Canonical sha256 of (operation, target, parameters, expected_revision)"
    )
    expected_revision: int | None = None
    target: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str
    worker: WorkerInfo | None = None
    checkpoint_id: str | None = None
    new_revision: int | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    result_path: str | None = None
    partial_effects: list[str] = Field(default_factory=list)
    progress: dict[str, Any] = Field(
        default_factory=dict, description="Last cooperative step reported by a live operation"
    )
    mode: str = Field(
        default="batch", description="batch (dedicated Blender process) or live (open session through MCP)"
    )


class Plan(StrictModel):
    schema_version: str = SCHEMA_VERSION
    operation_id: str
    operation: str
    backend: str
    op_class: str
    lot: str
    available: bool
    permission_ok: bool
    estimated_seconds: float = Field(ge=0)
    estimated_new_disk_mib: float = Field(ge=0)
    resources: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_conditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking_errors: list[ErrorRecord] = Field(default_factory=list)
