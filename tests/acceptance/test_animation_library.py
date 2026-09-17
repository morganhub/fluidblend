import pytest
from tests.acceptance.test_characters import install_character
from tests.conftest import make_request

from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender


def test_walk_contacts_are_measured_through_loop_and_apply(project):
    manifest = install_character(project)
    runner = TaskRunner(project)
    build = runner.run(
        make_request(
            "shot.build",
            "walk-build-001",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [{"manifest_path": manifest, "instance_id": "hero-01", "location": [1, 2, 0]}]
            },
        )
    )
    assert build.exit_code == 0, build.result.model_dump()
    target = {"shot_id": "shot010", "instance_id": "hero-01"}
    blocking = runner.run(
        make_request(
            "animation.create",
            "walk-blocking-001",
            target=target,
            parameters={"preset": "walk", "output_clip": "walk-blocking", "stage": "blocking"},
        )
    )
    assert blocking.result.errors[0].code == "VALIDATION_FAILED"
    assert not (project.root / "animation/clips/walk-blocking").exists()
    create = runner.run(
        make_request(
            "animation.create",
            "walk-create-001",
            target=target,
            parameters={"preset": "walk", "output_clip": "walk"},
        )
    )
    assert create.exit_code == 0, create.result.model_dump()
    clip = read_json(project.root / "animation/clips/walk/clip.json")
    assert clip["root_motion"] == "root_bone" and clip["stride_m"] == pytest.approx(0.6)
    assert [c["effector"] for c in clip["contacts"]] == ["left_foot", "right_foot"]
    slides = [m for m in clip["measurements"] if m["kind"] == "foot_slide"]
    assert len(slides) == 2 and all(
        m["passed"] and m["value"] <= 0.02 and m["space"] == "world" for m in slides
    )
    kinds = {m["kind"]: m for m in clip["measurements"]}
    assert kinds["loop_pose"]["passed"] is True
    # Seam velocity is reported with no tolerance: it must not read as a pass.
    assert kinds["loop_velocity"]["passed"] is None and kinds["loop_velocity"]["tolerance"] is None
    loop = runner.run(
        make_request(
            "animation.loop",
            "walk-loop-001",
            target={**target, "clip_id": "walk"},
            parameters={"output_clip": "walk-loop", "repetitions": 3},
        )
    )
    assert loop.exit_code == 0, loop.result.model_dump()
    apply = runner.run(
        make_request(
            "animation.apply",
            "walk-apply-001",
            target=target,
            parameters={"clip_id": "walk-loop", "start_frame": 10},
        )
    )
    assert apply.exit_code == 0, apply.result.model_dump()
    metrics = apply.result.metrics
    # Three cycles of two stance windows, each re-measured in the assembled scene.
    assert metrics["measured_contact_windows"] == 6 and metrics["contact_slide_max_m"] <= 0.02
    assert metrics["root_travel_m"] == pytest.approx(1.8, abs=0.02)


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
