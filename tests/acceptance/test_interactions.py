import math
import shutil
import subprocess

import pytest
from tests.acceptance.test_characters import install_character
from tests.conftest import make_request, note

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender

BLENDER_FLAGS = ["--background", "--factory-startup", "--offline-mode", "--disable-autoexec"]


@pytest.fixture(scope="session")
def baton_blend(blender_exe, tmp_path_factory):
    output = tmp_path_factory.mktemp("baton") / "prop.blend"
    script = kit_root() / "scripts/generate_prop_fixture.py"
    subprocess.run(
        [blender_exe, *BLENDER_FLAGS, "--python", str(script), "--", str(output)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return output


def install_prop(project, blend):
    folder = project.root / "assets/props/baton/v001"
    folder.mkdir(parents=True)
    shutil.copy2(blend, folder / "prop.blend")
    shutil.copy2(kit_root() / "licenses/baton.md", project.root / "licenses/baton.md")
    atomic_write_json(
        folder / "asset.json",
        {
            "asset_id": "baton",
            "version": 1,
            "kind": "prop",
            "blend_path": "assets/props/baton/v001/prop.blend",
            "sha256": sha256_file(folder / "prop.blend"),
            "license": "CC0-1.0",
            "license_path": "licenses/baton.md",
            "objects": ["baton"],
            "root_object": "baton",
            "grips": {"primary": [0, 0, 0], "secondary": [0, 0, 0.15]},
        },
    )
    return "assets/props/baton/v001/asset.json"


def human_edit(blender_exe, blend, code):
    """Stand-in for an artist: edit the published file outside the kit and save it in place."""
    subprocess.run(
        [blender_exe, *BLENDER_FLAGS, str(blend), "--python-expr", code + "\nbpy.ops.wm.save_mainfile()"],
        check=True,
        capture_output=True,
        timeout=300,
    )


def plan_request(operation_id, **overrides):
    parameters = {
        "interaction_id": "baton-handoff",
        "giver": {"instance_id": "hero-01", "hand": "right"},
        "receiver": {"instance_id": "sidekick-01", "hand": "left"},
        "prop_instance_id": "baton-01",
        "frame_range": {"start": 1, "end_exclusive": 81},
        "handoff_frame": 40,
        **overrides,
    }
    return make_request(
        "interaction.plan", operation_id, target={"shot_id": "shot010"}, parameters=parameters
    )


def artifact(result, suffix):
    return next(a.path for a in result.artifacts if a.path.endswith(suffix))


def test_take_and_give_prop_recipes_measure_the_palm(project, baton_blend):
    character = install_character(project)
    prop = install_prop(project, baton_blend)
    runner = TaskRunner(project)
    build = runner.run(
        make_request(
            "shot.build",
            "recipes-build-001",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [
                    {"manifest_path": character, "instance_id": "hero-01"},
                    {"manifest_path": prop, "instance_id": "baton-01", "location": [-0.25, -0.25, 1.15]},
                    {"manifest_path": prop, "instance_id": "baton-far", "location": [3, 3, 1]},
                ]
            },
        )
    )
    assert build.exit_code == 0, build.result.model_dump()
    target = {"shot_id": "shot010", "instance_id": "hero-01"}

    def create(operation_id, **parameters):
        return runner.run(
            make_request("animation.create", operation_id, target=target, parameters=parameters)
        )

    far = create("take-far-001", preset="take_prop", output_clip="take-far", prop_instance_id="baton-far")
    assert far.result.errors[0].code == "VALIDATION_FAILED" and "reach" in far.result.errors[0].message
    assert not (project.root / "animation/clips/take-far").exists()
    take = create("take-001", preset="take_prop", output_clip="take-baton", prop_instance_id="baton-01")
    assert take.exit_code == 0, take.result.model_dump()
    clip = read_json(project.root / "animation/clips/take-baton/clip.json")
    assert clip["contacts"][0]["support_instance_id"] == "baton-01"
    assert clip["contacts"][0]["control_point"] == "DEF-hand.R@0.5"
    error = next(m for m in clip["measurements"] if m["kind"] == "contact_error")
    assert error["space"] == "support:baton-01" and error["passed"] and error["value"] <= 0.02
    # Re-measured in the assembled scene, against the prop instance, not trusted from the library.
    applied = runner.run(
        make_request("animation.apply", "take-apply-001", target=target, parameters={"clip_id": "take-baton"})
    )
    assert applied.exit_code == 0, applied.result.model_dump()
    assert applied.result.metrics["contact_error_max_m"] <= 0.02
    give = create(
        "give-001", preset="give_prop", output_clip="give-left", hand="left", target_point=[0.25, -0.25, 1.2]
    )
    assert give.exit_code == 0, give.result.model_dump()
    given = read_json(project.root / "animation/clips/give-left/clip.json")
    assert given["contacts"] == [] and given["measurements"][0]["space"] == "world"
    assert given["measurements"][0]["passed"] and given["layer"] == "hands"
    # Disjoint channels, joint effect: root motion carries the IK hand away from the baton.
    walk = create("walk-001", preset="walk", output_clip="walk")
    assert walk.exit_code == 0, walk.result.model_dump()
    carried = runner.run(
        make_request("animation.apply", "walk-apply-001", target=target, parameters={"clip_id": "walk"})
    )
    error = carried.result.errors[0]
    assert error.code == "VALIDATION_FAILED" and error.details["clip_id"] == "take-baton"
    assert error.details["measurements"][0]["passed"] is False
    # A clip that leaves the hand alone is accepted, and says which earlier clips it re-measured.
    nod = create("nod-001", preset="look_at", output_clip="nod")
    assert nod.exit_code == 0, nod.result.model_dump()
    harmless = runner.run(
        make_request("animation.apply", "nod-apply-001", target=target, parameters={"clip_id": "nod"})
    )
    assert harmless.exit_code == 0, harmless.result.model_dump()
    assert harmless.result.metrics["rechecked_clips"] == ["take-baton"]
    report = read_json(project.root / artifact(harmless.result, "animation-apply.json"))
    assert report["existing_clips"][0]["broken"] == 0 and report["existing_clips"][0]["measurements"]


@pytest.mark.acceptance(
    "B03", title="Prop hand-off between two characters: contacts, jump and ownership measured"
)
def test_B03_prop_handoff(project, blender_exe, baton_blend):
    character = install_character(project)
    prop = install_prop(project, baton_blend)
    runner = TaskRunner(project)
    build = runner.run(
        make_request(
            "shot.build",
            "handoff-build-001",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [
                    {"manifest_path": character, "instance_id": "hero-01"},
                    # Facing the hero, close enough for both arms.
                    {
                        "manifest_path": character,
                        "instance_id": "sidekick-01",
                        "location": [0, -0.7, 0],
                        "rotation_z": math.pi,
                    },
                    {"manifest_path": prop, "instance_id": "baton-01", "location": [1.5, 1, 0]},
                ]
            },
        )
    )
    assert build.exit_code == 0, build.result.model_dump()

    too_far = runner.run(plan_request("handoff-plan-far", interaction_id="too-far", meeting_point=[4, 4, 1]))
    assert too_far.exit_code == 0, too_far.result.model_dump()
    before = project.latest_work_blend("shot010")
    refused = runner.run(
        make_request(
            "interaction.apply",
            "handoff-apply-far",
            target={"shot_id": "shot010"},
            parameters={"plan_path": artifact(too_far.result, "interaction-plan.json")},
        )
    )
    assert (
        refused.result.errors[0].code == "VALIDATION_FAILED" and "reach" in refused.result.errors[0].message
    )
    assert project.latest_work_blend("shot010") == before, "a refused hand-off publishes nothing"

    stale_plan = runner.run(plan_request("handoff-plan-001"))
    assert stale_plan.exit_code == 0, stale_plan.result.model_dump()
    moved_on = runner.run(
        make_request(
            "animation.create",
            "handoff-idle-001",
            target={"shot_id": "shot010", "instance_id": "hero-01"},
            parameters={"preset": "look_at", "output_clip": "look-at"},
        )
    )
    assert moved_on.exit_code == 0, moved_on.result.model_dump()
    stale = runner.run(
        make_request(
            "interaction.apply",
            "handoff-apply-stale",
            target={"shot_id": "shot010"},
            parameters={"plan_path": artifact(stale_plan.result, "interaction-plan.json")},
        )
    )
    assert stale.result.errors[0].code == "SCENE_CONFLICT", "a plan made for another revision is not applied"

    plan = runner.run(plan_request("handoff-plan-002"))
    assert plan.exit_code == 0, plan.result.model_dump()
    plan_path = artifact(plan.result, "interaction-plan.json")
    planned = read_json(project.root / plan_path)
    assert [o["owner_instance_id"] for o in planned["ownership"]] == ["hero-01", "sidekick-01"]
    source = project.latest_work_blend("shot010")[1]
    source_hash = sha256_file(source)
    applied = runner.run(
        make_request(
            "interaction.apply",
            "handoff-apply-001",
            target={"shot_id": "shot010"},
            parameters={"plan_path": plan_path},
        )
    )
    assert applied.exit_code == 0, applied.result.model_dump()
    assert sha256_file(source) == source_hash, "the source version is preserved"
    metrics = applied.result.metrics
    assert metrics["technical_pass"] and metrics["contact_error_max_m"] <= 0.02
    assert metrics["handoff_jump_m"] <= 0.005 and metrics["handoff_rotation_jump_rad"] <= 0.01
    report = read_json(project.root / artifact(applied.result, "interaction-apply.json"))
    shared = [
        m
        for m in report["measurements"]
        if m["kind"] == "contact_error" and m["effector"] == "shared_hold:sidekick-01"
    ]
    # The one contact that is not true by construction: the receiver reaches a prop it does not own yet.
    assert len(shared) == 1 and shared[0]["space"] == "support:baton-01" and shared[0]["passed"]
    assert all(check["passed"] for check in report["checks"].values())

    validated = runner.run(
        make_request(
            "interaction.validate",
            "handoff-validate-001",
            target={"shot_id": "shot010"},
            parameters={"interaction_id": "baton-handoff"},
        )
    )
    assert validated.exit_code == 0 and validated.result.metrics["technical_pass"] is True

    again = runner.run(plan_request("handoff-plan-003", interaction_id="second-owner"))
    second = runner.run(
        make_request(
            "interaction.apply",
            "handoff-apply-002",
            target={"shot_id": "shot010"},
            parameters={"plan_path": artifact(again.result, "interaction-plan.json")},
        )
    )
    assert second.result.errors[0].code == "SCENE_CONFLICT", "the prop keeps a single authority"

    latest = project.latest_work_blend("shot010")[1]
    human_edit(
        blender_exe,
        latest,
        "import bpy\n"
        "rig = next(o for o in bpy.data.objects if o.get('fluidblend_instance_id') == 'sidekick-01')\n"
        "rig.location.x += 0.06",
    )
    edited_hash = sha256_file(latest)
    runner.revisions.accept_external("shot:shot010")
    broken = runner.run(
        make_request(
            "interaction.validate",
            "handoff-validate-002",
            target={"shot_id": "shot010"},
            parameters={"interaction_id": "baton-handoff"},
        )
    )
    assert broken.exit_code == 0 and broken.result.metrics["technical_pass"] is False
    failed = read_json(project.root / artifact(broken.result, "interaction-validation.json"))
    assert any(m["passed"] is False for m in failed["measurements"])
    assert sha256_file(latest) == edited_hash, "the human edit is reported, never repaired silently"
    note(
        "B03",
        f"baton passed hero-01 -> sidekick-01 at frame 40; receiver contact {shared[0]['value'] * 1000:.2f} mm in prop "
        f"space, jump {metrics['handoff_jump_m'] * 1000:.3f} mm; unreachable target, stale plan and second authority "
        "refused; a 6 cm human move is detected by validate and preserved; artistic review pending",
    )
