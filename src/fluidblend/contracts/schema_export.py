"""Export of the JSON Schemas (Draft 2020-12) from the pydantic source of truth."""

from __future__ import annotations

import json
from pathlib import Path

from fluidblend.contracts.capabilities import CapabilitiesReport
from fluidblend.contracts.common import OperationResult
from fluidblend.contracts.operations import OPERATIONS, OperationRequest
from fluidblend.contracts.production import AssetManifest, ClipIndex, ClipManifest, RigProfile
from fluidblend.contracts.project import (
    DependencyLock,
    LocalConfig,
    Permissions,
    ProjectManifest,
    ProvidersConfig,
    QualityThresholds,
    RevisionsFile,
    ShotManifest,
)
from fluidblend.contracts.tasks import Plan, TaskRecord

ROOT_SCHEMAS = {
    "asset": AssetManifest,
    "rig-profile": RigProfile,
    "clip": ClipManifest,
    "clip-index": ClipIndex,
    "project": ProjectManifest,
    "local-config": LocalConfig,
    "permissions": Permissions,
    "quality": QualityThresholds,
    "providers": ProvidersConfig,
    "shot": ShotManifest,
    "operation-request": OperationRequest,
    "operation-result": OperationResult,
    "task": TaskRecord,
    "plan": Plan,
    "capabilities": CapabilitiesReport,
    "revisions": RevisionsFile,
    "dependencies-lock": DependencyLock,
}


def dumps_canonical(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for name, model in ROOT_SCHEMAS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://fluidblend.local/schemas/{name}.json"
        schemas[name] = schema
    for op_name, spec in OPERATIONS.items():
        schema = spec.params_model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://fluidblend.local/schemas/operations/{op_name}.json"
        schema["description"] = spec.description
        schema["x-fluidblend"] = {
            "backend": spec.backend,
            "op_class": spec.op_class,
            "lot": spec.lot,
            "available": spec.available,
            "requires_shot": spec.requires_shot,
            **spec.execution_contract(),
        }
        schemas[f"operations/{op_name}"] = schema
    return schemas


def export_all(out_dir: Path) -> list[Path]:
    """Write every schema; return the files written. Deterministic (sorted keys)."""
    written: list[Path] = []
    (out_dir / "operations").mkdir(parents=True, exist_ok=True)
    schemas = build_schemas()
    for name, schema in schemas.items():
        path = out_dir / f"{name}.json"
        path.write_text(dumps_canonical(schema), encoding="utf-8")
        written.append(path)
    index = {"schema_version": "1.0", "schemas": sorted(f"{n}.json" for n in schemas)}
    index_path = out_dir / "index.json"
    index_path.write_text(dumps_canonical(index), encoding="utf-8")
    written.append(index_path)
    return written


def check_up_to_date(out_dir: Path) -> list[str]:
    """Return the schemas that are missing or differ from the pydantic source."""
    stale: list[str] = []
    for name, schema in build_schemas().items():
        path = out_dir / f"{name}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != dumps_canonical(schema):
            stale.append(name)
    return stale
