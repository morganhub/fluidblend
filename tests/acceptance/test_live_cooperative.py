"""Cooperative live execution: progress while Blender stays responsive, cancellation only on acknowledgement."""

from __future__ import annotations

import threading

import pytest
from tests.acceptance.test_live_mcp import _identity, live_project, live_ready  # noqa: F401 - fixtures
from tests.conftest import make_request, note

from fluidblend.core.tasks import TaskRunner

pytestmark = [pytest.mark.blender]


@pytest.mark.acceptance(
    "L09", title="Live: progress is reported and a cancellation is acknowledged by the session"
)
def test_live_cancel_is_acknowledged(live_project):  # noqa: F811
    _runner, blend, _session = live_project
    project = _runner.project
    # 200 idle cooperative steps (~10 s) before the operation touches anything.
    runner = TaskRunner(project, mode="live", test_hooks={"cooperative_wait_steps": 200})
    seen: list[dict] = []
    cancelled: dict = {}

    def on_progress(task, progress):
        seen.append(progress)
        if len(seen) == 1:
            # `task cancel` comes from another process in real use: no lock, only the task folder.
            threading.Thread(
                target=lambda: cancelled.update(TaskRunner(project).cancel(task.task_id)), daemon=True
            ).start()

    runner.on_live_progress = on_progress
    outcome = runner.run(make_request("scene.inspect", "live-cancel-001", target={"shot_id": "shot010"}))
    assert outcome.result.status == "cancelled", outcome.result.model_dump()
    assert outcome.task.status == "cancelled" and seen and seen[0]["state"] in ("queued", "running")
    assert outcome.result.metrics["session_modified"] is False
    for _ in range(50):
        if cancelled:
            break
        threading.Event().wait(0.2)
    assert cancelled["cancelled"] is True and cancelled["acknowledgement"]["nothing_saved"] is True
    events = [e["event"] for e in project.journal().events()]
    assert "live_cancel_acknowledged" in events
    assert project.latest_work_blend("shot010")[1] == blend
    # The session answered while the job was pending and is still usable afterwards.
    assert _identity(project)["is_dirty"] is False
    again = TaskRunner(project, mode="live").run(
        make_request("scene.inspect", "live-after-cancel", target={"shot_id": "shot010"})
    )
    assert again.exit_code == 0, again.result.model_dump()
    note(
        "L09",
        f"cancel requested after {seen[0]['step']} step(s); session wrote cancel.ack.json, task cancelled, nothing "
        "saved, session clean and reusable; without acknowledgement the state stays unknown (unit test)",
    )
