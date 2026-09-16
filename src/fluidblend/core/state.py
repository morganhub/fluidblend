"""Compact state rebuilt from the journal: tasks, idempotency ledger, publications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.contracts.common import OperationStatus
from fluidblend.contracts.tasks import TaskRecord
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import now_iso
from fluidblend.core.journal import Journal

TERMINAL = {
    OperationStatus.succeeded,
    OperationStatus.failed,
    OperationStatus.cancelled,
    OperationStatus.blocked,
}


def rebuild_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "rebuilt_at": now_iso(),
        "event_count": len(events),
        "corrupt_lines": [],
        "tasks": {},
        "ledger": {},
        "published": [],
        "plans": {},
        "initialized_at": None,
    }
    for event in events:
        kind = event.get("event")
        if kind == "journal_corrupt_line":
            state["corrupt_lines"].append(event)
        elif kind == "project_initialized":
            state["initialized_at"] = state["initialized_at"] or event.get("ts")
        elif kind == "task_updated":
            record = event.get("task")
            if isinstance(record, dict) and record.get("task_id"):
                state["tasks"][record["task_id"]] = record
                state["ledger"][record["operation_id"]] = {
                    "task_id": record["task_id"],
                    "status": record["status"],
                    "fingerprint": record["fingerprint"],
                    "expected_revision": record.get("expected_revision"),
                    "new_revision": record.get("new_revision"),
                    "result_path": record.get("result_path"),
                    "updated_at": record.get("updated_at"),
                }
        elif kind == "artifact_published":
            state["published"].append({k: v for k, v in event.items() if k != "event"})
        elif kind == "plan_created":
            state["plans"][event.get("operation_id")] = event.get("path")
    return state


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.state_dir = root / "state"
        self.journal = Journal(self.state_dir / "journal.jsonl")
        self.snapshot_path = self.state_dir / "state.json"

    def rebuild(self, *, save: bool = True) -> dict[str, Any]:
        state = rebuild_state(self.journal.events())
        if save:
            atomic_write_json(self.snapshot_path, state)
        return state

    def task(self, task_id: str) -> TaskRecord | None:
        record = self.rebuild(save=False)["tasks"].get(task_id)
        return TaskRecord.model_validate(record) if record else None

    def tasks(self) -> list[TaskRecord]:
        records = self.rebuild(save=False)["tasks"].values()
        return [TaskRecord.model_validate(r) for r in records]

    def ledger_entry(self, operation_id: str) -> dict[str, Any] | None:
        return self.rebuild(save=False)["ledger"].get(operation_id)

    def upsert_task(self, record: TaskRecord) -> None:
        record.updated_at = now_iso()
        self.journal.append("task_updated", task=record.model_dump(mode="json"))
        self.rebuild(save=True)

    def unfinished_tasks(self) -> list[TaskRecord]:
        return [t for t in self.tasks() if t.status not in TERMINAL]
