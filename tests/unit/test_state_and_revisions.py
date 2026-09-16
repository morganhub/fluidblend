from __future__ import annotations

from pathlib import Path

import pytest

from fluidblend.contracts.common import OperationStatus
from fluidblend.contracts.tasks import TaskRecord
from fluidblend.core.checkpoints import create_file_checkpoint, list_checkpoints
from fluidblend.core.hashing import now_iso
from fluidblend.core.journal import Journal
from fluidblend.core.locks import LockBusy, ProjectLocks
from fluidblend.core.revisions import RevisionStore
from fluidblend.core.state import StateStore, rebuild_state


def _task(task_id: str, operation_id: str, status: OperationStatus, fingerprint: str = "fp") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        operation_id=operation_id,
        operation="scene.build",
        project_id="demo",
        status=status,
        fingerprint=fingerprint,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


def test_journal_append_and_redaction(tmp_path: Path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append("test", api_key="SECRET", nested={"token": "x", "ok": 1})
    events = journal.events()
    assert (
        events[0]["api_key"] == "***"
        and events[0]["nested"]["token"] == "***"
        and events[0]["nested"]["ok"] == 1
    )
    assert "SECRET" not in (tmp_path / "journal.jsonl").read_text(encoding="utf-8")


def test_state_rebuild_from_journal_and_corrupt_line(tmp_path: Path):
    store = StateStore(tmp_path)
    store.upsert_task(_task("t1", "op-1", OperationStatus.running))
    store.upsert_task(_task("t1", "op-1", OperationStatus.succeeded))
    with (tmp_path / "state" / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"event": "task_updated", "task": {"task_id": "trunc')  # simulated truncation
    state = store.rebuild(save=True)
    assert state["ledger"]["op-1"]["status"] == "succeeded"
    assert len(state["corrupt_lines"]) == 1
    assert (tmp_path / "state" / "state.json").exists()
    assert rebuild_state([])["tasks"] == {}


def test_revisions_detect_external_change_and_accept(tmp_path: Path):
    (tmp_path / "state").mkdir()
    source = tmp_path / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"BLENDER-v001")
    store = RevisionStore(tmp_path)
    record = store.record("shot:shot010", source)
    assert record.revision == 1
    assert store.check("shot:shot010", 1).ok
    assert store.check("shot:shot010", 2).reason == "revision_mismatch"
    source.write_bytes(b"BLENDER-v001-edited-by-human")
    check = store.check("shot:shot010", 1)
    assert not check.ok and check.reason == "external_change"
    accepted = store.accept_external("shot:shot010")
    assert accepted.revision == 2 and accepted.origin == "external_accepted"
    assert store.check("shot:shot010", 2).ok
    assert store.check("shot:unknown", 3).reason == "revision_unknown"


def test_checkpoint_copies_and_verifies(tmp_path: Path):
    source = tmp_path / "shots" / "s" / "work" / "v001" / "s.blend"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"data")
    manifest = create_file_checkpoint(tmp_path, source, label="test", task_id="t1")
    assert (tmp_path / manifest["copy"]).read_bytes() == b"data"
    assert list_checkpoints(tmp_path)[0]["checkpoint_id"] == manifest["checkpoint_id"]


def test_project_lock_is_exclusive(tmp_path: Path):
    locks = ProjectLocks(tmp_path)
    with locks.hold("project", purpose="test"):
        assert locks.owner("project")["purpose"] == "test"
        with pytest.raises(LockBusy):
            with ProjectLocks(tmp_path).hold("project", timeout=0.2):
                pass
    assert locks.owner("project") is None
