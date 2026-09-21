"""The hand-off bundle contract: what it refuses is the point."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fluidblend.contracts.handoff import HandoffBundle

SHA = "a" * 64


def bundle(**overrides):
    data = {
        "bundle_id": "export-shot010-001",
        "producer": {
            "kit": "fluidblend",
            "version": "0.6.0",
            "operation": "game.export",
            "operation_id": "export-shot010-001",
            "project_id": "my-film",
            "shot_id": "shot010",
            "source_revision": 7,
            "created_at": "2026-09-20T10:00:00Z",
        },
        "fps": {"numerator": 24, "denominator": 1},
        "axis_convention": {
            "blender": {"up": "+Z", "forward": "-Y"},
            "gltf": {"up": "+Y", "forward": "+Z"},
        },
        "files": [
            {"role": "model", "path": "shot010-hero.glb", "format": "glb", "sha256": SHA, "bytes": 12},
            {"role": "license", "path": "licenses/vitruvian.md", "sha256": SHA},
        ],
        "validation": {"khronos": "not_run", "reimport_passed": True},
        "instances": [
            {
                "instance_id": "hero-01",
                "kind": "character",
                "asset_id": "vitruvian",
                "asset_version": 3,
                "license": "CC0-1.0",
                "license_file": "licenses/vitruvian.md",
                "rig_profile": "rigify",
                "armature": "rig",
                "skinned": True,
                "baked": True,
                "export_def_bones": True,
                "bone_count": 188,
                "gltf_node_name": "rig",
                "reference_pose": [{"bone": "DEF-spine", "head_m": [0.0, 0.0, 1.05]}],
            }
        ],
        "clips": [
            {
                "clip_id": "walk",
                "instance_id": "hero-01",
                "gltf_animation_name": "rig.walk",
                "frame_range": {"start": 0, "end_exclusive": 96},
                "loop": True,
                "root_motion": "root_bone",
                "stride_m": 0.6,
                "repetitions": 4,
            }
        ],
    }
    data.update(overrides)
    return data


def test_the_reference_bundle_validates_and_finds_its_files():
    parsed = HandoffBundle.model_validate(bundle())
    assert parsed.kind == "handoff-bundle" and parsed.units == "meters"
    assert parsed.file("model").path == "shot010-hero.glb"
    assert parsed.file("khronos_report") is None
    assert parsed.clips[0].frame_range.count == 96


def test_a_bundle_without_a_licence_is_refused():
    data = bundle()
    data["files"] = [f for f in data["files"] if f["role"] != "license"]
    with pytest.raises(ValidationError, match="licence"):
        HandoffBundle.model_validate(data)


def test_a_wrapped_bundle_may_have_no_licence_file_but_still_needs_a_model():
    data = bundle()
    data["producer"]["kit"] = "external"
    data["files"] = [f for f in data["files"] if f["role"] != "license"]
    data["instances"] = []
    data["clips"] = []
    assert HandoffBundle.model_validate(data).producer.kit == "external"
    data["files"] = []
    with pytest.raises(ValidationError):
        HandoffBundle.model_validate(data)


def test_exactly_one_model_file():
    data = bundle()
    data["files"].append({"role": "model", "path": "other.glb", "sha256": SHA})
    with pytest.raises(ValidationError, match="exactly one model"):
        HandoffBundle.model_validate(data)


def test_a_clip_cannot_point_at_an_unknown_instance():
    data = bundle()
    data["clips"][0]["instance_id"] = "ghost-01"
    with pytest.raises(ValidationError, match="unknown instances"):
        HandoffBundle.model_validate(data)


@pytest.mark.parametrize("path", ["../escape.glb", "/abs.glb", "a\\b.glb", "sub//x.glb"])
def test_a_bundle_path_never_escapes_its_folder(path):
    data = bundle()
    data["files"][0]["path"] = path
    with pytest.raises(ValidationError):
        HandoffBundle.model_validate(data)


def test_unknown_fields_and_duplicate_paths_are_refused():
    with pytest.raises(ValidationError):
        HandoffBundle.model_validate(bundle(surprise=1))
    data = bundle()
    data["files"][1]["path"] = data["files"][0]["path"]
    with pytest.raises(ValidationError, match="share a path"):
        HandoffBundle.model_validate(data)


def test_khronos_status_is_a_closed_list():
    with pytest.raises(ValidationError):
        HandoffBundle.model_validate(bundle(validation={"khronos": "probably fine"}))
