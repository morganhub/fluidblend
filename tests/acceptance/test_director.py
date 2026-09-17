"""Director panel (B06): the buttons run the same engine operations as the CLI, from a real GUI session."""

from __future__ import annotations

import time

import pytest
from tests.acceptance.test_adjustments import DRIFT
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import human_edit
from tests.acceptance.test_live_mcp import PORT, _identity, live_ready  # noqa: F401 - fixture
from tests.conftest import make_request, note
from tests.live_blender import launch_live_blender, port_open

from fluidblend.adapters import blender_live, client_config
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.tasks import TaskRunner

pytestmark = [pytest.mark.blender]

SETUP = (
    "import bpy\n"
    "d = bpy.context.window_manager.fluidblend_director\n"
    'd.instance_id = "hero-01"\n'
    'd.adjustment_id = "plant-left"\n'
    'd.effector = "left_foot"\n'
    "d.frame_start = 1\n"
    "d.frame_end_exclusive = 26\n"
)


@pytest.fixture
def director_session(project, blender_exe, live_ready):  # noqa: F811
    if port_open(PORT):
        pytest.skip(f"not_run: port {PORT} busy (another Blender/MCP session is running)")
    manifest = install_character(project)
    runner = TaskRunner(project)
    hero = {"shot_id": "shot010", "instance_id": "hero-01"}
    for operation, operation_id, target, parameters in (
        (
            "shot.build",
            "panel-build",
            {"shot_id": "shot010"},
            {"assets": [{"manifest_path": manifest, "instance_id": "hero-01"}]},
        ),
        ("animation.create", "panel-walk", hero, {"preset": "walk", "output_clip": "walk"}),
        ("animation.apply", "panel-walk-apply", hero, {"clip_id": "walk"}),
    ):
        outcome = runner.run(make_request(operation, operation_id, target=target, parameters=parameters))
        assert outcome.exit_code == 0, outcome.result.model_dump()
    human_edit(blender_exe, project.latest_work_blend("shot010")[1], DRIFT)
    runner.revisions.accept_external("shot:shot010")
    entry = client_config.mcp_server_entry(port=PORT)
    atomic_write_json(project.root / ".mcp.json", client_config.claude_mcp_json(None, "blender", entry))
    blend = project.latest_work_blend("shot010")[1]
    session = launch_live_blender(project.local.blender_executable or "", port=PORT, blend=str(blend))
    if session is None:
        pytest.skip("not_run: Blender GUI session with the MCP add-on did not come up")
    try:
        yield project, blend
    finally:
        session.stop()


def call(project, code):
    ok, payload = blender_live.mutate_for_test(blender_live.server_config_for(project), code)
    assert ok, payload
    return payload


def status(project):
    payload = call(project, "import bpy\nbpy.ops.fluidblend.director_status()\n")
    return blender_live.extract_marker(payload, "FLUIDBLEND_DIRECTOR=")


def settle(project, timeout_s=180):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        current = status(project)
        if not current["busy"] and not current["pending_preview"]:
            return current
        time.sleep(1.0)
    pytest.fail("the Director operation did not finish")


@pytest.mark.acceptance(
    "B06", title="Director panel: Preview / Apply / Revert run the engine, the session stays clean"
)
def test_B06_director_panel(director_session):
    project, blend = director_session
    before = _identity(project)
    source_hash = sha256_file(blend)

    call(project, SETUP + "bpy.ops.fluidblend.director_preview()\n")
    preview = settle(project)
    assert preview["last_kind"] == "preview" and preview["last_status"] == "succeeded", preview
    assert preview["before_m"] == pytest.approx(0.10, abs=0.005) and 0 <= preview["after_m"] <= 0.02
    assert preview["last_report"].endswith("adjustment-preview.json")
    assert (project.root / preview["last_report"]).is_file()
    after_preview = _identity(project)
    # The preview ran in the engine, not in the session: no edit, no dirty flag, no new version.
    assert after_preview["is_dirty"] is False
    assert after_preview["edit_generation"] == before["edit_generation"]
    assert project.latest_work_blend("shot010")[1] == blend

    drags = "".join(f"d.max_correction_m = {value}\n" for value in (0.11, 0.12, 0.13, 0.14, 0.2))
    call(project, SETUP + "d.auto_preview = True\n" + drags)
    debounced = settle(project)
    assert debounced["launched"] == preview["launched"] + 1, "five slider moves, one preview"
    assert _identity(project)["is_dirty"] is False
    call(project, SETUP + "d.auto_preview = False\n")

    call(project, SETUP + "bpy.ops.fluidblend.director_apply()\n")
    applied = settle(project)
    assert applied["last_status"] == "succeeded" and "opened" in applied["status"], applied
    version, published = project.latest_work_blend("shot010")
    assert published != blend and sha256_file(blend) == source_hash
    session = _identity(project)
    assert session["blend_path"].lower() == str(published).lower() and session["is_dirty"] is False
    tasks = [e for e in project.journal().events() if e.get("event") == "revision_updated"]
    assert tasks[-1]["path"].endswith(f"v{version:03d}/shot010.blend"), "same journal as the CLI"

    # Found by a human clicking the panel: a fix name already in the scene, then a session left on
    # an older version while the engine works on the latest one.
    launched = status(project)["launched"]
    again = blender_live.mutate_for_test(
        blender_live.server_config_for(project), SETUP + "bpy.ops.fluidblend.director_apply()\n"
    )[1]
    assert "already applied" in status(project)["status"], again
    call(project, f"import bpy\nbpy.ops.fluidblend.open_file(filepath={str(blend)!r})\n")
    blender_live.mutate_for_test(
        blender_live.server_config_for(project), SETUP + "bpy.ops.fluidblend.director_preview()\n"
    )
    stale = status(project)
    assert "not the latest work version" in stale["status"] and stale["launched"] == launched
    call(project, "import bpy\nbpy.ops.fluidblend.director_open_latest()\n")
    assert _identity(project)["blend_path"].lower() == str(published).lower()

    call(project, SETUP + "bpy.ops.fluidblend.director_revert()\n")
    reverted = settle(project)
    assert reverted["last_status"] == "succeeded" and reverted["before_m"] == pytest.approx(0.10, abs=0.005)
    assert project.latest_work_blend("shot010")[0] == version + 1

    # As in L03: an interactive edit pushes an undo step, which is what flags the file as unsaved.
    call(
        project,
        'import bpy\nbpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name = "artist-cube"\n'
        "bpy.ops.ed.undo_push(message='manual edit')\n",
    )
    launched = status(project)["launched"]
    payload = blender_live.mutate_for_test(
        blender_live.server_config_for(project), SETUP + "bpy.ops.fluidblend.director_apply()\n"
    )[1]
    refused = status(project)
    assert refused["launched"] == launched and "unsaved changes" in refused["status"], payload
    assert "PRESERVED True" in call(
        project, 'import bpy\nprint("PRESERVED", "artist-cube" in bpy.data.objects)\n'
    )
    note(
        "B06",
        f"panel preview {preview['before_m'] * 1000:.1f} -> {preview['after_m'] * 1000:.2f} mm with the session "
        "untouched (same edit generation, not dirty); five slider moves -> one debounced preview; Apply and Revert "
        "published new revisions through the engine journal and reopened the session; Apply refused on unsaved "
        "changes, artist object preserved; driven through the panel operators, no human clicked the UI",
    )
