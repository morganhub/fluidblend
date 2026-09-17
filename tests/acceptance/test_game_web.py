"""Web game target (B09): an exported character really loaded, played and rendered by Three.js."""

import pytest
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request, note

from fluidblend.adapters.tool_paths import find_browser
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.project import load_project
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


@pytest.mark.acceptance(
    "B09", title="Exported character loaded by Three.js in a headless browser, played and rendered"
)
def test_B09_web_import_and_smoke(project, monkeypatch):
    if not find_browser(project.local.browser_executable):
        pytest.skip("not_run: no Edge or Chrome, the web game target stays not_tested")
    runner = TaskRunner(project)
    shot = {"shot_id": "shot010"}
    for operation, operation_id, parameters in (
        ("scene.build", "web-build", {"frames": 96}),
        ("game.export", "web-export", {"output_name": "hero", "instance_ids": ["hero-01"]}),
    ):
        outcome = runner.run(make_request(operation, operation_id, target=shot, parameters=parameters))
        assert outcome.exit_code == 0, outcome.result.model_dump()
    glb = next(a.path for a in outcome.result.artifacts if a.kind == "glb")

    imported = runner.run(
        make_request(
            "game.import_test", "web-import", target=shot, parameters={"export_path": glb, "template": "web"}
        )
    )
    assert imported.exit_code == 0, imported.result.model_dump()
    report = read_json(project.root / artifact(imported.result, "game-import.json"))
    assert report["engine"] == "three.js r186" and report["walk_clip"] and report["clips"]
    game_dir = artifact(imported.result, "game-import.json").rsplit("/", 1)[0] + "/game"
    assert (project.root / game_dir / "vendor/three/three.module.js").is_file(), "the page works offline"

    # A project that declares the web as its engine gets the web template without being asked twice.
    manifest = read_json(project.root / "project.json")
    manifest["targets"]["game_engine"] = "web"
    atomic_write_json(project.root / "project.json", manifest)
    declared = TaskRunner(load_project(project.root)).run(
        make_request("game.import_test", "web-import-declared", target=shot, parameters={"export_path": glb})
    )
    assert declared.exit_code == 0, declared.result.model_dump()
    assert declared.result.metrics["template"] == "web"
    assert declared.result.metrics["template_from"] == "project targets.game_engine"

    def smoke(operation_id):
        return runner.run(
            make_request("game.smoke_test", operation_id, target=shot, parameters={"game_dir": game_dir})
        )

    played = smoke("web-smoke")
    assert played.exit_code == 0, played.result.model_dump()
    result = read_json(project.root / artifact(played.result, "game-smoke.json"))
    names = {c["name"] for c in result["checks"]}
    assert result["passed"] and len(result["checks"]) == 14
    assert {"walk_clip_moves_bones", "wall_stops_character", "prop_is_held"} <= names
    moved = next(c["value"] for c in result["checks"] if c["name"] == "walk_clip_moves_bones")
    assert moved > 0.01, "the clip really moves the character, it does not merely 'run'"
    # Rendering is evidence only when the browser gave a GPU context; otherwise the limit is stated.
    if result["webgl"]:
        assert result["rendered_share"] > 0.01
        frame = project.root / artifact(played.result, "web-frame.png")
        assert frame.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and frame.stat().st_size > 5000
    else:
        assert any("no WebGL" in limit for limit in result["limits"])

    # A prototype that fails must fail the operation: break the game, keep everything else.
    player = project.root / game_dir / "src/player.js"
    source = player.read_text(encoding="utf-8")
    player.write_text(source.replace("export let SPEED = 1.6;", "export let SPEED = 0.0;"), encoding="utf-8")
    failed = smoke("web-smoke-broken")
    assert failed.result.errors[0].code == "VALIDATION_FAILED"
    assert "character_moved" in failed.result.errors[0].details["failed_checks"]
    player.write_text(source, encoding="utf-8")

    # The engine the page runs is the one the kit pinned, not whatever sits in the folder.
    engine = project.root / game_dir / "vendor/three/three.module.js"
    engine.write_text(engine.read_text(encoding="utf-8") + "\n// edited\n", encoding="utf-8")
    tampered = smoke("web-smoke-tampered")
    assert "pinned hashes" in tampered.result.errors[0].message

    monkeypatch.setattr("fluidblend.hostops.game_web.find_browser", lambda *_: None)
    missing = smoke("web-smoke-nobrowser")
    assert (
        missing.result.errors[0].code == "MISSING_DEPENDENCY"
        and "not_tested" in missing.result.errors[0].message
    )
    note(
        "B09",
        f"hero GLB loaded by {result['engine']} in a headless browser, offline, on 127.0.0.1: 14 checks in "
        f"{result['wall_time_ms']} ms through keyboard events (idle/walk, bones really moved, wall, pickup); "
        f"webgl={result['webgl']}, character covers {result['rendered_share']} of the frame; a broken prototype "
        "fails the operation, edited engine files are refused, without a browser: MISSING_DEPENDENCY, not_tested; "
        "one rendered frame, no frame-rate claim, artistic review pending",
    )
