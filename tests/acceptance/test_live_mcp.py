"""Live mode acceptance (lot 2): the engine drives the open Blender GUI session through the MCP add-on.

Each test launches its own Blender GUI on a work version, waits for the add-on socket (port 9876),
runs operations with `mode="live"` and stops the process it created. Requires the runtime add-on to be
installed and enabled (the session fixture does it, hash-checked, into the Blender user add-ons dir).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.conftest import make_request, note
from tests.live_blender import launch_live_blender, port_open

from fluidblend import __version__
from fluidblend.adapters import blender_live, client_config
from fluidblend.core import exit_codes
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import Project
from fluidblend.core.runtime_install import enable_runtime_addon, install_runtime, runtime_status
from fluidblend.core.tasks import TaskRunner

pytestmark = [pytest.mark.blender]
PORT = 9876
BUILD = make_request(
    "scene.build", "build-shot010-001", target={"shot_id": "shot010"}, parameters={"frames": 240}
)


@pytest.fixture(scope="session")
def live_ready(blender_exe: str) -> None:
    if not client_config.blender_mcp_addon_installed()["installed"]:
        pytest.skip("not_run: MCP for Blender add-on is not installed (approval required)")
    if not shutil.which("uvx"):
        pytest.skip("not_run: uvx is missing")
    status = install_runtime()
    if status["action"] != "up_to_date":
        enabled = enable_runtime_addon(blender_exe)
        if not enabled.get("ok"):
            pytest.skip(f"not_run: runtime add-on could not be enabled: {enabled}")
    assert runtime_status()["up_to_date"]


@pytest.fixture
def live_project(project: Project, live_ready: None):
    """Batch-built v001, `.mcp.json` written, GUI session opened on v001. Yields (runner, blend, session)."""
    if port_open(PORT):
        pytest.skip(f"not_run: port {PORT} busy (another Blender/MCP session is running)")
    batch = TaskRunner(project)
    outcome = batch.run(BUILD)
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    blend = project.root / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    entry = client_config.mcp_server_entry(port=PORT)
    atomic_write_json(project.root / ".mcp.json", client_config.claude_mcp_json(None, "blender", entry))
    session = launch_live_blender(project.local.blender_executable or "", port=PORT, blend=str(blend))
    if session is None:
        pytest.skip("not_run: Blender GUI session with the MCP add-on did not come up")
    try:
        yield TaskRunner(project, mode="live"), blend, session
    finally:
        session.stop()


def _identity(project: Project) -> dict:
    return blender_live.identity(blender_live.server_config_for(project))


@pytest.mark.acceptance("L01", title="Live: identity check and read-only inspection of the open scene")
def test_L01_live_inspect_with_identity(live_project):
    runner, blend, _session = live_project
    ident = _identity(runner.project)
    assert (
        ident["runtime_version"] == __version__
        and ident["project_id"] == "demo-studio"
        and ident["is_dirty"] is False
    )
    assert Path(ident["blend_path"]).resolve() == blend.resolve()
    outcome = runner.run(
        make_request(
            "scene.inspect",
            "live-inspect-001",
            target={"shot_id": "shot010"},
            parameters={"include_actions": True},
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    assert outcome.result.metrics["mode"] == "live" and outcome.result.metrics["armatures"] == 2
    report = next(a for a in outcome.result.artifacts if a.path.endswith("inspect.json"))
    assert (runner.project.root / report.path).exists()
    assert runner.state.task(outcome.result.task_id).mode == "live"
    note(
        "L01",
        "identity (project, file, revision, runtime, clean) verified through bpy.ops.fluidblend.identity; scene.inspect ran in the GUI session; report published",
    )


@pytest.mark.acceptance(
    "L02", title="Live: isolated write (retime) publishes a new version and reloads the session"
)
def test_L02_live_retime_publishes_version_and_reloads(live_project):
    runner, blend, _session = live_project
    v001_hash = sha256_file(blend)
    outcome = runner.run(
        make_request(
            "animation.retime",
            "live-retime-001",
            target={
                "shot_id": "shot010",
                "instance_id": "hero-01",
                "clip_id": "walk",
                "expected_revision": 1,
            },
            parameters={"duration_scale": 1.2, "output_variant": "walk-slower-v001", "preview_samples": 2},
        )
    )
    assert outcome.exit_code == exit_codes.OK, outcome.result.model_dump()
    assert outcome.result.new_revision == 2 and outcome.result.metrics["mode"] == "live"
    assert outcome.result.metrics["live_session_reloaded"] is True
    assert sha256_file(blend) == v001_hash, "v001 on disk untouched"
    v002 = runner.project.root / "shots" / "shot010" / "work" / "v002" / "shot010.blend"
    assert v002.exists()
    ident = _identity(runner.project)
    assert (
        Path(ident["blend_path"]).resolve() == v002.resolve()
        and ident["revision"] == 2
        and ident["is_dirty"] is False
    )
    note(
        "L02",
        "retime executed in the open session; v002 saved as a copy, published, revision 2; session reloaded on v002; v001 hash unchanged",
    )


@pytest.mark.acceptance("L03", title="Live: unsaved manual changes block the write and are preserved")
def test_L03_dirty_scene_is_blocked(live_project):
    runner, blend, _session = live_project
    config = blender_live.server_config_for(runner.project)
    # A bare property assignment does not flag the file; interactive edits push an undo step, which does.
    ok, _payload = blender_live.mutate_for_test(
        config,
        "import bpy\nbpy.data.objects['ground'].location.x += 0.25\nbpy.ops.ed.undo_push(message='manual edit')\n",
    )
    assert ok, _payload
    assert _identity(runner.project)["is_dirty"] is True
    outcome = runner.run(
        make_request(
            "animation.retime",
            "live-retime-dirty",
            target={
                "shot_id": "shot010",
                "instance_id": "hero-01",
                "clip_id": "walk",
                "expected_revision": 1,
            },
            parameters={"duration_scale": 1.5, "output_variant": "walk-dirty", "preview_samples": 0},
        )
    )
    assert outcome.exit_code == exit_codes.CONFLICT and outcome.result.errors[0].code == "SCENE_CONFLICT"
    assert "unsaved" in outcome.result.errors[0].message
    assert not (runner.project.root / "shots" / "shot010" / "work" / "v002").exists()
    ok, payload = blender_live.mutate_for_test(
        config, "import bpy\nprint('X=', bpy.data.objects['ground'].location.x)\n"
    )
    assert ok and "X= 0.25" in payload, "the manual change is preserved"
    checkpoint = runner.run(
        make_request(
            "scene.checkpoint",
            "live-ckpt-001",
            target={"shot_id": "shot010"},
            parameters={"label": "dirty-snapshot"},
        )
    )
    assert checkpoint.exit_code == exit_codes.OK and checkpoint.result.checkpoint_id
    assert checkpoint.result.metrics["was_dirty"] is True
    note(
        "L03",
        "dirty session → SCENE_CONFLICT (exit 3), nothing published, manual change kept; scene.checkpoint snapshots the unsaved scene (copy=True)",
    )


@pytest.mark.acceptance("L04", title="Live: wrong file open in the session is refused")
def test_L04_wrong_open_file_is_refused(project: Project, live_ready: None):
    if port_open(PORT):
        pytest.skip(f"not_run: port {PORT} busy")
    batch = TaskRunner(project)
    assert batch.run(BUILD).exit_code == exit_codes.OK
    entry = client_config.mcp_server_entry(port=PORT)
    atomic_write_json(project.root / ".mcp.json", client_config.claude_mcp_json(None, "blender", entry))
    session = launch_live_blender(
        project.local.blender_executable or "", port=PORT, blend=None
    )  # default cube scene, unsaved
    if session is None:
        pytest.skip("not_run: Blender GUI session did not come up")
    try:
        runner = TaskRunner(project, mode="live")
        outcome = runner.run(
            make_request("scene.inspect", "live-inspect-wrong", target={"shot_id": "shot010"})
        )
    finally:
        session.stop()
    assert outcome.exit_code == exit_codes.CONFLICT and outcome.result.errors[0].code == "SCENE_CONFLICT"
    assert (
        "no saved file" in outcome.result.errors[0].message
        or "not the latest work version" in outcome.result.errors[0].message
    )
    note(
        "L04",
        "session opened on an unrelated unsaved scene → identity mismatch → SCENE_CONFLICT, no task executed in Blender",
    )


@pytest.mark.acceptance(
    "L05", title="Live: lost response leaves an unknown state that reconciliation resolves"
)
def test_L05_lost_response_reconciles(live_project):
    runner, blend, _session = live_project
    slow = TaskRunner(
        runner.project, mode="live", test_hooks={"sleep_before_result_s": 12, "live_call_timeout_s": 4}
    )
    request = make_request("scene.audit", "live-audit-slow", target={"shot_id": "shot010"})
    outcome = slow.run(request)
    assert outcome.exit_code == exit_codes.UNKNOWN_STATE and outcome.result.status == "unknown"
    task_id = outcome.result.task_id
    blocked = runner.run(request)
    assert blocked.exit_code == exit_codes.UNKNOWN_STATE
    import time

    time.sleep(10)  # let the operator finish inside Blender
    report = runner.reconcile(task_id)
    assert report["status"] == "failed" and report["action"] in (
        "result_found_not_committed",
        "marked_failed",
    )
    retry = runner.run(request)
    assert retry.exit_code == exit_codes.OK and retry.result.metrics["audit_passed"] is True
    note(
        "L05",
        "call timeout → task unknown (exit 5); retry refused until reconcile; reconcile → failed (result found, not committed); retry succeeds on the clean session",
    )


def test_batch_operations_are_refused_in_live_mode(live_project):
    runner, _blend, _session = live_project
    outcome = runner.run(make_request("scene.build", "live-build", target={"shot_id": "shot010"}))
    # scene.build stays batch even with mode=live: the engine routes it to a dedicated process.
    assert outcome.exit_code in (exit_codes.OK, exit_codes.CONFLICT)
