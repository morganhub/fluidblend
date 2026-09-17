"""Lip-sync admission: exact time mapping, cue validation and face profiles — without Blender."""

import pytest
from pydantic import ValidationError
from tests.conftest import make_request
from tests.unit.test_interaction_contracts import _fake_version

from fluidblend.contracts.production import AssetManifest, ExpressionApplyParams, LipsyncApplyParams
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.production import FACE_PROFILES, lipsync_cues
from fluidblend.core.project import load_project
from fluidblend.core.tasks import TaskRunner


def _analysis(root, cues):
    path = root / "reviews/handmade/lipsync-analysis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, {"source_path": "audio/x.wav", "source_sha256": "0" * 64, "mouthCues": cues})
    return "reviews/handmade/lipsync-analysis.json"


def _request(path, **parameters):
    return make_request(
        "lipsync.apply",
        "lips-001",
        target={"shot_id": "shot010", "instance_id": "hero-01"},
        parameters={"lipsync_id": "line-01", "analysis_path": path, **parameters},
    )


def test_every_rhubarb_shape_is_mapped_and_rest_drives_nothing():
    profile = FACE_PROFILES["charmorph-l3/1"]
    assert set(profile["visemes"]) == set("ABCDEFGHX") and profile["visemes"]["X"] == {}
    assert all(0 < w <= 1 for mix in profile["visemes"].values() for w in mix.values())


def test_seconds_become_fractional_frames_without_rounding(project_root):
    project = load_project(project_root)
    path = _analysis(
        project_root, [{"start": 0.0, "end": 0.07, "value": "X"}, {"start": 0.07, "end": 0.5, "value": "D"}]
    )
    from fluidblend.contracts.operations import validate_request

    request, _params, _spec = validate_request(_request(path, start_frame=101))
    cues = lipsync_cues(project, request)["cues"]
    # 24 fps: 0.07 s is frame 1.68 after the start, kept as such (rounding would drift up to half a frame).
    assert cues[1]["start_frame"] == pytest.approx(102.68) and cues[1]["end_frame"] == pytest.approx(113.0)


@pytest.mark.parametrize(
    "cues",
    [
        [{"start": 0.5, "end": 0.4, "value": "D"}],
        [{"start": 0.0, "end": 0.5, "value": "D"}, {"start": 0.3, "end": 0.8, "value": "A"}],
        [{"start": 0.0, "end": 0.5, "value": "Z"}],
        [{"start": 0.0, "end": 0.5, "value": "X"}],
        [{"start": 0.0, "value": "D"}],
    ],
)
def test_invalid_or_silent_analysis_is_refused_before_any_task(project_root, cues):
    _fake_version(project_root, 1, b"scene")
    outcome = TaskRunner(load_project(project_root)).run(_request(_analysis(project_root, cues)))
    assert outcome.result.errors[0].code == "VALIDATION_FAILED" and outcome.task is None


def test_parameters_are_bounded_and_props_have_no_face():
    LipsyncApplyParams(lipsync_id="l", analysis_path="a.json")
    for broken in ({"transition_frames": 0.1}, {"strength": 0}, {"preview_samples": 99}):
        with pytest.raises(ValidationError):
            LipsyncApplyParams(lipsync_id="l", analysis_path="a.json", **broken)
    with pytest.raises(ValidationError):
        ExpressionApplyParams(
            expression_id="e", expression="happy", frame_range={"start": 1, "end_exclusive": 6}, ease_frames=4
        )
    with pytest.raises(ValidationError):
        ExpressionApplyParams(
            expression_id="e", expression="wink", frame_range={"start": 1, "end_exclusive": 40}
        )
    with pytest.raises(ValidationError):
        AssetManifest(
            asset_id="baton",
            version=1,
            blend_path="p.blend",
            sha256="0" * 64,
            license="CC0-1.0",
            license_path="l.md",
            objects=["baton"],
            kind="prop",
            root_object="baton",
            grips={"primary": [0, 0, 0]},
            face_profile="charmorph-l3/1",
        )
