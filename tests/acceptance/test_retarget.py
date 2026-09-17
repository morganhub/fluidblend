"""Bounded retargeting (B02): the P0 biped walk onto the Rigify character, source preserved."""

import pytest
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request, note

from fluidblend.core.atomic import read_json
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


@pytest.mark.acceptance(
    "B02", title="Bounded retargeting: biped walk onto the Rigify character, source preserved"
)
def test_B02_biped_walk_onto_rigify(project):
    runner = TaskRunner(project)
    built = runner.run(
        make_request(
            "scene.build", "retarget-scene", target={"shot_id": "shot010"}, parameters={"frames": 96}
        )
    )
    assert built.exit_code == 0, built.result.model_dump()
    manifest = install_character(project)
    added = runner.run(
        make_request(
            "shot.build",
            "retarget-actor",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [{"manifest_path": manifest, "instance_id": "actor-01", "location": [3, 0, 0]}]
            },
        )
    )
    assert added.exit_code == 0, added.result.model_dump()

    def source_action():
        inspected = runner.run(
            make_request(
                "scene.inspect",
                f"retarget-inspect-{len(list((project.root / 'reviews/shot010').iterdir()))}",
                target={"shot_id": "shot010"},
                parameters={"include_actions": True},
            )
        )
        report = read_json(project.root / artifact(inspected.result, "inspect.json"))
        return next(
            a
            for a in report["actions"]
            if a["custom"].get("fluidblend_clip_id") == "walk" and "hero-01" in a["name"]
        )

    before = source_action()

    def retarget(operation_id, target_instance="actor-01", **overrides):
        parameters = {
            "source_instance_id": "hero-01",
            "source_clip": "walk",
            "output_clip": "walk-from-biped",
            "frame_range": {"start": 1, "end_exclusive": 49},
            **overrides,
        }
        return runner.run(
            make_request(
                "animation.retarget",
                operation_id,
                target={"shot_id": "shot010", "instance_id": target_instance},
                parameters=parameters,
            )
        )

    # No universal solver: only the declared pair of profiles, and only the clip really assigned.
    wrong_target = retarget("retarget-onto-biped", target_instance="sidekick-01")
    assert wrong_target.result.errors[0].code == "RIG_MAPPING_REQUIRED"
    wrong_source = retarget("retarget-from-rigify", source_instance_id="actor-01", target_instance="actor-01")
    assert wrong_source.result.errors
    wrong_clip = retarget("retarget-wrong-clip", source_clip="run")
    assert wrong_clip.result.errors[0].code == "SCENE_CONFLICT"
    assert not (project.root / "animation/clips/walk-from-biped").exists()

    done = retarget("retarget-001")
    assert done.exit_code == 0, done.result.model_dump()
    assert done.result.metrics["limb_error_max_deg"] <= 3.0 and done.result.metrics["frames"] == 48
    # A zero error only means something if the source limbs really swing.
    assert done.result.metrics["source_limb_swing_deg"] > 10
    report = read_json(project.root / artifact(done.result, "retarget-report.json"))
    assert len(report["test_poses"]) == 3 and report["source_preserved"] is True
    assert report["unmapped_source_bones"] == ["spine", "neck"]
    assert report["root_travel_m"] > 0.3, "the walk really travels on the target"
    clip = read_json(project.root / "animation/clips/walk-from-biped/clip.json")
    assert clip["source_clip"] == "walk" and clip["root_motion"] == "root_bone"
    assert {m["effector"] for m in clip["measurements"]} == {"left_arm", "right_arm", "left_leg", "right_leg"}
    assert all(m["passed"] and m["unit"] == "deg" for m in clip["measurements"])
    assert before == source_action(), "the source Action is only read"

    applied = runner.run(
        make_request(
            "animation.apply",
            "retarget-apply",
            target={"shot_id": "shot010", "instance_id": "actor-01"},
            parameters={"clip_id": "walk-from-biped"},
        )
    )
    assert applied.exit_code == 0, applied.result.model_dump()
    note(
        "B02",
        f"biped walk -> Rigify FK controls, 48 frames after 3 test poses; limb direction error "
        f"{done.result.metrics['limb_error_max_deg']:.2f} deg max on the deform chain, leg ratio "
        f"{report['leg_length_ratio']:.3f}, travel {report['root_travel_m']:.2f} m; wrong rig pair and wrong clip "
        "refused; source Action unchanged; feet are not re-planted; artistic review pending",
    )
