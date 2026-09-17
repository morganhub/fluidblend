"""Web game template: pinned vendor files, import-free page, and the contract switch."""

import json
import re

from fluidblend.contracts.operations import validate_request
from fluidblend.contracts.production import GameImportTestParams
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root
from fluidblend.hostops.game_web import _Handler, is_web_game, vendor_problems

TEMPLATE = kit_root() / "templates/game-web"


def test_vendored_three_matches_its_pinned_hashes_and_licence():
    pinned = json.loads((TEMPLATE / "vendor/VENDOR.json").read_text(encoding="utf-8"))
    assert pinned["package"] == "three" and pinned["version"] == "0.186.0" and pinned["license"] == "MIT"
    for name, expected in pinned["files"].items():
        assert sha256_file(TEMPLATE / "vendor/three" / name) == expected, name
    assert "LICENSE" in pinned["files"] and (kit_root() / "licenses/three.md").is_file()
    assert vendor_problems(TEMPLATE) == [] and is_web_game(TEMPLATE)


def test_the_page_loads_nothing_from_the_network_and_keeps_the_house_style():
    for path in [TEMPLATE / "index.html", *TEMPLATE.glob("src/*.js"), *TEMPLATE.glob("test/*.js")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!127\.0\.0\.1)", text), f"{path.name} reaches for the network"
        if path.suffix == ".js":
            assert not re.search(r"^\s*(const|var)\s", text, re.M), f"{path.name}: `let` only"
            assert "jquery" not in text.lower()


def test_modules_are_served_as_javascript_whatever_the_windows_registry_says():
    assert _Handler.extensions_map[".js"] == "text/javascript"
    assert _Handler.extensions_map[".glb"] == "model/gltf-binary"


def test_game_profile_starts_from_an_empty_work_scene_and_keeps_its_engine(tmp_path):
    from fluidblend.core.project import load_project, scaffold_project

    scaffold_project(tmp_path / "game", profile="game", project_id="gorash", game_engine="web")
    game = load_project(tmp_path / "game")
    shot = game.shot_manifest("shot010")
    assert shot.instances == [] and shot.props == [] and "shot.build" in shot.notes
    assert game.manifest.targets.game_engine == "web"
    scaffold_project(tmp_path / "film", profile="film", project_id="clip")
    assert len(load_project(tmp_path / "film").shot_manifest("shot010").instances) == 2


def test_template_parameter_selects_the_engine_and_follows_the_project_when_omitted():
    assert GameImportTestParams(export_path="exports/a.glb").template is None
    assert GameImportTestParams(export_path="exports/a.glb", template="web").template == "web"
    example = kit_root() / "skills/fluidblend/assets/request-game-import-test-web.json"
    _request, params, spec = validate_request(json.loads(example.read_text(encoding="utf-8")))
    assert params.template == "web" and spec.available
