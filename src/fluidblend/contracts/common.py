"""Shared types: time, errors, artifacts, operation result."""

from __future__ import annotations

from enum import StrEnum
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    """Common base: no unknown field accepted (free-form parameters are rejected)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Fps(StrictModel):
    """Rational frame rate (24/1, 30000/1001, ...)."""

    numerator: int = Field(ge=1, le=1_000_000)
    denominator: int = Field(default=1, ge=1, le=1_000_000)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def as_float(self) -> float:
        return self.numerator / self.denominator

    def blender_settings(self) -> tuple[int, float]:
        """Equivalent `scene.render.fps` (int) and `fps_base` (float)."""
        return self.numerator, float(self.denominator)


class FrameRange(StrictModel):
    """Canonical half-open interval `[start, end_exclusive)`."""

    start: int = Field(ge=-100000, le=1_000_000)
    end_exclusive: int = Field(ge=-100000, le=1_000_001)

    @model_validator(mode="after")
    def _check_order(self) -> FrameRange:
        if self.end_exclusive <= self.start:
            raise ValueError("end_exclusive must be strictly greater than start")
        return self

    @property
    def count(self) -> int:
        return self.end_exclusive - self.start

    def to_blender_inclusive(self) -> tuple[int, int]:
        """Inclusive bounds expected by `scene.frame_start` / `scene.frame_end`."""
        return self.start, self.end_exclusive - 1

    @classmethod
    def from_blender_inclusive(cls, frame_start: int, frame_end: int) -> FrameRange:
        return cls(start=frame_start, end_exclusive=frame_end + 1)


class ErrorCode(StrEnum):
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    RIG_MAPPING_REQUIRED = "RIG_MAPPING_REQUIRED"
    SCENE_CONFLICT = "SCENE_CONFLICT"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    TIMEOUT_UNKNOWN_STATE = "TIMEOUT_UNKNOWN_STATE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorRecord(StrictModel):
    code: ErrorCode
    message: str
    recovery: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Artifact(StrictModel):
    kind: str = Field(description="blend | frames | video | glb | report | image | json | checkpoint")
    path: str = Field(
        description="Path relative to the project after publication, relative to the task folder before"
    )
    sha256: str | None = None
    bytes: int | None = Field(default=None, ge=0)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ChangedEntity(StrictModel):
    kind: str = Field(description="shot | instance | clip | asset | file | action")
    id: str
    change: Literal["created", "modified", "deleted", "versioned"]


class OperationStatus(StrEnum):
    planned = "planned"
    queued = "queued"
    running = "running"
    validating = "validating"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    unknown = "unknown"
    cancelled = "cancelled"


class OperationResult(StrictModel):
    """Structured response of an operation (§6.5 of the specification)."""

    schema_version: str = SCHEMA_VERSION
    operation_id: str
    operation: str
    task_id: str | None = None
    status: OperationStatus
    changed_entities: list[ChangedEntity] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    checkpoint_id: str | None = None
    new_revision: int | None = None
    next_safe_actions: list[str] = Field(default_factory=list)
