import pytest
from tests.acceptance.test_characters import install_character
from tests.conftest import make_request

from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


def test_rigify_library_layers_loop_and_bake(project):
    manifest = install_character(project)
    runner = TaskRunner(project)
    build = runner.run(
        make_request(
            "shot.build",
            "library-build-001",
            target={"shot_id": "shot010"},
            parameters={"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]},
        )
    )
    assert build.exit_code == 0, build.result.model_dump()
    target = {"shot_id": "shot010", "instance_id": "hero-01"}
    for preset in ("idle_neutral", "turn", "look_at", "reach", "react"):
        create = runner.run(
            make_request(
                "animation.create",
                f"create-{preset}-001",
                target=target,
                parameters={"preset": preset, "output_clip": preset},
            )
        )
        assert create.exit_code == 0, create.result.model_dump()
        assert (project.root / f"animation/clips/{preset}/clip.json").exists()
        assert runner.run(
            make_request(
                "animation.create",
                f"create-{preset}-001",
                target=target,
                parameters={"preset": preset, "output_clip": preset},
            )
        ).replayed
    loop = runner.run(
        make_request(
            "animation.loop",
            "loop-idle-001",
            target={**target, "clip_id": "idle_neutral"},
            parameters={"output_clip": "idle-loop", "repetitions": 3},
        )
    )
    assert loop.exit_code == 0, loop.result.model_dump()
    for clip in ("idle-loop", "look_at"):
        apply = runner.run(
            make_request("animation.apply", f"apply-{clip}-001", target=target, parameters={"clip_id": clip})
        )
        assert apply.exit_code == 0, apply.result.model_dump()
    overlap = runner.run(
        make_request("animation.apply", "overlap-001", target=target, parameters={"clip_id": "idle_neutral"})
    )
    assert overlap.result.errors[0].code == "SCENE_CONFLICT"
    before = project.latest_work_blend("shot010")[1]
    digest = sha256_file(before)
    bake = runner.run(
        make_request(
            "animation.bake",
            "bake-001",
            target=target,
            parameters={"output_clip": "baked-idle", "frame_range": {"start": 1, "end_exclusive": 25}},
        )
    )
    assert bake.exit_code == 0, bake.result.model_dump()
    assert bake.result.metrics["channels"] > 0 and sha256_file(before) == digest
    clip = read_json(project.root / "animation/clips/baked-idle/clip.json")
    assert clip["source_sha256"] == sha256_file(project.root / clip["source_blend"])
