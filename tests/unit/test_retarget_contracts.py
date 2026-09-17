"""Bounded retargeting: parameters and preset consistency, without Blender."""

import pytest
from pydantic import ValidationError

from fluidblend.contracts.production import AnimationRetargetParams
from fluidblend.core.production import RETARGET_PRESETS, RIGIFY_CONTROLS

BASE = {"source_instance_id": "hero-01", "source_clip": "walk", "output_clip": "walk-from-biped"}


def test_range_is_bounded_and_only_declared_presets_exist():
    AnimationRetargetParams(**BASE, frame_range={"start": 1, "end_exclusive": 49})
    for broken in (
        {"frame_range": {"start": 1, "end_exclusive": 2}},
        {"frame_range": {"start": 1, "end_exclusive": 5000}},
        {"frame_range": {"start": 1, "end_exclusive": 49}, "preset": "mixamo_to_rigify"},
        {"frame_range": {"start": 1, "end_exclusive": 49}, "test_poses": 1},
    ):
        with pytest.raises(ValidationError):
            AnimationRetargetParams(**BASE, **broken)


def test_every_preset_role_exists_in_the_target_profile_and_parents_come_first():
    for preset in RETARGET_PRESETS.values():
        roles = [role for _, role in preset["bones"]] + preset["fk_switches"] + [preset["target_leg"][0]]
        roles += [limb[4] for limb in preset["limbs"]] + [preset["target_leg"][1]]
        assert set(roles) <= set(RIGIFY_CONTROLS), set(roles) - set(RIGIFY_CONTROLS)
        order = [source for source, _ in preset["bones"]]
        for _name, first, second, end, _role in preset["limbs"]:
            assert order.index(first) < order.index(second) < order.index(end)
        assert not set(order) & set(preset["unmapped_source_bones"])
