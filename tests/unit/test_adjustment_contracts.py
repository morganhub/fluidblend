"""Adjustment contracts: bounded parameters and a complete tool contract (§12.2), without Blender."""

import pytest
from pydantic import ValidationError

from fluidblend.contracts.operations import OPERATIONS, validate_request
from fluidblend.contracts.production import (
    ADJUSTMENT_TOOLS,
    AdjustmentParams,
    ContactLockParams,
    CustomTool,
    LookAtTargetParams,
)
from fluidblend.core.custom_tools import limitations
from fluidblend.core.project import kit_root

CONTRACT_FIELDS = {
    "tool_id",
    "version",
    "purpose",
    "supported_rigs",
    "parameters",
    "time_scope",
    "affected_channels",
    "preconditions",
    "preview_mode",
    "effects_on_sources",
    "revert",
    "tests",
    "known_limits",
}
LOCK = {
    "adjustment_id": "plant-left",
    "effector": "left_foot",
    "frame_range": {"start": 1, "end_exclusive": 26},
}


def test_contact_lock_parameters_are_bounded():
    params = ContactLockParams(**LOCK)
    assert params.support_instance_id is None and params.max_correction_m == 0.15
    for broken in (
        {"effector": "head"},
        {"frame_range": {"start": 5, "end_exclusive": 6}},
        {"max_correction_m": 0},
        {"max_correction_m": 2},
        {"blend_frames": 0},
        {"tool": "scale_gesture"},
        {"strength": 1.0},
    ):
        with pytest.raises(ValidationError):
            ContactLockParams(**{**LOCK, **broken})


def test_every_available_tool_declares_the_full_contract_and_existing_tests():
    for tool_id, contract in ADJUSTMENT_TOOLS.items():
        assert contract["tool_id"] == tool_id and set(contract) == CONTRACT_FIELDS
        assert all(contract[field] for field in CONTRACT_FIELDS), "no empty contract field"
        for test in contract["tests"]:
            assert (kit_root() / test.split("::")[0]).is_file(), f"declared test is missing: {test}"


def test_preview_is_a_read_and_apply_revert_create_versions():
    assert OPERATIONS["adjustment.preview"].op_class == "read"
    assert not OPERATIONS["adjustment.preview"].creates_version
    for name in ("adjustment.apply", "adjustment.revert"):
        assert OPERATIONS[name].op_class == "write" and OPERATIONS[name].creates_version


GAZE = {
    "adjustment_id": "watch-baton",
    "tool": "look_at_target",
    "target_instance_id": "baton-01",
    "frame_range": {"start": 12, "end_exclusive": 40},
}


def test_look_at_target_parameters_are_bounded():
    params = LookAtTargetParams(**GAZE)
    assert params.max_angle_deg == 60 and params.blend_frames == 8
    for broken in (
        {"target_point": [0, 0, 1]},  # two targets
        {"target_instance_id": None},  # none
        {"target_instance_id": None, "target_point": [0, 1]},
        {"target_instance_id": None, "target_point": [0, float("nan"), 1]},
        {"max_angle_deg": 120},
        {"max_step_deg": 0},
        {"frame_range": {"start": 5, "end_exclusive": 6}},
        {"effector": "left_foot"},
        {"custom_tool_id": "gentle-lock"},
    ):
        with pytest.raises(ValidationError):
            LookAtTargetParams(**{**GAZE, **broken})


def test_adjustment_requests_pick_their_tool_and_old_requests_stay_contact_lock():
    assert isinstance(AdjustmentParams.model_validate(LOCK).root, ContactLockParams)
    assert isinstance(AdjustmentParams.model_validate(GAZE).root, LookAtTargetParams)
    with pytest.raises(ValidationError):
        AdjustmentParams.model_validate({**LOCK, "tool": "scale_gesture"})
    payload = {
        "schema_version": "1.0",
        "operation": "adjustment.preview",
        "operation_id": "gaze-001",
        "project_id": "demo",
        "target": {"shot_id": "shot010", "instance_id": "hero-01"},
        "parameters": GAZE,
    }
    _request, params, _spec = validate_request(payload)
    assert params.model_dump()["tool"] == "look_at_target"


def test_a_custom_tool_cannot_narrow_look_at_target_yet():
    tool = CustomTool.model_validate(
        {
            "tool_id": "soft-gaze",
            "version": 1,
            "purpose": "a gentler look_at_target for close-ups",
            "base_tool": "look_at_target",
            "supported_rigs": ["rigify/0.6.10"],
            "bounds": {"effectors": ["left_foot"], "max_correction_m": 0.1},
            "known_limits": ["none stated"],
            "tests": [
                {
                    "name": "t1",
                    "instance_id": "hero-01",
                    "effector": "left_foot",
                    "frame_range": {"start": 1, "end_exclusive": 10},
                    "expect": "pass",
                }
            ],
        }
    )
    assert "cannot be narrowed yet" in limitations(tool)[0]
