import pytest
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact, baton_blend, human_edit, install_prop  # noqa: F401
from tests.conftest import make_request, note

from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender

DRIFT = (
    "import bpy\n"
    "rig = next(o for o in bpy.data.objects if o.get('fluidblend_instance_id') == 'hero-01')\n"
    "rig.location.x = 0.0\n"
    "rig.keyframe_insert('location', frame=1)\n"
    "rig.location.x = 0.10\n"
    "rig.keyframe_insert('location', frame=25)\n"
)


@pytest.mark.acceptance("B05", title="Sliding stance fixed with contact_lock: preview, apply, revert")
def test_B05_contact_lock_preview_apply_revert(project, blender_exe):
    manifest = install_character(project)
    runner = TaskRunner(project)
    target = {"shot_id": "shot010", "instance_id": "hero-01"}
    for operation, operation_id, extra_target, parameters in (
        ("shot.build", "lock-build", {}, {"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]}),
        ("animation.create", "lock-walk", target, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "lock-walk-apply", target, {"clip_id": "walk"}),
    ):
        outcome = runner.run(
            make_request(
                operation, operation_id, target={"shot_id": "shot010", **extra_target}, parameters=parameters
            )
        )
        assert outcome.exit_code == 0, outcome.result.model_dump()
    # An artist keys a 10 cm sideways drift of the whole character during the left stance.
    edited = project.latest_work_blend("shot010")[1]
    human_edit(blender_exe, edited, DRIFT)
    runner.revisions.accept_external("shot:shot010")
    edited_hash = sha256_file(edited)
    lock = {
        "adjustment_id": "plant-left",
        "effector": "left_foot",
        "frame_range": {"start": 1, "end_exclusive": 26},
    }

    def run(operation, operation_id, parameters):
        return runner.run(make_request(operation, operation_id, target=target, parameters=parameters))

    travel = run(
        "adjustment.preview", "lock-travel", {**lock, "frame_range": {"start": 1, "end_exclusive": 49}}
    )
    assert travel.result.errors[0].code == "VALIDATION_FAILED" and "travel" in travel.result.errors[0].message
    planted = run(
        "adjustment.preview",
        "lock-planted",
        {**lock, "effector": "right_foot", "frame_range": {"start": 30, "end_exclusive": 48}},
    )
    assert "nothing to lock" in planted.result.errors[0].message, "an already planted foot is left alone"

    before_preview = project.latest_work_blend("shot010")
    preview = run("adjustment.preview", "lock-preview", lock)
    assert preview.exit_code == 0, preview.result.model_dump()
    assert project.latest_work_blend("shot010") == before_preview, "a preview saves no version"
    metrics = preview.result.metrics
    assert (
        metrics["contact_before_m"] == pytest.approx(0.10, abs=0.005) and metrics["contact_after_m"] <= 0.02
    )
    frames = project.root / next(a.path for a in preview.result.artifacts if a.kind == "frames")
    assert len(list((frames / "before").glob("*.png"))) == 4 == len(list((frames / "after").glob("*.png")))
    # Close-ups over a fixed mark at the contact: the whole-body frames do not show a 10 cm slide.
    for side in ("closeup-before", "closeup-after"):
        assert len(list((frames / side).glob("*.png"))) == 4

    applied = run("adjustment.apply", "lock-apply", lock)
    assert applied.exit_code == 0, applied.result.model_dump()
    assert applied.result.metrics["contact_after_m"] <= 0.02
    assert sha256_file(edited) == edited_hash, "the artist's version is preserved"
    report = read_json(project.root / artifact(applied.result, "adjustment-apply.json"))
    assert report["after"][0]["space"] == "world" and report["after"][0]["control_point"] == "DEF-foot.L"
    assert run("adjustment.apply", "lock-apply-again", lock).result.errors[0].code == "SCENE_CONFLICT"

    reverted = run("adjustment.revert", "lock-revert", {"adjustment_id": "plant-left"})
    assert reverted.exit_code == 0, reverted.result.model_dump()
    assert reverted.result.metrics["contact_restored_m"] == pytest.approx(
        metrics["contact_before_m"], abs=1e-4
    )
    assert run("adjustment.revert", "lock-revert-again", {"adjustment_id": "plant-left"}).result.errors
    note(
        "B05",
        f"artist drift {metrics['contact_before_m'] * 1000:.1f} mm -> {applied.result.metrics['contact_after_m'] * 1000:.2f} mm "
        "after contact_lock (world, DEF-foot.L); travel window and planted foot refused; preview saved nothing; "
        "revert restored the drift exactly; artist file hash unchanged; artistic review pending",
    )


def test_look_at_target_preview_apply_revert(project, baton_blend):  # noqa: F811
    character = install_character(project)
    prop = install_prop(project, baton_blend)
    runner = TaskRunner(project)
    target = {"shot_id": "shot010", "instance_id": "hero-01"}
    assets = [
        {"manifest_path": character, "instance_id": "hero-01"},
        # Ahead of the walking character, to its side, at eye height.
        {"manifest_path": prop, "instance_id": "baton-01", "location": [-1.2, -2.0, 1.5]},
    ]
    for operation, operation_id, extra_target, parameters in (
        ("shot.build", "gaze-build", {}, {"assets": assets}),
        ("animation.create", "gaze-walk", target, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "gaze-walk-apply", target, {"clip_id": "walk"}),
    ):
        outcome = runner.run(
            make_request(
                operation, operation_id, target={"shot_id": "shot010", **extra_target}, parameters=parameters
            )
        )
        assert outcome.exit_code == 0, outcome.result.model_dump()
    gaze = {
        "adjustment_id": "watch-baton",
        "tool": "look_at_target",
        "target_instance_id": "baton-01",
        "frame_range": {"start": 12, "end_exclusive": 40},
    }

    def run(operation, operation_id, parameters):
        return runner.run(make_request(operation, operation_id, target=target, parameters=parameters))

    behind = {k: v for k, v in gaze.items() if k != "target_instance_id"} | {"target_point": [0, 3, 1.6]}
    refused = run("adjustment.preview", "gaze-behind", behind)
    assert "max_angle_deg" in refused.result.errors[0].message
    rushed = run("adjustment.apply", "gaze-rushed", {**gaze, "blend_frames": 1})
    assert rushed.result.errors[0].code == "VALIDATION_FAILED", "a one-frame head snap is not published"
    assert rushed.result.errors[0].details["after"][0]["kind"] == "gaze_step"

    before_preview = project.latest_work_blend("shot010")
    preview = run("adjustment.preview", "gaze-preview", gaze)
    assert preview.exit_code == 0, preview.result.model_dump()
    assert project.latest_work_blend("shot010") == before_preview, "a preview saves no version"
    metrics = preview.result.metrics
    assert metrics["gaze_before_deg"] > 20 and metrics["gaze_after_deg"] <= 2.0
    assert metrics["gaze_step_deg"] <= 12.0

    applied = run("adjustment.apply", "gaze-apply", gaze)
    assert applied.exit_code == 0, applied.result.model_dump()
    report = read_json(project.root / artifact(applied.result, "adjustment-apply.json"))
    assert report["tool"] == "look_at_target" and report["after"][0]["unit"] == "deg"
    assert report["after"][0]["control_point"].startswith("DEF-"), "measured on the skin's bone"
    assert run("adjustment.apply", "gaze-again", gaze).result.errors[0].code == "SCENE_CONFLICT"
    # The target moves with the walk: the head follows on every frame, so nothing is left to adjust.
    second = run("adjustment.preview", "gaze-second", {**gaze, "adjustment_id": "watch-again"})
    assert "already looks" in second.result.errors[0].message

    reverted = run("adjustment.revert", "gaze-revert", {"adjustment_id": "watch-baton"})
    assert reverted.exit_code == 0, reverted.result.model_dump()
    assert reverted.result.metrics["gaze_restored_deg"] == pytest.approx(metrics["gaze_before_deg"], abs=1e-3)
