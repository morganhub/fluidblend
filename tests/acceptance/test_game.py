"""Game target (B07): an exported character really imported into Godot, the prototype really launched."""

import pytest
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request, note

from fluidblend.adapters.tool_paths import find_godot
from fluidblend.core.atomic import read_json
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


@pytest.mark.acceptance("B07", title="Exported character imported into Godot, prototype launched headless")
def test_B07_godot_import_and_smoke(project, monkeypatch):
    if not find_godot(project.local.godot_executable):
        pytest.skip("not_run: Godot missing, the game target stays not_tested")
    runner = TaskRunner(project)
    shot = {"shot_id": "shot010"}
    for operation, operation_id, parameters in (
        ("scene.build", "game-build", {"frames": 96}),
        ("game.export", "game-export", {"output_name": "hero", "instance_ids": ["hero-01"]}),
    ):
        outcome = runner.run(make_request(operation, operation_id, target=shot, parameters=parameters))
        assert outcome.exit_code == 0, outcome.result.model_dump()
    glb = next(a.path for a in outcome.result.artifacts if a.kind == "glb")

    not_a_glb = runner.run(
        make_request(
            "game.import_test", "game-import-bad", target=shot, parameters={"export_path": "project.json"}
        )
    )
    assert not_a_glb.result.errors, "only a published .glb is imported"

    imported = runner.run(
        make_request("game.import_test", "game-import", target=shot, parameters={"export_path": glb})
    )
    assert imported.exit_code == 0, imported.result.model_dump()
    report = read_json(project.root / artifact(imported.result, "game-import.json"))
    assert report["import_file"] == "assets/character.glb.import" and report["imported_scene_bytes"] > 1000
    game_dir = artifact(imported.result, "game-import.json").rsplit("/", 1)[0] + "/game"
    assert (project.root / game_dir / "assets/character.glb.import").is_file()
    assert not (project.root / game_dir / ".godot").exists(), "the engine cache is not a deliverable"

    played = runner.run(
        make_request("game.smoke_test", "game-smoke", target=shot, parameters={"game_dir": game_dir})
    )
    assert played.exit_code == 0, played.result.model_dump()
    smoke = read_json(project.root / artifact(played.result, "game-smoke.json"))
    names = {c["name"] for c in smoke["checks"]}
    assert smoke["passed"] and smoke["exit_code"] == 0 and len(smoke["checks"]) == 13
    assert {
        "walk_state_plays_walk_clip",
        "wall_stops_character",
        "prop_is_held",
        "idle_state_plays_nothing",
    } <= names

    # A prototype that fails must fail the operation: break the game, keep everything else.
    broken = project.root / game_dir / "scripts/player.gd"
    broken.write_text(
        broken.read_text(encoding="utf-8").replace("const SPEED := 1.4", "const SPEED := 0.0"),
        encoding="utf-8",
    )
    failed = runner.run(
        make_request("game.smoke_test", "game-smoke-broken", target=shot, parameters={"game_dir": game_dir})
    )
    assert failed.result.errors[0].code == "VALIDATION_FAILED"
    assert "character_moved" in failed.result.errors[0].details["failed_checks"]

    monkeypatch.setattr("fluidblend.hostops.game.find_godot", lambda *_: None)
    missing = runner.run(
        make_request("game.smoke_test", "game-smoke-nogodot", target=shot, parameters={"game_dir": game_dir})
    )
    assert (
        missing.result.errors[0].code == "MISSING_DEPENDENCY"
        and "not_tested" in missing.result.errors[0].message
    )
    note(
        "B07",
        f"hero GLB imported headless by {smoke['engine']} (.import and imported scene checked, not only the exit "
        f"code), prototype launched: 13 checks in {smoke['wall_time_ms']} ms (idle/walk states, looping walk clip, "
        "wall collision, prop pickup); a broken prototype fails the operation; without Godot: MISSING_DEPENDENCY, "
        "not_tested; headless, no frame-rate claim; GDScript smoke test, GUT not used",
    )
