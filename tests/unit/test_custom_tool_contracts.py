"""Declarative custom tools: narrowing only, stated limitations, bounds enforced — without Blender."""

import pytest
from pydantic import ValidationError
from tests.conftest import make_request

from fluidblend.contracts.production import CustomTool, ToolRegistration
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.custom_tools import enforce_bounds, limitations
from fluidblend.core.project import load_project
from fluidblend.core.tasks import TaskRunner

TOOL = {
    "tool_id": "gentle-foot-lock",
    "version": 1,
    "purpose": "plant a sliding foot, small corrections only",
    "base_tool": "contact_lock",
    "supported_rigs": ["rigify/0.6.10"],
    "bounds": {"effectors": ["left_foot"], "max_correction_m": 0.1},
    "known_limits": ["left foot only"],
    "tests": [
        {
            "name": "fix-left",
            "instance_id": "hero-01",
            "effector": "left_foot",
            "frame_range": {"start": 1, "end_exclusive": 26},
            "expect": "pass",
        }
    ],
}


def test_declaration_cannot_widen_or_skip_its_tests():
    assert limitations(CustomTool(**TOOL)) == []
    only_refusals = [{**TOOL["tests"][0], "expect": "refuse"}]
    for broken in (
        {"bounds": {"effectors": ["left_foot"], "max_correction_m": 0.8}},
        {"bounds": {"effectors": ["tail"], "max_correction_m": 0.1}},
        {"tests": []},
        {"tests": only_refusals},
        {"tests": TOOL["tests"] * 2},
        {"known_limits": []},
        {"script": "tools/custom/gentle-foot-lock/run.py"},
    ):
        with pytest.raises(ValidationError):
            CustomTool(**{**TOOL, **broken})


def test_unsupported_requests_become_limitations_not_parse_errors():
    assert "not implemented" in limitations(CustomTool(**{**TOOL, "base_tool": "scale_gesture"}))[0]
    assert "IK" in limitations(CustomTool(**{**TOOL, "supported_rigs": ["fluidblend.simple_biped/1"]}))[0]


def test_registered_bounds_apply_even_when_the_request_omits_them():
    registration = ToolRegistration(
        tool_id="gentle-foot-lock",
        version=1,
        base_tool="contact_lock",
        supported_rigs=["rigify/0.6.10"],
        bounds=TOOL["bounds"],
        tool_sha256="0" * 64,
        test_report="reviews/shot010/test/tool-test.json",
        test_report_sha256="1" * 64,
        tests_passed=1,
    )
    assert enforce_bounds(registration, {"effector": "left_foot"})["max_correction_m"] == 0.1
    for beyond in ({"effector": "right_foot"}, {"effector": "left_foot", "max_correction_m": 0.15}):
        with pytest.raises(ValueError):
            enforce_bounds(registration, beyond)


def test_inspect_reports_a_limitation_and_register_refuses_it(project_root):
    path = project_root / "tools/custom/wider-gesture/tool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {**TOOL, "tool_id": "wider-gesture", "base_tool": "scale_gesture"})
    runner = TaskRunner(load_project(project_root))
    inspected = runner.run(
        make_request("tool.inspect", "inspect-001", parameters={"tool_id": "wider-gesture"})
    )
    assert inspected.exit_code == 0 and inspected.result.metrics["status"] == "unsupported"
    refused = runner.run(
        make_request(
            "tool.register",
            "register-001",
            parameters={"tool_id": "wider-gesture", "test_report_path": "project.json"},
        )
    )
    assert refused.result.errors and not (path.parent / "registration.json").exists()
    missing = runner.run(make_request("tool.inspect", "inspect-002", parameters={"tool_id": "nothing-here"}))
    assert missing.result.errors[0].code == "VALIDATION_FAILED"
