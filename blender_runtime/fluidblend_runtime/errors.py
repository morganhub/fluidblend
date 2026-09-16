"""Operation error carrying a stable code (§6.5)."""

from __future__ import annotations

KNOWN_CODES = {
    "MISSING_DEPENDENCY",
    "UNSUPPORTED_CAPABILITY",
    "RIG_MAPPING_REQUIRED",
    "SCENE_CONFLICT",
    "PERMISSION_REQUIRED",
    "BUDGET_EXCEEDED",
    "TIMEOUT_UNKNOWN_STATE",
    "VALIDATION_FAILED",
    "INTERNAL_ERROR",
}


class OpError(Exception):
    def __init__(self, code: str, message: str, *, recovery: str | None = None, details: dict | None = None):
        if code not in KNOWN_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(message)
        self.code = code
        self.recovery = recovery
        self.details = details or {}
