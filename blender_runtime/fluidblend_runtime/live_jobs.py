"""Cooperative live execution: the MCP call returns at once, a timer advances the operation.

Blender's main thread is released between steps, so the session stays usable, progress is published
and a cancellation can be acknowledged. The engine never treats a cancel as done without the
`cancel.ack.json` written here.
"""

from __future__ import annotations

import json
import os
import time

import bpy

from fluidblend_runtime.envelope import load_envelope
from fluidblend_runtime.result import write_json_atomic

TICK_S = 0.05
_job: dict | None = None


def _path(name: str) -> str:
    return os.path.join(_job["task_dir"], name)


def _progress(state: str, label: str) -> None:
    write_json_atomic(
        _path("progress.json"),
        {
            "task_id": _job["task_id"],
            "state": state,
            "step": _job["step"],
            "label": label,
            "updated_at": time.time(),
        },
    )


def start(request_path: str, result_path: str) -> dict:
    global _job
    if _job is not None:
        return {"started": False, "error": f"session busy with task {_job['task_id']}"}
    from fluidblend_runtime import envelope_steps

    envelope = load_envelope(request_path)
    _job = {
        "task_id": envelope["task_id"],
        "task_dir": envelope["context"]["task_dir"],
        "result_path": result_path,
        "request": envelope["request"],
        "steps": envelope_steps(envelope),
        "step": 0,
        "dirty_before": bpy.data.is_dirty,
    }
    _progress("queued", "queued")
    bpy.app.timers.register(_tick, first_interval=TICK_S, persistent=True)
    return {"started": True, "task_id": _job["task_id"]}


def _finish(result: dict) -> None:
    global _job
    write_json_atomic(_job["result_path"], result)
    _progress(result["status"], "finished")
    _job = None


def _cancelled_result() -> dict:
    request = _job["request"]
    modified = bpy.data.is_dirty and not _job["dirty_before"]
    return {
        "schema_version": "1.0",
        "operation_id": request["operation_id"],
        "operation": request["operation"],
        "task_id": _job["task_id"],
        "status": "cancelled",
        "changed_entities": [],
        "artifacts": [],
        "warnings": ["the open session was modified before the stop; revert it before retrying"]
        if modified
        else [],
        "errors": [],
        "metrics": {"cancelled_at_step": _job["step"], "session_modified": modified},
        "checkpoint_id": None,
        "new_revision": None,
        "next_safe_actions": [],
    }


def _tick():
    """One cooperative step per timer call; returning None ends the timer."""
    if _job is None:
        return None
    try:
        if os.path.exists(_path("cancel.request")):
            _job["steps"].close()
            result = _cancelled_result()
            # The acknowledgement is what makes the cancellation real for the engine.
            write_json_atomic(
                _path("cancel.ack.json"),
                {
                    "task_id": _job["task_id"],
                    "acknowledged_at": time.time(),
                    "cancelled_at_step": _job["step"],
                    "session_modified": result["metrics"]["session_modified"],
                    "nothing_saved": True,
                },
            )
            _finish(result)
            return None
        label = next(_job["steps"])
        _job["step"] += 1
        _progress("running", label)
        return TICK_S
    except StopIteration as done:
        _finish(done.value)
        return None
    except Exception as exc:  # noqa: BLE001 - a timer must never raise into Blender; report and stop
        request = _job["request"]
        failed = _cancelled_result()
        failed.update(
            status="failed",
            warnings=[],
            errors=[
                {
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                    "recovery": None,
                    "details": {"operation": request["operation"]},
                }
            ],
        )
        _finish(failed)
        return None


def describe() -> str:
    return json.dumps({"busy": _job is not None, "task_id": _job["task_id"] if _job else None})
