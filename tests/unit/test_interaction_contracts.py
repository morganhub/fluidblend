"""Prop assets, hand recipes and hand-off plans: contract rules and stale-plan refusal, without Blender."""

import pytest
from pydantic import ValidationError
from tests.conftest import make_request

from fluidblend.contracts.production import AnimationCreateParams, AssetManifest, InteractionPlanParams
from fluidblend.core.project import load_project
from fluidblend.core.revisions import RevisionStore
from fluidblend.core.tasks import TaskRunner

ASSET = {
    "asset_id": "baton",
    "version": 1,
    "blend_path": "assets/props/baton/v001/prop.blend",
    "sha256": "0" * 64,
    "license": "CC0-1.0",
    "license_path": "licenses/baton.md",
    "objects": ["baton"],
}
PLAN = {
    "interaction_id": "baton-handoff",
    "giver": {"instance_id": "hero-01", "hand": "right"},
    "receiver": {"instance_id": "sidekick-01", "hand": "left"},
    "prop_instance_id": "baton-01",
    "frame_range": {"start": 1, "end_exclusive": 81},
    "handoff_frame": 40,
}


def test_prop_asset_needs_root_and_primary_grip_and_character_stays_compatible():
    prop = AssetManifest(**ASSET, kind="prop", root_object="baton", grips={"primary": [0, 0, 0]})
    assert prop.armature is None
    # Manifests written before props existed carry no `kind`.
    legacy = AssetManifest(
        **{**ASSET, "objects": ["rig", "body"]}, armature="rig", rig_profile="rigify/0.6.10"
    )
    assert legacy.kind == "character"
    for broken in (
        {"kind": "prop", "root_object": "baton"},
        {"kind": "prop", "root_object": "other", "grips": {"primary": [0, 0, 0]}},
        {"kind": "prop", "root_object": "baton", "grips": {"primary": [0, 0]}},
        {"kind": "prop", "root_object": "baton", "grips": {"primary": [0, 0, float("nan")]}},
        {"kind": "character"},
    ):
        with pytest.raises(ValidationError):
            AssetManifest(**ASSET, **broken)


def test_hand_recipes_require_their_own_inputs_only():
    AnimationCreateParams(preset="take_prop", output_clip="take", prop_instance_id="baton-01")
    AnimationCreateParams(preset="give_prop", output_clip="give", target_point=[0, -0.3, 1.2], hand="left")
    for broken in (
        {"preset": "take_prop"},
        {"preset": "give_prop"},
        {"preset": "give_prop", "target_point": [0, 0, float("inf")]},
        {"preset": "walk", "prop_instance_id": "baton-01"},
    ):
        with pytest.raises(ValidationError):
            AnimationCreateParams(output_clip="clip", **broken)


def test_handoff_plan_needs_distinct_instances_and_room_to_reach():
    InteractionPlanParams(**PLAN)
    for broken in (
        {"receiver": {"instance_id": "hero-01", "hand": "left"}},
        {"prop_instance_id": "hero-01"},
        {"handoff_frame": 10},
        {"handoff_frame": 70},
        {"overlap_frames": 1},
        {"meeting_point": [0, 0]},
    ):
        with pytest.raises(ValidationError):
            InteractionPlanParams(**{**PLAN, **broken})


def _fake_version(root, number, content):
    blend = root / f"shots/shot010/work/v{number:03d}/shot010.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(content)
    return RevisionStore(root).record("shot:shot010", blend, origin="kit")


def test_plan_is_bound_to_its_revision_and_a_stale_plan_is_a_conflict(project_root):
    _fake_version(project_root, 1, b"scene one")
    runner = TaskRunner(load_project(project_root))
    target = {"shot_id": "shot010"}
    planned = runner.run(make_request("interaction.plan", "plan-001", target=target, parameters=PLAN))
    assert planned.exit_code == 0, planned.result.model_dump()
    assert any("not checked against the scene" in w for w in planned.result.warnings)
    plan_path = next(a.path for a in planned.result.artifacts if a.path.endswith("interaction-plan.json"))
    _fake_version(project_root, 2, b"scene two")
    runner = TaskRunner(load_project(project_root))
    stale = runner.run(
        make_request("interaction.apply", "apply-001", target=target, parameters={"plan_path": plan_path})
    )
    assert stale.result.errors[0].code == "SCENE_CONFLICT" and stale.exit_code == 3
    assert stale.task is None, "refused at preflight: no task, no checkpoint, no worker"
    tampered = project_root / plan_path
    tampered.write_text(
        tampered.read_text(encoding="utf-8").replace('"handoff_frame": 40', '"handoff_frame": 41')
    )
    edited = runner.run(
        make_request("interaction.apply", "apply-002", target=target, parameters={"plan_path": plan_path})
    )
    assert edited.result.errors[0].code == "SCENE_CONFLICT", (
        "a plan edited after review no longer matches its evidence"
    )
