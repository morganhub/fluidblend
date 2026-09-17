import shutil

import pytest
from tests.conftest import make_request, note

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


def install_character(project):
    fixture = kit_root() / "fixtures/vitruvian/character.blend"
    if not fixture.exists():
        pytest.skip("not_run: generate the pinned Vitruvian fixture first")
    metadata = read_json(fixture.with_name("asset.json"))
    assert sha256_file(fixture) == metadata["sha256"]
    folder = project.root / "assets/characters/vitruvian/v001"
    folder.mkdir(parents=True)
    shutil.copy2(fixture, folder / "character.blend")
    shutil.copy2(kit_root() / "licenses/vitruvian.md", project.root / "licenses/vitruvian.md")
    manifest = {
        key: metadata[key]
        for key in ("asset_id", "version", "sha256", "license", "objects", "armature", "rig_profile")
    }
    manifest.update(
        blend_path="assets/characters/vitruvian/v001/character.blend", license_path="licenses/vitruvian.md"
    )
    atomic_write_json(folder / "asset.json", manifest)
    # Front camera for readable deformation views.
    shot = project.shot_manifest("shot010")
    shot.camera.location = [2.8, -4, 1.4]
    shot.camera.look_at = [0, 0, 0.9]
    shot.camera.focal_length_mm = 50
    atomic_write_json(project.root / "shots/shot010/shot.json", shot.model_dump())
    return "assets/characters/vitruvian/v001/asset.json"


@pytest.mark.acceptance(
    "B01", title="Versioned skinned Rigify character: semantic mapping and five deformation poses"
)
def test_B01_character_mapping_and_deformation(project):
    manifest = install_character(project)
    runner = TaskRunner(project)
    build = runner.run(
        make_request(
            "shot.build",
            "asset-build-001",
            target={"shot_id": "shot010"},
            parameters={"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]},
        )
    )
    assert build.exit_code == 0, build.result.model_dump()
    blend = project.root / next(a.path for a in build.result.artifacts if a.kind == "blend")
    source_hash = sha256_file(blend)
    target = {"shot_id": "shot010", "instance_id": "hero-01", "expected_revision": 1}
    inspection = runner.run(make_request("character.inspect", "character-inspect-001", target=target))
    assert inspection.exit_code == 0, inspection.result.model_dump()
    assert inspection.result.metrics["skinned"] and inspection.result.metrics["uninfluenced_vertices"] == 0
    report_path = next(
        a.path for a in inspection.result.artifacts if a.path.endswith("character-inspection.json")
    )
    mapping = runner.run(
        make_request("rig.map", "rig-map-001", target=target, parameters={"inspection_path": report_path})
    )
    assert mapping.exit_code == 0, mapping.result.model_dump()
    assert mapping.result.metrics["missing_controls"] == []
    profile_path = next(a.path for a in mapping.result.artifacts if a.path.endswith("rig-profile.json"))
    validation = runner.run(
        make_request(
            "rig.validate", "rig-validate-001", target=target, parameters={"profile_path": profile_path}
        )
    )
    assert validation.exit_code == 0, validation.result.model_dump()
    assert validation.result.metrics["technical_pass"] and validation.result.metrics["tested_poses"] == 5
    assert sha256_file(blend) == source_hash
    poses = project.root / next(a.path for a in validation.result.artifacts if a.kind == "frames")
    assert len(list(poses.glob("*.png"))) == 5
    broken = read_json(project.root / profile_path)
    broken["controls"]["left_hand_ik"] = None
    atomic_write_json(project.root / "animation/rig-maps/incomplete.json", broken)
    refused = runner.run(
        make_request(
            "rig.validate",
            "rig-incomplete-001",
            target=target,
            parameters={"profile_path": "animation/rig-maps/incomplete.json", "preview": False},
        )
    )
    assert refused.result.errors[0].code == "RIG_MAPPING_REQUIRED"
    assert sha256_file(blend) == source_hash
    duplicate = runner.run(
        make_request(
            "shot.build",
            "asset-duplicate-001",
            target={"shot_id": "shot010"},
            parameters={"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]},
        )
    )
    assert duplicate.result.errors[0].code == "SCENE_CONFLICT"
    appended = runner.run(
        make_request(
            "shot.build",
            "asset-append-001",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [{"manifest_path": manifest, "instance_id": "sidekick-01", "location": [2, 0, 0]}]
            },
        )
    )
    assert appended.exit_code == 0, appended.result.model_dump()
    both = runner.run(make_request("scene.inspect", "inspect-two-assets", target={"shot_id": "shot010"}))
    assert both.exit_code == 0 and both.result.metrics["armatures"] == 2
    assert sha256_file(blend) == source_hash
    note(
        "B01",
        "Vitruvian CC0, 37,436 influenced vertices, complete Rigify mapping; five finite deformation responses and PNG views; source hash unchanged; incomplete mapping refused; artistic review pending",
    )
