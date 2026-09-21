"""The bundle join, without Blender: what it reads, what it refuses, what it admits it does not know."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import make_request

from fluidblend import __version__
from fluidblend.contracts.common import Artifact, OperationResult, OperationStatus
from fluidblend.contracts.handoff import HandoffBundle
from fluidblend.contracts.operations import validate_request
from fluidblend.core.handoff import LicenceUnknown, build_bundle
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import load_project, scaffold_project

FPS = {"numerator": 24, "denominator": 1}


def export_report(**overrides):
    report = {
        "glb": "shot010-hero.glb",
        "bytes": 12,
        "settings": {"export_def_bones": True},
        "axis_convention": {
            "blender": {"up": "+Z", "forward": "-Y"},
            "gltf": {"up": "+Y", "forward": "+Z"},
        },
        "exported": {"armatures": {"rig": 188}, "actions": ["rig.walk"], "meshes": 1},
        "node_names": ["rig"],
        "instances": [
            {
                "instance_id": "hero-01",
                "asset_id": "vitruvian",
                "asset_version": 1,
                "kind": "character",
                "rig_profile": "rigify",
                "armature": "rig",
                "skinned": True,
                "baked": True,
                "export_def_bones": True,
                "bone_count": 188,
                "gltf_node_name": "rig",
                "grips": {},
                "animations": ["rig.walk"],
                "reference_pose": [{"bone": "DEF-spine", "head_m": [0.0, 0.0, 1.05]}],
            }
        ],
        "reimport": {"passed": True, "skeleton_fidelity": {"max_error_m": 3e-06}},
    }
    report.update(overrides)
    return report


def clip_index(clip_id="walk"):
    return {
        "schema_version": "1.0",
        "clip_id": clip_id,
        "action": f"rig.{clip_id}",
        "slot": "OBrig",
        "rig_profile": "rigify",
        "frame_range": {"start": 0, "end_exclusive": 96},
        "root_motion": "root_bone",
        "contacts": [],
        "events": [],
        "layer": "base",
        "owned_channels": [['pose.bones["root"].location', 0]],
        "loop": True,
        "stride_m": 0.6,
        "repetitions": 4,
        "measurements": [],
        "source_blend": "assets/characters/vitruvian/v001/character.blend",
        "source_sha256": "b" * 64,
        "manifest_path": "animation/clips/walk/clip.json",
        "manifest_sha256": "c" * 64,
    }


def asset_manifest(license_path="licenses/vitruvian.md"):
    return {
        "schema_version": "1.0",
        "asset_id": "vitruvian",
        "version": 1,
        "blend_path": "assets/characters/vitruvian/v001/character.blend",
        "sha256": "d" * 64,
        "license": "CC0-1.0",
        "license_path": license_path,
        "objects": ["rig", "body"],
        "kind": "character",
        "armature": "rig",
        "rig_profile": "rigify",
    }


@pytest.fixture
def scene(tmp_path: Path):
    """A project with one asset, one clip and a finished export sitting in an out/ folder."""
    root = tmp_path / "studio"
    scaffold_project(root, profile="game", project_id="demo-studio", game_engine="unreal")
    project = load_project(root)

    asset_dir = root / "assets" / "characters" / "vitruvian" / "v001"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "asset.json").write_text(json.dumps(asset_manifest()), encoding="utf-8")
    licence = root / "licenses" / "vitruvian.md"
    licence.parent.mkdir(parents=True, exist_ok=True)
    licence.write_text("# Vitruvian\n\nCC0-1.0, public domain.\n", encoding="utf-8")
    clips = root / "animation" / "clips" / "walk"
    clips.mkdir(parents=True, exist_ok=True)
    (clips / "clip.json").write_text(json.dumps(clip_index()), encoding="utf-8")

    out = tmp_path / "out"
    out.mkdir()
    glb = out / "shot010-hero.glb"
    glb.write_bytes(b"glTF\x02\x00\x00\x00fake")
    (out / "export-report.json").write_text(json.dumps(export_report()), encoding="utf-8")
    return project, out, glb


def run_build(scene, *, preset="unreal", report=None, result=None):
    project, out, glb = scene
    if report is not None:
        (out / "export-report.json").write_text(json.dumps(report), encoding="utf-8")
    payload = make_request(
        "game.export",
        "export-shot010-001",
        target={"shot_id": "shot010"},
        parameters={"output_name": "shot010-hero", "export_def_bones": True, "export_preset": preset},
    )
    request, params, _spec = validate_request(payload)
    result = result or OperationResult(
        operation_id=request.operation_id,
        operation=request.operation,
        task_id="task-001",
        status=OperationStatus.succeeded,
        artifacts=[Artifact(kind="glb", path=glb.name, sha256=sha256_file(glb), bytes=glb.stat().st_size)],
    )
    return build_bundle(
        root=project.root,
        request=request,
        parameters=params,
        out_dir=out,
        result=result,
        fps=project.manifest.fps,
        source_revision=7,
    )


def test_the_join_describes_the_instance_the_clip_and_the_licence(scene):
    _project, out, _glb = scene
    outcome = run_build(scene)
    bundle = outcome.bundle

    assert bundle.bundle_id == "export-shot010-001"
    assert bundle.producer.version == __version__ and bundle.producer.source_revision == 7
    assert bundle.producer.shot_id == "shot010" and bundle.units == "meters"

    instance = bundle.instances[0]
    assert instance.asset_id == "vitruvian" and instance.asset_version == 1
    assert instance.license == "CC0-1.0" and instance.license_file == "licenses/vitruvian.md"
    assert instance.bone_count == 188 and instance.skinned and instance.baked
    assert instance.reference_pose[0].bone == "DEF-spine"

    clip = bundle.clips[0]
    assert clip.clip_id == "walk" and clip.instance_id == "hero-01"
    assert clip.gltf_animation_name == "rig.walk" and clip.frame_range.count == 96
    assert clip.root_motion == "root_bone" and clip.stride_m == 0.6 and clip.loop

    # The licence really travels with the bundle, not just its name.
    assert (out / "licenses" / "vitruvian.md").is_file()
    assert HandoffBundle.model_validate(bundle.model_dump(mode="json")) == bundle


def test_every_declared_file_matches_the_bytes_on_disk(scene):
    _project, out, _glb = scene
    bundle = run_build(scene).bundle
    roles = {f.role for f in bundle.files}
    assert roles == {"model", "export_report", "license"}
    for entry in bundle.files:
        assert sha256_file(out / entry.path) == entry.sha256, entry.path
        assert (out / entry.path).stat().st_size == entry.bytes


def test_without_the_validator_khronos_is_not_run_and_never_passed(scene):
    bundle = run_build(scene).bundle
    assert bundle.validation.khronos == "not_run"
    assert bundle.file("khronos_report") is None
    assert bundle.validation.reimport_passed is True
    assert bundle.validation.skeleton_fidelity_max_error_m == pytest.approx(3e-06)


def test_a_failed_khronos_run_is_reported_as_failed(scene):
    _project, out, glb = scene
    (out / "gltf-validator.json").write_text('{"issues": {"numErrors": 2}}', encoding="utf-8")
    result = OperationResult(
        operation_id="export-shot010-001",
        operation="game.export",
        task_id="task-001",
        status=OperationStatus.succeeded,
        artifacts=[Artifact(kind="glb", path=glb.name, sha256=sha256_file(glb), bytes=glb.stat().st_size)],
        metrics={"khronos_validation": {"passed": False, "num_errors": 2}},
    )
    bundle = run_build(scene, result=result).bundle
    assert bundle.validation.khronos == "failed"
    assert bundle.file("khronos_report").path == "gltf-validator.json"


def test_the_unreal_preset_stops_on_an_unknown_licence(scene):
    project, _out, _glb = scene
    manifest = project.root / "assets" / "characters" / "vitruvian" / "v001" / "asset.json"
    manifest.write_text(json.dumps(asset_manifest(license_path="licenses/missing.md")), encoding="utf-8")
    with pytest.raises(LicenceUnknown) as raised:
        run_build(scene, preset="unreal")
    assert raised.value.instance_id == "hero-01"
    assert "missing" in raised.value.detail


def test_without_the_preset_an_unlicensed_instance_is_left_out_and_said_so(scene):
    project, _out, _glb = scene
    manifest = project.root / "assets" / "characters" / "vitruvian" / "v001" / "asset.json"
    manifest.write_text(json.dumps(asset_manifest(license_path="licenses/missing.md")), encoding="utf-8")
    outcome = run_build(scene, preset="none")
    # A bundle is a redistribution format: with no licence established, none is published at all.
    assert outcome.bundle is None
    assert any("unknown license" in w for w in outcome.warnings)
    assert any("never redistributes an asset without one" in w for w in outcome.warnings)


def test_an_unmatched_animation_is_reported_not_attributed(scene):
    report = export_report()
    report["exported"]["actions"] = ["rig.sprint"]
    outcome = run_build(scene, report=report)
    assert outcome.bundle.clips == []
    assert any("rig.sprint" in w and "could not be matched" in w for w in outcome.bundle.warnings)


def test_a_scene_built_before_060_falls_back_to_the_highest_version_and_warns(scene):
    report = export_report()
    report["instances"][0].pop("asset_version")
    outcome = run_build(scene, report=report)
    assert outcome.bundle.instances[0].asset_version == 1
    assert any("does not say which version" in w for w in outcome.bundle.warnings)


def test_a_skipped_reimport_is_admitted_as_a_limit(scene):
    report = export_report(reimport=None)
    bundle = run_build(scene, report=report).bundle
    assert bundle.validation.reimport_passed is None
    assert any("node names are unverified" in limit for limit in bundle.limits)


def test_a_renamed_node_becomes_a_limit_rather_than_a_silent_claim(scene):
    report = export_report()
    report["instances"][0]["gltf_node_name_verified"] = False
    bundle = run_build(scene, report=report).bundle
    assert any("glTF node name was not confirmed" in limit for limit in bundle.limits)


def test_a_bundle_needs_a_glb_artifact(scene):
    project, _out, _glb = scene
    result = OperationResult(
        operation_id="export-shot010-001",
        operation="game.export",
        task_id="task-001",
        status=OperationStatus.succeeded,
        artifacts=[],
    )
    with pytest.raises(ValueError, match="no GLB artifact"):
        run_build(scene, result=result)
    assert project.manifest.targets.game_engine == "unreal"


def test_the_clip_range_describes_the_glb_not_the_blender_scene(scene):
    """With slide_to_zero the exported animation starts at 0: that is the range a consumer measures."""
    clips = scene[0].root / "animation" / "clips" / "walk" / "clip.json"
    index = json.loads(clips.read_text(encoding="utf-8"))
    index["frame_range"] = {"start": 1, "end_exclusive": 49}
    clips.write_text(json.dumps(index), encoding="utf-8")

    report = export_report()
    report["settings"]["export_anim_slide_to_zero"] = True
    bundle = run_build(scene, report=report).bundle
    assert bundle.clips[0].frame_range.start == 0
    assert bundle.clips[0].frame_range.count == 48

    # Without it, the scene's own range is what the GLB carries, so it is kept as it is.
    report["settings"]["export_anim_slide_to_zero"] = False
    bundle = run_build(scene, report=report).bundle
    assert bundle.clips[0].frame_range.start == 1 and bundle.clips[0].frame_range.count == 48
