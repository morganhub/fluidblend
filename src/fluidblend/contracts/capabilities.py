"""Capabilities discovered through real probes (§3.3)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from fluidblend.contracts.common import SCHEMA_VERSION, StrictModel


class CapabilityStatus(StrEnum):
    available = "available"
    not_installed = "not_installed"
    not_configured = "not_configured"
    unverified = "unverified"
    incompatible = "incompatible"
    blocked = "blocked"


class Capability(StrictModel):
    capability_id: str
    provider: str
    version: str | None = None
    transport: str | None = None
    executable: str | None = None
    tools: list[str] = Field(default_factory=list)
    input_schema_ref: str | None = None
    status: CapabilityStatus
    restrictions: list[str] = Field(default_factory=list)
    verified_at: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    fallback: str | None = None


class CapabilitiesReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    generated_at: str
    host: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(default_factory=list)

    def get(self, capability_id: str) -> Capability | None:
        for cap in self.capabilities:
            if cap.capability_id == capability_id:
                return cap
        return None
