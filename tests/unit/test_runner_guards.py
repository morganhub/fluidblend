"""TaskRunner guards without Blender: permissions, budgets, paths, idempotency of refusals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import make_request, note

from fluidblend.contracts.project import Permissions
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.project import load_project
from fluidblend.core.tasks import TaskRunner


def _set_permissions(root: Path, **overrides):
    perms = Permissions(**overrides)
    atomic_write_json(root / "config" / "permissions.json", perms.model_dump(mode="json"))


@pytest.mark.acceptance("A13", title="Exhaust the budget or request an unavailable permission")
def test_A13_permission_and_budget_stop_controlled(project_root: Path):
    _set_permissions(project_root, profile="inspect")
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(make_request("scene.build", "build-001", target={"shot_id": "shot010"}))
    assert outcome.exit_code == exit_codes.BLOCKED
    assert outcome.result.status == "blocked" and outcome.result.errors[0].code == "PERMISSION_REQUIRED"
    assert not (project_root / "shots" / "shot010" / "work").exists()
    assert not list((project_root / "state" / "tasks").glob("*")), (
        "no task must be created before authorization"
    )

    _set_permissions(project_root, profile="assisted")
    project = load_project(project_root)
    project.manifest.budgets.max_preview_frames = 24
    atomic_write_json(project_root / "project.json", project.manifest.model_dump(mode="json"))
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(
        make_request(
            "shot.preview",
            "preview-001",
            target={"shot_id": "shot010"},
            parameters={"frame_start": 1, "frame_end_exclusive": 241},
        )
    )
    assert outcome.exit_code == exit_codes.BUDGET_EXCEEDED
    assert outcome.result.errors[0].code == "BUDGET_EXCEEDED" and "user decision" in (
        outcome.result.errors[0].recovery or ""
    )
    state = json.loads(
        (project_root / "state" / "journal.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert state["event"] == "request_blocked"
    note(
        "A13",
        "inspect profile -> PERMISSION_REQUIRED (exit 2); 240 frames > budget 24 -> BUDGET_EXCEEDED (exit 6); journal request_blocked",
    )


@pytest.mark.acceptance("A12", title="Supply an escaping path or a command as a parameter")
def test_A12_escape_path_and_command_injection_are_refused(project_root: Path, tmp_path: Path):
    runner = TaskRunner(load_project(project_root))
    victim = tmp_path / "outside.wav"
    victim.write_bytes(b"RIFF")
    for candidate in ("..\\outside.wav", str(victim), "\\\\srv\\share\\x.wav", "audio/x.wav; del *"):
        outcome = runner.run(
            make_request(
                "film.assemble",
                f"asm-{abs(hash(candidate))}",
                parameters={"shot_ids": ["shot010"], "output_name": "film", "audio_path": candidate},
            )
        )
        assert outcome.exit_code == exit_codes.BLOCKED, candidate
        assert outcome.result.status == "blocked" and outcome.result.errors[0].code == "PERMISSION_REQUIRED"
    assert victim.read_bytes() == b"RIFF"
    outcome = runner.run(
        make_request(
            "shot.preview",
            "prev-inj",
            target={"shot_id": "shot010"},
            parameters={"engine": "WORKBENCH; rm -rf /"},
        )
    )
    assert outcome.exit_code == exit_codes.INVALID
    assert not any((project_root / "renders").rglob("*.png"))
    note(
        "A12",
        "../ paths, external absolute path and UNC -> PERMISSION_REQUIRED (exit 2); ';' in an enum -> VALIDATION_FAILED (exit 4); no file created",
    )


def test_cli_only_operations_redirect_to_subcommand(project_root: Path):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(make_request("environment.doctor", "doctor-1"))
    assert outcome.exit_code == exit_codes.INVALID
    assert "fluidblend doctor" in (outcome.result.errors[0].recovery or "")
    assert not list((project_root / "state" / "tasks").glob("*"))


def test_providers_check_runs_without_network(project_root: Path):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(make_request("providers.check", "providers-1"))
    assert outcome.exit_code == exit_codes.OK and outcome.result.metrics == {
        "providers": 0,
        "enabled": 0,
        "ready": 0,
    }
    assert (project_root / "reviews" / "project" / "providers-1" / "providers-check.json").exists()


def test_scene_checkpoint_is_blocked_under_inspect_profile(project_root: Path):
    _set_permissions(project_root, profile="inspect")
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(make_request("scene.checkpoint", "ckpt-inspect", target={"shot_id": "shot010"}))
    assert outcome.exit_code == exit_codes.BLOCKED and outcome.result.errors[0].code == "PERMISSION_REQUIRED"


def test_wrong_project_id_is_rejected(project_root: Path):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(
        make_request("scene.inspect", "insp-1", target={"shot_id": "shot010"}, project_id="autre")
    )
    # Refused before any execution: INVALID (4), nothing was launched.
    assert outcome.exit_code == exit_codes.INVALID and outcome.result.errors[0].code == "VALIDATION_FAILED"
    assert not list((project_root / "state" / "tasks").glob("*"))


def test_operation_without_work_version_fails_cleanly(project_root: Path):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(
        make_request("scene.checkpoint", "ckpt-1", target={"shot_id": "shot010"}, parameters={"label": "x"})
    )
    assert outcome.exit_code == exit_codes.INVALID
    assert "scene.build" in (outcome.result.errors[0].recovery or "")


def test_dry_run_creates_plan_without_blender(project_root: Path):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(
        make_request("scene.build", "build-dry", target={"shot_id": "shot010"}, dry_run=True)
    )
    assert outcome.exit_code == exit_codes.OK and outcome.result.status == "planned"
    assert (project_root / "state" / "plans" / "build-dry.json").exists()
    assert not (project_root / "shots" / "shot010" / "work").exists()
