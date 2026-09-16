"""P0 acceptance (A03-A11) on the real locked Blender. Each scenario writes its evidence into the temporary project."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import make_request, note

from fluidblend.adapters import blender_batch
from fluidblend.adapters import ffmpeg as ff
from fluidblend.adapters import gltf_validator as gltfv
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import Project, load_project
from fluidblend.core.revisions import RevisionStore
from fluidblend.core.tasks import TaskRunner

pytestmark = [pytest.mark.blender]

BUILD = make_request(
    "scene.build", "build-shot010-001", target={"shot_id": "shot010"}, parameters={"frames": 240}
)


def _build(project: Project, runner: TaskRunner | None = None) -> TaskRunner:
    runner = runner or TaskRunner(project)
    outcome = runner.run(BUILD)
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    return runner


def _inspect(runner: TaskRunner, operation_id: str) -> dict:
    outcome = runner.run(
        make_request(
            "scene.inspect",
            operation_id,
            target={"shot_id": "shot010"},
            parameters={"include_actions": True, "include_bones": True},
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    report = next(a for a in outcome.result.artifacts if a.path.endswith("inspect.json"))
    return read_json(runner.project.root / report.path)


@pytest.mark.acceptance(
    "A04", title="Build two simple articulated characters and one prop (240 frames at 24 fps)"
)
def test_A04_build_two_characters_and_prop(project: Project):
    runner = _build(project)
    blend = project.root / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    assert blend.exists()
    summary = _inspect(runner, "inspect-after-build")
    assert summary["scene"]["fps"] == 24 and summary["scene"]["frame_count_inclusive"] == 240
    assert summary["counts"]["armatures"] == 2 and summary["counts"]["actions"] == 2
    instances = {i["instance_id"]: i["kind"] for i in summary["instances"]}
    assert instances == {"hero-01": "character", "sidekick-01": "character", "lantern-01": "prop"}
    for action in summary["actions"]:
        assert action["pose_key_extent"] == [
            1.0 + (12.0 if "sidekick" in action["name"] else 0.0),
            49.0 + (12.0 if "sidekick" in action["name"] else 0.0),
        ]
        assert action["channelbags"][0]["cyclic_fcurves"] >= 10
        assert len(action["pose_markers"]) == 2
    assert summary["identity"]["project_id"] == "demo-studio" and summary["identity"]["shot_id"] == "shot010"
    assert RevisionStore(project.root).get("shot:shot010").revision == 1
    bone_counts = sorted(o["bone_count"] for o in summary["objects"] if o["type"] == "ARMATURE")
    assert bone_counts == [18, 18]
    note(
        "A04",
        f"{summary['counts']['objects']} objects, 2 armatures of 18 bones, cyclic slotted Actions, file reopened by scene.inspect",
    )


@pytest.mark.acceptance("A05", title="Re-run the same operation after a lost response")
def test_A05_replay_same_operation_id(project: Project):
    runner = _build(project)
    first = runner.run(BUILD)
    assert first.replayed and first.exit_code == exit_codes.OK
    versions = project.work_versions("shot010")
    assert [v for v, _ in versions] == [1], "no duplicated version"
    summary = _inspect(runner, "inspect-after-replay")
    assert summary["counts"]["armatures"] == 2 and summary["counts"]["actions"] == 2
    conflict = runner.run({**BUILD, "parameters": {"frames": 120}})
    assert conflict.exit_code == exit_codes.CONFLICT and conflict.result.errors[0].code == "SCENE_CONFLICT"
    note(
        "A05",
        "idempotent replay (same task_id, a single v001); different parameters -> SCENE_CONFLICT exit 3",
    )


@pytest.mark.acceptance("A06", title="Interrupt the worker after an output is created but before commit")
def test_A06_interrupted_worker_reconciles_without_loss(project: Project):
    runner = _build(project)
    source = project.root / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    source_hash = sha256_file(source)
    crashing = TaskRunner(project, test_hooks={"crash_after_output": True})
    request = make_request(
        "animation.retime",
        "retime-crash-001",
        target={"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk", "expected_revision": 1},
        parameters={"duration_scale": 1.5, "output_variant": "walk-crash", "preview_samples": 0},
    )
    outcome = crashing.run(request)
    assert outcome.exit_code == exit_codes.UNKNOWN_STATE and outcome.result.status == "unknown"
    task_id = outcome.result.task_id
    assert task_id and runner.state.task(task_id).status == "unknown"
    assert sha256_file(source) == source_hash, "the source was not touched"
    assert project.work_versions("shot010")[-1][0] == 1, "nothing published"
    blocked = runner.run(request)
    assert blocked.exit_code == exit_codes.UNKNOWN_STATE, "a new attempt requires reconciliation"
    report = runner.reconcile(task_id)
    assert report["status"] == "failed" and any("shot010.blend" in p for p in report["partial_effects"])
    retry = runner.run(request)
    assert retry.exit_code == exit_codes.OK and retry.result.new_revision == 2
    assert [v for v, _ in project.work_versions("shot010")] == [1, 2]
    assert sha256_file(source) == source_hash
    note(
        "A06",
        "worker killed after the outputs were written -> unknown state (exit 5); reconcile -> failed + partial effects; re-run with the same operation_id -> a single v002",
    )


@pytest.mark.acceptance("A07", title="Manually modify a protected object between two operations")
def test_A07_manual_change_detected_and_preserved(project: Project):
    runner = _build(project)
    source = project.root / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    with source.open("ab") as handle:
        handle.write(b"\n# edited by a human in Blender\n")
    edited_hash = sha256_file(source)
    request = make_request(
        "animation.retime",
        "retime-after-edit",
        target={"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk", "expected_revision": 1},
        parameters={"duration_scale": 1.2, "output_variant": "walk-slower-v001", "preview_samples": 0},
    )
    outcome = runner.run(request)
    assert outcome.exit_code == exit_codes.CONFLICT and outcome.result.errors[0].code == "SCENE_CONFLICT"
    assert outcome.result.errors[0].details["observed_sha256"] == edited_hash
    assert sha256_file(source) == edited_hash, "the manual change is preserved"
    assert "revision accept" in (outcome.result.errors[0].recovery or "")
    accepted = runner.revisions.accept_external("shot:shot010")
    assert accepted.revision == 2
    stale = runner.run(request)
    assert stale.exit_code == exit_codes.CONFLICT and "revision_mismatch" in stale.result.errors[0].message
    note(
        "A07",
        "hash mismatch -> SCENE_CONFLICT (exit 3), file preserved; `revision accept` -> revision 2; stale expected_revision=1 -> conflict",
    )


@pytest.mark.acceptance("A08", title="Slow down an animation on a variant")
def test_A08_retime_on_variant_keeps_source(project: Project):
    runner = _build(project)
    source = project.root / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    source_hash = sha256_file(source)
    outcome = runner.run(
        make_request(
            "animation.retime",
            "retime-shot010-hero-001",
            target={
                "shot_id": "shot010",
                "instance_id": "hero-01",
                "clip_id": "walk",
                "expected_revision": 1,
            },
            parameters={
                "duration_scale": 1.2,
                "preserve_contact_markers": True,
                "output_variant": "walk-slower-v001",
                "preview_samples": 6,
            },
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    metrics = outcome.result.metrics
    assert metrics["duration_before_frames"] == 48.0
    assert abs(metrics["duration_after_frames"] - 57.6) < 0.01
    assert (
        metrics["markers_before"] == metrics["markers_after"] == 2 and metrics["source_action_intact"] is True
    )
    assert outcome.result.new_revision == 2 and outcome.result.checkpoint_id
    assert sha256_file(source) == source_hash
    before = [a for a in outcome.result.artifacts if a.kind == "frames" and a.metrics.get("role") == "before"]
    after = [a for a in outcome.result.artifacts if a.kind == "frames" and a.metrics.get("role") == "after"]
    assert (
        before
        and after
        and (project.root / before[0].path).exists()
        and len(list((project.root / after[0].path).glob("*.png"))) == 6
    )
    report = read_json(
        project.root / next(a.path for a in outcome.result.artifacts if a.path.endswith("retime-report.json"))
    )
    assert [m["frame"] for m in report["after"]["markers"]] == [1, 30]
    note(
        "A08",
        "48 -> 57.6 frames (x1.2), contact markers 1/25 -> 1/30, source v001 untouched (hash), 6 before/after frames",
    )


@pytest.mark.acceptance("A09", title="Render then assemble the preview")
@pytest.mark.slow
def test_A09_preview_frames_and_video_proof(project: Project):
    runner = _build(project)
    outcome = runner.run(
        make_request(
            "shot.preview",
            "preview-shot010-001",
            target={"shot_id": "shot010"},
            parameters={"engine": "WORKBENCH", "label": "blocking"},
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    metrics = outcome.result.metrics
    assert (
        metrics["frames_expected"] == 240
        and metrics["frames_produced"] == 240
        and metrics["frames_missing"] == 0
    )
    frames = next(a for a in outcome.result.artifacts if a.kind == "frames")
    assert len(list((project.root / frames.path).glob("frame_*.png"))) == 240
    if not ff.find_tool("ffprobe", project.local.ffprobe_executable):
        note("A09", "ffmpeg missing: 240 frames proven, video not_run")
        pytest.skip("not_run: ffmpeg/ffprobe missing for the video part")
    assert metrics["video_frames"] == 240 and metrics["video_frame_rate_ok"] is True
    probe = read_json(
        project.root / next(a.path for a in outcome.result.artifacts if a.path.endswith("ffprobe.json"))
    )
    assert (
        probe["video"]["r_frame_rate"] == "24/1"
        and probe["video"]["pix_fmt"] == "yuv420p"
        and abs(probe["duration_s"] - 10.0) < 0.05
    )
    validate = runner.run(
        make_request("shot.validate", "validate-shot010-001", target={"shot_id": "shot010"})
    )
    assert validate.exit_code == exit_codes.OK and validate.result.metrics["technical_pass"] is True
    note(
        "A09",
        f"240/240 Workbench PNG in {metrics['render_seconds']} s, MP4 24/1 yuv420p, ffprobe nb_read_frames=240, 10 s duration, shot.validate technical_pass",
    )


@pytest.mark.acceptance("A10", title="Export an animation as GLB")
def test_A10_export_glb_validate_and_reimport(project: Project):
    runner = _build(project)
    outcome = runner.run(
        make_request(
            "game.export",
            "export-shot010-001",
            target={"shot_id": "shot010"},
            parameters={"output_name": "shot010-characters"},
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    glb = next(a for a in outcome.result.artifacts if a.kind == "glb")
    path = project.root / glb.path
    assert path.exists() and path.read_bytes()[:4] == b"glTF"
    assert outcome.result.metrics["reimport_passed"] is True and outcome.result.metrics["actions"] == 2
    report = read_json(
        project.root / next(a.path for a in outcome.result.artifacts if a.path.endswith("export-report.json"))
    )
    assert report["reimport"]["checks"] == {
        "armature_count": True,
        "bone_counts": True,
        "mesh_count": True,
        "animations_present": True,
    }
    assert report["settings"]["export_yup"] is True and report["axis_convention"]["gltf"]["up"] == "+Y"
    if not gltfv.find_validator(project.local.gltf_validator_executable):
        note(
            "A10",
            "GLB written and re-imported (2 armatures, 2 animations); Khronos validation not_run (gltf_validator missing)",
        )
        pytest.skip(
            "not_run: gltf_validator missing - a Blender re-import alone is not enough to declare the acceptance validated"
        )
    khronos = outcome.result.metrics["khronos_validation"]
    assert khronos["passed"] is True and khronos["num_errors"] == 0
    note(
        "A10",
        f"Khronos {khronos['validator_version']}: 0 error, {khronos['num_warnings']} warning(s); consistent Blender re-import",
    )


@pytest.mark.acceptance("A11", title="Run without network after an approved preparation")
def test_A11_offline_execution(project: Project):
    cmd = blender_batch.build_command("blender.exe", Path("r.json"), Path("res.json"), "task-x")
    assert "--offline-mode" in cmd and "--factory-startup" in cmd and "--background" in cmd
    runner = _build(project)
    task = runner.state.tasks()[0]
    assert task.worker is not None and task.worker.task_marker == task.task_id
    stdout = (project.root / "state" / "tasks" / task.task_id / "blender.stdout.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "FLUIDBLEND_RESULT" in stdout
    note(
        "A11",
        "worker launched with --offline-mode (Blender network disabled), no provider enabled, scene produced without any download",
    )


@pytest.mark.acceptance("A03", title="Inspect the scene through the configured MCP")
def test_A03_live_mcp_inspection(project: Project, blender_exe: str):
    """Ephemeral GUI session + MCP add-on + `uvx mcp-for-blender` server: read-only (list_tools, get_scene_info)."""
    import shutil

    from tests.live_blender import launch_live_blender

    from fluidblend.adapters import client_config
    from fluidblend.adapters.mcp_client import probe_server
    from fluidblend.core.atomic import atomic_write_json

    addon = client_config.blender_mcp_addon_installed()
    if not addon["installed"]:
        note(
            "A03",
            "MCP for Blender add-on not installed: not_run (the MCP client is unit-tested against a fake server)",
        )
        pytest.skip("not_run: MCP add-on missing (installation to be approved)")
    if not shutil.which("uvx"):
        pytest.skip("not_run: uvx missing")
    port = 9876  # add-on default port (automatic start on load)
    entry = client_config.mcp_server_entry(port=port)
    atomic_write_json(project.root / ".mcp.json", client_config.claude_mcp_json(None, "blender", entry))
    servers = [
        s for s in client_config.configured_servers(project_root=project.root) if s["name"] == "blender"
    ]
    assert servers and servers[0]["client"] == "claude-code:project"
    try:
        live = launch_live_blender(blender_exe, port=port)
    except RuntimeError as exc:
        note("A03", f"{exc}: not_run (close the existing Blender/MCP session or free the port)")
        pytest.skip(f"not_run: {exc}")
    if live is None:
        note("A03", "Blender GUI did not open the MCP socket in time: not_run")
        pytest.skip("not_run: Blender GUI session with the MCP add-on unavailable")
    try:
        report = probe_server(
            entry["command"], entry["args"], {**entry["env"]}, startup_timeout_s=120, call_timeout_s=60
        )
    finally:
        live.stop()
    assert report["errors"] == [], report
    assert "get_scene_info" in report["tools"] and "execute_blender_code" in report["tools"]
    assert report["scene_info"] and report["scene_info"]["is_error"] is False
    assert len(report["tools"]) >= 20
    note(
        "A03",
        f"{len(report['tools'])} tools advertised by {report.get('server', {}).get('name')}; get_scene_info read without mutation; GUI session started and stopped by the test (port {port})",
    )


def test_budget_timeout_marks_unknown_and_reconciles(project: Project):
    runner = _build(project)
    slow = TaskRunner(project, test_hooks={"sleep_before_result_s": 20, "timeout_s": 6})
    outcome = slow.run(make_request("scene.inspect", "inspect-slow", target={"shot_id": "shot010"}))
    assert (
        outcome.exit_code == exit_codes.UNKNOWN_STATE
        and outcome.result.errors[0].code == "TIMEOUT_UNKNOWN_STATE"
    )
    report = runner.reconcile(outcome.result.task_id)
    assert report["status"] == "failed"
    assert load_project(project.root) is not None
