"""providers.check: state of the providers declared in config/providers.json (none enabled in P0).

A provider is `ready` only if its record is complete (license, source) and the referenced secret
exists in the environment - its value is never read nor journaled.
"""

from __future__ import annotations

import os

from fluidblend.contracts.project import ProvidersConfig
from fluidblend.core.atomic import read_json
from fluidblend.hostops.context import HostContext


def run(ctx: HostContext) -> None:
    path = ctx.project.root / "config" / "providers.json"
    config = ProvidersConfig.model_validate(read_json(path)) if path.exists() else ProvidersConfig()
    rows = []
    for provider in config.providers:
        missing = [field for field in ("license", "kind") if not getattr(provider, field)]
        secret_present = bool(provider.secret_ref) and provider.secret_ref in os.environ
        if not provider.enabled:
            status = "disabled"
        elif missing:
            status = "incomplete"
        elif provider.secret_ref and not secret_present:
            status = "secret_missing"
        else:
            status = "ready"
        rows.append(
            {
                "provider_id": provider.provider_id,
                "kind": provider.kind,
                "enabled": provider.enabled,
                "status": status,
                "missing_fields": missing,
                "secret_ref": provider.secret_ref,
                "secret_present": secret_present if provider.secret_ref else None,
                "license": provider.license,
            }
        )
    report = {
        "providers": rows,
        "enabled_count": sum(1 for r in rows if r["enabled"]),
        "ready_count": sum(1 for r in rows if r["status"] == "ready"),
        "note": "P0: no external provider is integrated; this check makes no network call",
    }
    ctx.write_report("providers-check.json", report)
    ctx.metrics.update(
        {"providers": len(rows), "enabled": report["enabled_count"], "ready": report["ready_count"]}
    )
    if not rows:
        ctx.warnings.append("no provider declared (expected behaviour in P0)")
