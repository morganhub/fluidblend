"""Loading, idempotent scaffolding and inspection of a production project."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

import fluidblend
from fluidblend.contracts.project import (
    LocalConfig,
    Permissions,
    ProjectManifest,
    QualityThresholds,
    ShotManifest,
)
from fluidblend.core.atomic import atomic_write_json, atomic_write_text, read_json
from fluidblend.core.hashing import now_iso, sha256_bytes
from fluidblend.core.journal import Journal
from fluidblend.core.paths import normalize_root


class ProjectError(RuntimeError):
    pass


def kit_root() -> Path:
    """Root of the kit repository (holds `pyproject.toml`, `templates/`, `blender_runtime/`)."""
    env = os.environ.get("FLUIDBLEND_HOME")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "blender_runtime").exists():
            return parent
    raise ProjectError("kit root not found; set FLUIDBLEND_HOME")


def templates_dir() -> Path:
    return kit_root() / "templates"


@dataclass
class Project:
    root: Path
    manifest: ProjectManifest
    local: LocalConfig
    permissions: Permissions
    quality: QualityThresholds

    @property
    def project_id(self) -> str:
        return self.manifest.project_id

    def shot_dir(self, shot_id: str) -> Path:
        return self.root / "shots" / shot_id

    def shot_manifest(self, shot_id: str) -> ShotManifest:
        path = self.shot_dir(shot_id) / "shot.json"
        if not path.exists():
            raise ProjectError(f"unknown shot: {shot_id} ({path} missing)")
        return ShotManifest.model_validate(read_json(path))

    def work_versions(self, shot_id: str) -> list[tuple[int, Path]]:
        work = self.shot_dir(shot_id) / "work"
        versions: list[tuple[int, Path]] = []
        if not work.exists():
            return versions
        for entry in work.iterdir():
            match = re.fullmatch(r"v(\d{3,})", entry.name)
            blend = entry / f"{shot_id}.blend"
            if entry.is_dir() and match and blend.exists():
                versions.append((int(match.group(1)), blend))
        return sorted(versions)

    def latest_work_blend(self, shot_id: str) -> tuple[int, Path] | None:
        versions = self.work_versions(shot_id)
        return versions[-1] if versions else None

    def next_version_dir(self, shot_id: str) -> tuple[int, Path]:
        versions = self.work_versions(shot_id)
        number = (versions[-1][0] + 1) if versions else 1
        return number, self.shot_dir(shot_id) / "work" / f"v{number:03d}"

    def journal(self) -> Journal:
        return Journal(self.root / "state" / "journal.jsonl")


def _load_model(path: Path, model: type, *, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise ProjectError(f"missing file: {path}")
    try:
        return model.model_validate(read_json(path))
    except (ValidationError, ValueError) as exc:
        raise ProjectError(f"{path.name} is invalid: {exc}") from exc


def load_project(root: Path) -> Project:
    root = normalize_root(root)
    manifest_path = root / "project.json"
    if not manifest_path.exists():
        raise ProjectError(f"no project.json in {root}")
    manifest = _load_model(manifest_path, ProjectManifest)
    if manifest.schema_version != fluidblend.SCHEMA_VERSION:
        raise ProjectError(
            f"schema_version {manifest.schema_version} is not supported (kit {fluidblend.SCHEMA_VERSION}); explicit migration required"
        )
    local = _load_model(root / "config" / "local.json", LocalConfig, default=LocalConfig())
    permissions = _load_model(root / "config" / "permissions.json", Permissions, default=Permissions())
    quality = _load_model(root / "config" / "quality.json", QualityThresholds, default=QualityThresholds())
    return Project(root=root, manifest=manifest, local=local, permissions=permissions, quality=quality)


# --- Scaffold -----------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def _render(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ProjectError(f"unknown placeholder in a template: {key}")
        return values[key]

    return _PLACEHOLDER.sub(replace, text)


def _structure_for(profile: str) -> dict[str, Any]:
    structure = read_json(templates_dir() / "film" / "folder_structure.json")
    if profile in ("game", "hybrid"):
        structure["directories"] = sorted(set(structure["directories"]) | {"game", "exports/game"})
    return structure


def scaffold_project(
    path: Path,
    *,
    profile: str,
    project_id: str,
    name: str | None = None,
    game_engine: str = "none",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or complete a project, never overwriting a different existing file (A01/A02)."""
    root = Path(os.path.abspath(path))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", project_id):
        raise ProjectError("invalid project_id (lowercase letters, digits, . _ -)")
    structure = _structure_for(profile)
    values = {
        "project_id": project_id,
        "project_name": name or project_id,
        "profile": profile,
        "game_engine": game_engine if profile != "film" else "none",
        "film_target": "false" if profile == "game" else "true",
        "created_at": now_iso(),
        "fluidblend_version": fluidblend.__version__,
        "schema_version": fluidblend.SCHEMA_VERSION,
    }
    report: dict[str, Any] = {
        "root": str(root),
        "dry_run": dry_run,
        "created_dirs": [],
        "created_files": [],
        "identical": [],
        "conflicts": [],
        "first_init": not (root / "project.json").exists(),
    }
    template_root = templates_dir() / "film" / "files"
    planned: list[tuple[Path, str]] = []
    for rel, source in structure["files"].items():
        raw = (template_root / source).read_text(encoding="utf-8")
        planned.append((root / rel, _render(raw, values)))

    for rel in structure["directories"]:
        target = root / rel
        if not target.exists():
            report["created_dirs"].append(rel)
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)

    for target, content in planned:
        rel = target.relative_to(root).as_posix()
        if target.exists():
            existing = target.read_bytes()
            if _same_content(existing, content, target.suffix):
                report["identical"].append(rel)
            else:
                report["conflicts"].append(
                    {
                        "path": rel,
                        "existing_sha256": sha256_bytes(existing),
                        "proposed_sha256": sha256_bytes(content.encode("utf-8")),
                        "action": "kept_existing",
                    }
                )
            continue
        report["created_files"].append(rel)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, content)

    if not dry_run:
        journal = Journal(root / "state" / "journal.jsonl")
        if report["first_init"]:
            journal.append(
                "project_initialized",
                project_id=project_id,
                profile=profile,
                fluidblend_version=fluidblend.__version__,
            )
        else:
            journal.append(
                "project_init_rerun",
                created=len(report["created_files"]),
                identical=len(report["identical"]),
                conflicts=[c["path"] for c in report["conflicts"]],
            )
    return report


def _same_content(existing: bytes, proposed: str, suffix: str) -> bool:
    """Compare while ignoring the volatile fields (`created_at`) of generated JSON."""
    try:
        text = existing.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if suffix == ".json":
        try:
            left, right = json.loads(text), json.loads(proposed)
        except json.JSONDecodeError:
            return text == proposed
        for volatile in ("created_at",):
            if isinstance(left, dict):
                left.pop(volatile, None)
            if isinstance(right, dict):
                right.pop(volatile, None)
        return left == right
    return text.replace("\r\n", "\n") == proposed.replace("\r\n", "\n")


def inspect_project(project: Project) -> dict[str, Any]:
    from fluidblend.core.checkpoints import list_checkpoints
    from fluidblend.core.revisions import RevisionStore
    from fluidblend.core.state import StateStore

    shots = []
    shots_dir = project.root / "shots"
    if shots_dir.exists():
        for entry in sorted(shots_dir.iterdir()):
            if entry.is_dir() and (entry / "shot.json").exists():
                try:
                    manifest = project.shot_manifest(entry.name)
                    frame_range = manifest.frame_range.model_dump()
                    state = manifest.validation_state
                except ProjectError:
                    frame_range, state = None, "invalid"
                versions = project.work_versions(entry.name)
                shots.append(
                    {
                        "shot_id": entry.name,
                        "frame_range": frame_range,
                        "validation_state": state,
                        "work_versions": [f"v{n:03d}" for n, _ in versions],
                        "latest_work": versions[-1][1].relative_to(project.root).as_posix()
                        if versions
                        else None,
                    }
                )
    state = StateStore(project.root).rebuild(save=False)
    return {
        "root": str(project.root),
        "project": project.manifest.model_dump(mode="json"),
        "permissions": project.permissions.model_dump(mode="json"),
        "shots": shots,
        "revisions": RevisionStore(project.root).load().model_dump(mode="json")["revisions"],
        "tasks": {
            tid: {"operation": t["operation"], "status": t["status"]} for tid, t in state["tasks"].items()
        },
        "unfinished_tasks": [
            tid
            for tid, t in state["tasks"].items()
            if t["status"] in ("running", "unknown", "validating", "queued")
        ],
        "checkpoints": len(list_checkpoints(project.root)),
        "journal_events": state["event_count"],
        "journal_corrupt_lines": len(state["corrupt_lines"]),
    }


def write_local_config(root: Path, local: LocalConfig) -> None:
    atomic_write_json(root / "config" / "local.json", local.model_dump(mode="json"))
