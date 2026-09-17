import pytest
from tests.acceptance.test_adjustments import DRIFT
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact, human_edit
from tests.conftest import make_request, note

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender

STANCE = {"start": 1, "end_exclusive": 26}
WHOLE_CYCLE = {"start": 1, "end_exclusive": 49}


def declare(project, tool_id, **overrides):
    tool = {
        "tool_id": tool_id,
        "version": 1,
        "purpose": "plant a sliding foot, small corrections only",
        "base_tool": "contact_lock",
        "supported_rigs": ["rigify/0.6.10"],
        "bounds": {"effectors": ["left_foot", "right_foot"], "max_correction_m": 0.12},
        "known_limits": ["feet only", "refuses windows that contain a step"],
        "tests": [
            {
                "name": "fix-left",
                "instance_id": "hero-01",
                "effector": "left_foot",
                "frame_range": STANCE,
                "expect": "pass",
            },
            {
                "name": "decline-step",
                "instance_id": "hero-01",
                "effector": "left_foot",
                "frame_range": WHOLE_CYCLE,
                "expect": "refuse",
            },
        ],
        **overrides,
    }
    path = project.root / f"tools/custom/{tool_id}/tool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, tool)
    return path


@pytest.mark.acceptance("B08", title="Custom tool request: a bounded tested tool, or a stated limitation")
def test_B08_custom_tool_is_bounded_tested_or_refused(project, blender_exe):
    manifest = install_character(project)
    runner = TaskRunner(project)
    shot = {"shot_id": "shot010"}
    hero = {**shot, "instance_id": "hero-01"}
    for operation, operation_id, target, parameters in (
        (
            "shot.build",
            "tool-build",
            shot,
            {"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]},
        ),
        ("animation.create", "tool-walk", hero, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "tool-walk-apply", hero, {"clip_id": "walk"}),
    ):
        assert (
            runner.run(make_request(operation, operation_id, target=target, parameters=parameters)).exit_code
            == 0
        )
    human_edit(blender_exe, project.latest_work_blend("shot010")[1], DRIFT)
    runner.revisions.accept_external("shot:shot010")

    def run(operation, operation_id, parameters, target=None):
        return runner.run(make_request(operation, operation_id, target=target or {}, parameters=parameters))

    # "Make the gesture wider" and "lock the foot of the simple biped": no algorithm, no IK. Say so.
    declare(project, "wider-gesture", base_tool="scale_gesture")
    declare(project, "biped-foot-lock", supported_rigs=["fluidblend.simple_biped/1"])
    for tool_id, word in (("wider-gesture", "not implemented"), ("biped-foot-lock", "IK")):
        inspected = run("tool.inspect", f"inspect-{tool_id}", {"tool_id": tool_id})
        assert inspected.exit_code == 0 and inspected.result.metrics["status"] == "unsupported"
        assert word in inspected.result.metrics["limitations"][0]
        tested = run("tool.test", f"test-{tool_id}", {"tool_id": tool_id}, shot)
        assert tested.result.errors[0].code == "VALIDATION_FAILED" and tested.task is None
        registered = run(
            "tool.register",
            f"register-{tool_id}",
            {"tool_id": tool_id, "test_report_path": "licenses/vitruvian.md"},
        )
        assert registered.result.errors[0].code == "UNSUPPORTED_CAPABILITY"
        assert not (project.root / f"tools/custom/{tool_id}/registration.json").exists()

    # A tool that claims more than it does fails its own test and stays unregistered.
    declare(
        project,
        "overconfident",
        tests=[
            {
                "name": "fix-anything",
                "instance_id": "hero-01",
                "effector": "left_foot",
                "frame_range": WHOLE_CYCLE,
                "expect": "pass",
            }
        ],
    )
    failing = run("tool.test", "test-overconfident", {"tool_id": "overconfident"}, shot)
    assert failing.exit_code == 0 and failing.result.metrics["all_passed"] is False
    refused = run(
        "tool.register",
        "register-overconfident",
        {"tool_id": "overconfident", "test_report_path": artifact(failing.result, "tool-test.json")},
    )
    assert refused.result.errors[0].code == "VALIDATION_FAILED"

    declared = declare(project, "gentle-foot-lock")
    lock = {
        "adjustment_id": "plant-left",
        "custom_tool_id": "gentle-foot-lock",
        "effector": "left_foot",
        "frame_range": STANCE,
    }
    unregistered = run("adjustment.preview", "gentle-too-early", lock, hero)
    assert "not registered" in unregistered.result.errors[0].message
    tested = run("tool.test", "test-gentle", {"tool_id": "gentle-foot-lock"}, shot)
    assert tested.exit_code == 0 and tested.result.metrics["all_passed"] is True
    report_path = artifact(tested.result, "tool-test.json")
    results = {r["name"]: r for r in read_json(project.root / report_path)["results"]}
    assert results["fix-left"]["contact_after_m"] <= 0.02 and results["decline-step"]["refused"]
    registered = run(
        "tool.register", "register-gentle", {"tool_id": "gentle-foot-lock", "test_report_path": report_path}
    )
    assert registered.exit_code == 0, registered.result.model_dump()
    assert (
        run("tool.inspect", "inspect-gentle", {"tool_id": "gentle-foot-lock"}).result.metrics["status"]
        == "registered"
    )

    for operation_id, change in (
        ("gentle-hand", {"effector": "left_hand"}),
        ("gentle-wide", {"max_correction_m": 0.15}),
    ):
        beyond = run("adjustment.apply", operation_id, {**lock, **change}, hero)
        assert beyond.result.errors[0].code == "VALIDATION_FAILED" and beyond.task is None
    applied = run("adjustment.apply", "gentle-apply", lock, hero)
    assert applied.exit_code == 0, applied.result.model_dump()
    assert applied.result.metrics["contact_after_m"] <= 0.02

    # Widening the bound after registration does not widen the capability.
    tool = read_json(declared)
    tool["bounds"]["max_correction_m"] = 0.5
    atomic_write_json(declared, tool)
    stale = run("adjustment.preview", "gentle-stale", {**lock, "adjustment_id": "plant-again"}, hero)
    assert "changed after registration" in stale.result.errors[0].message
    assert (
        run("tool.inspect", "inspect-gentle-2", {"tool_id": "gentle-foot-lock"}).result.metrics["status"]
        == "registration_stale"
    )
    note(
        "B08",
        "unimplemented base tool and IK-less rig -> stated limitation, no test, no registration; failing tool not "
        "registered; bounded declarative tool tested (1 fix, 1 refusal), registered, applied within its bounds, "
        "refused beyond them and after its declaration changed; no custom code is executed",
    )
