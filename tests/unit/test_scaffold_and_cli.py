from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import make_request

from fluidblend.cli import main
from fluidblend.core import exit_codes
from fluidblend.core.project import load_project, scaffold_project
from fluidblend.core.state import StateStore


@pytest.mark.acceptance("A01", title="Initialize in a Windows path with spaces and accents")
def test_A01_init_in_accented_path(tmp_path: Path):
    root = tmp_path / "Démo Studio é"
    report = scaffold_project(root, profile="film", project_id="demo-studio")
    assert (root / "project.json").exists() and (root / "shots" / "shot010" / "shot.json").exists()
    project = load_project(root)
    assert project.project_id == "demo-studio" and project.manifest.fps.numerator == 24
    outside = [p for p in tmp_path.rglob("*") if root not in p.parents and p != root]
    assert outside == [], f"writes outside the scope: {outside}"
    assert len(report["created_files"]) == 12 and report["conflicts"] == []


@pytest.mark.acceptance("A02", title="Re-run the initialization on the same project")
def test_A02_rerun_init_is_idempotent_and_keeps_manual_edits(tmp_path: Path):
    root = tmp_path / "Démo Studio é"
    scaffold_project(root, profile="film", project_id="demo-studio")
    agents = root / "AGENTS.md"
    agents.write_text("# My own rules\n", encoding="utf-8")
    report = scaffold_project(root, profile="film", project_id="demo-studio")
    assert report["created_files"] == []
    assert len(report["identical"]) == 11
    assert [c["path"] for c in report["conflicts"]] == ["AGENTS.md"]
    assert agents.read_text(encoding="utf-8") == "# My own rules\n"
    dry = scaffold_project(root, profile="film", project_id="demo-studio", dry_run=True)
    assert dry["dry_run"] and [c["path"] for c in dry["conflicts"]] == ["AGENTS.md"]
    events = StateStore(root).rebuild(save=False)
    assert events["initialized_at"] is not None


def test_cli_ops_and_version(capsys, unavailable_operation):
    assert main(["ops", "--json"]) == exit_codes.OK
    rows = json.loads(capsys.readouterr().out)
    assert all(r["available"] for r in rows)
    assert main(["ops", "--all", "--json"]) == exit_codes.OK
    assert any(not r["available"] for r in json.loads(capsys.readouterr().out))
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_cli_init_dry_run_creates_nothing(tmp_path: Path, capsys):
    root = tmp_path / "New Project"
    assert main(["init", "--path", str(root), "--dry-run", "--json"]) == exit_codes.OK
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and not root.exists()


def test_cli_run_rejects_invalid_request(project_root: Path, capsys):
    bad = project_root / "requests" / "bad.json"
    bad.parent.mkdir(exist_ok=True)
    bad.write_text(
        json.dumps(
            make_request(
                "scene.build", "b-1", target={"shot_id": "shot010"}, parameters={"frames": "240; del"}
            )
        ),
        encoding="utf-8",
    )
    code = main(["run", "--project", str(project_root), "--operation", "requests/bad.json", "--json"])
    assert code == exit_codes.INVALID
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["errors"][0]["code"] == "VALIDATION_FAILED"


def test_cli_unavailable_operation_is_blocked_not_faked(project_root: Path, capsys, unavailable_operation):
    req = project_root / "requests" / "retarget.json"
    req.parent.mkdir(exist_ok=True)
    req.write_text(
        json.dumps(
            make_request(
                unavailable_operation,
                "rt-1",
                target={"shot_id": "shot010"},
                parameters={"game_dir": "reviews/shot010/import/game"},
            )
        ),
        encoding="utf-8",
    )
    code = main(["run", "--project", str(project_root), "--operation", "requests/retarget.json", "--json"])
    assert code == exit_codes.BLOCKED
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and result["errors"][0]["code"] == "UNSUPPORTED_CAPABILITY"


def test_cli_client_config_prints_valid_json(capsys):
    assert main(["client-config", "--client", "claude", "--port", "9878"]) == exit_codes.OK
    data = json.loads(capsys.readouterr().out)
    assert data["mcpServers"]["blender"]["args"][-1] == "9878"


def test_cli_init_accepts_the_unreal_engine_target(tmp_path: Path):
    """`unreal` is a declared target like any other: the kit exports for it, fluidunreal tests it."""
    root = tmp_path / "unreal-game"
    assert (
        main(
            [
                "init",
                "--path",
                str(root),
                "--project-id",
                "gorash",
                "--profile",
                "game",
                "--game-engine",
                "unreal",
            ]
        )
        == exit_codes.OK
    )
    assert load_project(root).manifest.targets.game_engine == "unreal"
