"""A skinned Rigify character all the way into Godot: walk -> bake -> GLB -> import -> prototype."""

import pytest
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request

from fluidblend.adapters.tool_paths import find_browser, find_godot
from fluidblend.contracts.handoff import HandoffBundle
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
            # The baked walk travels, and says so: until 0.6.1 it was declared in place, and
            # fluidunreal measured it carrying the body 0.6 m per loop under that declaration.
            baked = read_json(project.root / "animation/clips/walk-baked/clip.json")
            assert baked["root_motion"] == "root_bone" and baked["source_clip"] == "walk"
            assert baked["stride_m"] == pytest.approx(0.6) and baked.get("repetitions") is None
            assert metrics["root_motion"] == "root_bone"
            # One whole cycle of a looping walk, over its whole strip: until 0.6.2 it said no loop.
            assert baked["loop"] is True and metrics["loop"] is True
    # Baking the baked skeleton again used to succeed and declare the walk in place, not looping,
    # with no IK left to make rigid. fluidunreal's bake template asked for exactly that.
    rebake = runner.run(
        make_request(
            "animation.bake",
            "rg-rebake",
            target=hero,
            parameters={"output_clip": "walk-baked-again", "frame_range": span, "rigid_limbs": True},
        )
    )
    assert rebake.exit_code != 0 and rebake.result.errors[0].code == "UNSUPPORTED_CAPABILITY"
    assert "baked again" in rebake.result.errors[0].message and rebake.result.errors[0].recovery
    export = read_json(project.root / artifact(outcome.result, "export-report.json"))
    assert export["reimport"]["passed"] and export["exported"]["meshes"] == 1
    fidelity = export["reimport"]["skeleton_fidelity"]
    assert fidelity["compared"] > 500 and fidelity["max_error_m"] <= 0.001
    assert export["reimport"]["action_names"] == ["CustomRig_Vitruvian.walk-baked"]
    # A Rigify character exported for Unreal: the bundle must carry the deform skeleton it really
    # exported and a reference pose an engine can measure its import against.
    bundle_path = project.root / artifact(outcome.result, "handoff-bundle.json")
    bundle = HandoffBundle.model_validate(read_json(bundle_path))
    hero = next(i for i in bundle.instances if i.instance_id == "hero-01")
    assert hero.rig_profile and hero.export_def_bones and hero.skinned and hero.baked
    assert hero.bone_count == export["exported"]["armatures"][hero.gltf_node_name]
    assert hero.reference_pose, "no reference pose: an engine could not check the scale it got"
    assert all(len(bone.head_m) == 3 for bone in hero.reference_pose)
    assert bundle.validation.reimport_passed is True
    # What the engine is told the clip does is what the clip does: it travels one stride.
    walk = next(c for c in bundle.clips if c.clip_id == "walk-baked")
    assert walk.root_motion == "root_bone" and walk.stride_m == pytest.approx(0.6) and walk.loop
    # The GLB's range starts at 0; the range a request sent back here must bake is the scene's.
    assert (walk.frame_range.start, walk.frame_range.end_exclusive) == (0, 48)
    assert (walk.source_frame_range.start, walk.source_frame_range.end_exclusive) == (1, 49)
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
    if not find_browser(project.local.browser_executable):
        return
    # Same GLB, second engine: Three.js in a headless browser, which also renders the skin.
    web = runner.run(
        make_request(
            "game.import_test",
            "rg-web-import",
            target=shot,
            parameters={"export_path": glb, "template": "web"},
        )
    )
    assert web.exit_code == 0, web.result.model_dump()
    web_dir = artifact(web.result, "game-import.json").rsplit("/", 1)[0] + "/game"
    web_played = runner.run(
        make_request("game.smoke_test", "rg-web-smoke", target=shot, parameters={"game_dir": web_dir})
    )
    assert web_played.exit_code == 0, web_played.result.model_dump()
    web_smoke = read_json(project.root / artifact(web_played.result, "game-smoke.json"))
    assert web_smoke["passed"] and web_smoke["skinned_meshes"] == 1
    # The baked walk carries its 0.6 m stride on the hips: removed for the loop, and said so.
    assert web_smoke["root_motion_removed_m"] == pytest.approx(0.6, abs=0.01)
    if web_smoke["webgl"]:
        assert web_smoke["rendered_share"] > 0.01
