"""Adjustment contracts: bounded parameters and a complete tool contract (§12.2), without Blender."""

import pytest
from pydantic import ValidationError

from fluidblend.contracts.operations import OPERATIONS
from fluidblend.contracts.production import ADJUSTMENT_TOOLS, ContactLockParams
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
