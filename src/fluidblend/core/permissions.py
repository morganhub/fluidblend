"""Enforcement of the approved scope (`config/permissions.json`, §15)."""

from __future__ import annotations

from fnmatch import fnmatchcase

from fluidblend.contracts.operations import OperationSpec
from fluidblend.contracts.project import Permissions

READ_ONLY_PROFILES = {"inspect"}


def operation_allowed(permissions: Permissions, spec: OperationSpec) -> tuple[bool, str | None]:
    if spec.op_class != "read" and permissions.profile in READ_ONLY_PROFILES:
        return (
            False,
            f"profile '{permissions.profile}': read-only, {spec.name} is a {spec.op_class} operation",
        )
    patterns = permissions.allowed_operations or []
    if "*" in patterns:
        return True, None
    for pattern in patterns:
        if fnmatchcase(spec.name, pattern):
            return True, None
    return False, f"{spec.name} not listed in allowed_operations ({', '.join(patterns) or 'empty'})"
