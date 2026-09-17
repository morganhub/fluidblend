"""Pure arithmetic of the shared contact/loop measurements; Blender sampling is covered in acceptance."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "blender_runtime"))

from fluidblend.contracts.production import ClipManifest, ContactWindow, Measurement  # noqa: E402
from fluidblend_runtime.anim import measures  # noqa: E402


def test_window_is_half_open_and_stepped():
    assert measures.window_frames({"start": 1, "end_exclusive": 5}) == [1, 2, 3, 4]
    assert measures.window_frames({"start": 1, "end_exclusive": 8}, 3) == [1, 4, 7]


def test_drift_is_measured_from_the_first_sample_in_3d():
    points = [(0, 0, 0), (0.01, 0, 0), (0, 0.03, 0.04)]
    assert measures.max_drift(points) == pytest.approx(0.05)
    assert measures.max_drift([]) == 0.0
    assert measures.max_anchor_error(points, (0, 0, 0.04)) == pytest.approx(0.0412310, abs=1e-6)


def test_loop_pose_and_seam_velocity():
    first, last = [(0, 0, 0), (1, 1, 1)], [(0, 0, 0.002), (1, 1, 1)]
    assert measures.pose_error(first, last) == pytest.approx(0.002)
    # Same position, opposite velocity: a pose-only check would miss this seam.
    start = ([(0, 0, 0)], [(0.1, 0, 0)])
    end = ([(0.1, 0, 0)], [(0, 0, 0)])
    assert measures.velocity_error(start, end) == pytest.approx(0.2)


def test_record_carries_its_definition_and_never_passes_ungated():
    window = {"start": 1, "end_exclusive": 26}
    common = {
        "effector": "left_foot",
        "control_point": "DEF-foot.L",
        "space": "world",
        "frame_range": window,
        "step": 1,
        "unit": "m",
    }
    gated = measures.record("foot_slide", value=0.03, tolerance=0.02, **common)
    ungated = measures.record("loop_velocity", value=0.5, **{**common, "unit": "m/frame"})
    assert gated["passed"] is False and ungated["passed"] is None
    assert measures.failures([gated, ungated]) == [gated]
    Measurement.model_validate(gated)
    Measurement.model_validate(ungated)
    with pytest.raises(ValueError):
        measures.record("foot_slide", value=math.nan, tolerance=0.02, **common)


def test_contact_window_defaults_to_world_ground_and_manifest_accepts_measurements():
    contact = ContactWindow(
        effector="left_foot",
        control_point="DEF-foot.L",
        frame_range={"start": 1, "end_exclusive": 26},
        anchor=[0.2, 0, 0.09],
    )
    assert contact.support_instance_id is None
    manifest = ClipManifest(
        clip_id="walk",
        action="rig.walk",
        slot="OBrig",
        rig_profile="rigify/0.6.10",
        frame_range={"start": 1, "end_exclusive": 49},
        root_motion="root_bone",
        contacts=[contact],
        events=[{"name": "contact-left", "frame": 1}],
        layer="locomotion",
        owned_channels=[('pose.bones["root"].location', 1)],
        root_motion_channels=[('pose.bones["root"].location', 1)],
        stride_m=0.6,
    )
    assert manifest.measurements == []
