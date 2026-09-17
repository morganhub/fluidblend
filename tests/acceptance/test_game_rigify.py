"""A skinned Rigify character all the way into Godot: walk -> bake -> GLB -> import -> prototype."""

import pytest
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request

from fluidblend.adapters.tool_paths import find_godot
from fluidblend.core.atomic import read_json
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


def test_rigify_character_walks_in_godot(project):
    if not find_godot(project.local.godot_executable):
        pytest.skip("not_run: Godot missing, the game target stays not_tested")
    manifest = install_character(project)
    runner = TaskRunner(project)
    shot = {"shot_id": "shot010"}
    hero = {**shot, "instance_id": "hero-01"}
    outcome = None
    span = {"start": 1, "end_exclusive": 49}
    for operation, operation_id, target, parameters in (
        ("shot.build", "rg-build", shot, {"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]}),
        ("animation.create", "rg-walk", hero, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "rg-apply", hero, {"clip_id": "walk"}),
    ):
        outcome = runner.run(make_request(operation, operation_id, target=target, parameters=parameters))
        assert outcome.exit_code == 0, (operation, outcome.result.model_dump())
    # Negative control: the IK solver compresses the legs, which TRS keys cannot carry.
    refused = runner.run(
        make_request(
            "animation.bake",
            "rg-bake-soft",
            target=hero,
            parameters={"output_clip": "walk-soft", "frame_range": span},
        )
    )
    assert refused.exit_code != 0
    details = refused.result.errors[0].details
    assert details["max_error_m"] > 0.001 and "rigid_limbs" in details["hint"]
    assert any(name.startswith("DEF-") for name in details["non_uniform_scale_bones"])
    for operation, operation_id, target, parameters in (
        (
            "animation.bake",
            "rg-bake",
            hero,
            {"output_clip": "walk-baked", "frame_range": span, "rigid_limbs": True},
        ),
        (
            "game.export",
            "rg-export",
            shot,
            {"output_name": "hero", "instance_ids": ["hero-01"], "export_def_bones": True},
        ),
    ):
        outcome = runner.run(make_request(operation, operation_id, target=target, parameters=parameters))
        assert outcome.exit_code == 0, (operation, outcome.result.model_dump())
        if operation == "animation.bake":
            metrics = outcome.result.metrics
            rigid = metrics["rigid_limbs"]
            assert metrics["max_geometry_error_m"] <= 0.001 and rigid["ik_tip_drift_m"] <= 0.001
            # The knees really bend instead: a zero delta would mean the option did nothing.
            assert rigid["bones"] and rigid["max_pose_delta_m"] > 0.005
    export = read_json(project.root / artifact(outcome.result, "export-report.json"))
    assert export["reimport"]["passed"] and export["exported"]["meshes"] == 1
    fidelity = export["reimport"]["skeleton_fidelity"]
    assert fidelity["compared"] > 500 and fidelity["max_error_m"] <= 0.001
    assert export["reimport"]["action_names"] == ["CustomRig_Vitruvian.walk-baked"]
    glb = next(a.path for a in outcome.result.artifacts if a.kind == "glb")
    imported = runner.run(
        make_request("game.import_test", "rg-import", target=shot, parameters={"export_path": glb})
    )
    assert imported.exit_code == 0, imported.result.model_dump()
    game_dir = artifact(imported.result, "game-import.json").rsplit("/", 1)[0] + "/game"
    played = runner.run(
        make_request("game.smoke_test", "rg-smoke", target=shot, parameters={"game_dir": game_dir})
    )
    assert played.exit_code == 0, played.result.model_dump()
    smoke = read_json(project.root / artifact(played.result, "game-smoke.json"))
    assert smoke["passed"] and len(smoke["checks"]) == 13
