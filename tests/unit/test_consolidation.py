from pathlib import Path

import pytest
from tests.conftest import make_request
from tests.unit.test_state_and_revisions import _task

from fluidblend.cli import main
from fluidblend.contracts.capabilities import CapabilitiesReport, Capability
from fluidblend.contracts.common import OperationStatus
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.dependencies import compare_lock
from fluidblend.core.evidence import verify_evidence
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import load_project
from fluidblend.core.tasks import TaskRunner


def test_unavailable_operation_stops_before_routing(project_root, unavailable_operation):
    runner = TaskRunner(load_project(project_root))
    outcome = runner.run(
        make_request(
            unavailable_operation,
            "unavailable-001",
            target={"shot_id": "shot010"},
            parameters={"game_dir": "reviews/shot010/import/game"},
        )
    )
    assert outcome.exit_code == 2
    assert outcome.result.errors[0].code == "UNSUPPORTED_CAPABILITY"
    assert runner.state.tasks() == []


def test_live_cancel_is_believed_only_on_the_session_acknowledgement(project_root):
    import threading

    from fluidblend.core.atomic import atomic_write_json

    runner = TaskRunner(load_project(project_root), test_hooks={"live_cancel_wait_s": 5})
    task = _task("live-002", "live-operation-002", OperationStatus.running)
    task.mode = "live"
    runner.state.upsert_task(task)
    task_dir = project_root / "state/tasks/live-002"
    task_dir.mkdir(parents=True)

    def session():
        # Stand-in for the Blender timer: acknowledge only once the request file exists.
        while not (task_dir / "cancel.request").exists():
            threading.Event().wait(0.05)
        atomic_write_json(task_dir / "cancel.ack.json", {"task_id": "live-002", "nothing_saved": True})

    worker = threading.Thread(target=session)
    worker.start()
    result = runner.cancel(task.task_id)
    worker.join()
    assert result["cancelled"] is True and result["acknowledgement"]["nothing_saved"] is True


def test_live_cancel_never_kills_gui_or_claims_confirmation(project_root, monkeypatch):
    runner = TaskRunner(load_project(project_root), test_hooks={"live_cancel_wait_s": 0.4})
    task = _task("live-001", "live-operation-001", OperationStatus.running)
    task.mode = "live"
    runner.state.upsert_task(task)

    def forbidden(*args):
        pytest.fail("must not kill Blender GUI")

    monkeypatch.setattr("fluidblend.core.tasks.blender_batch.kill_worker", forbidden)
    result = runner.cancel(task.task_id)
    assert result["cancelled"] is False
    assert runner.state.task(task.task_id).status == "unknown"
    with runner.locks.hold("project"):
        assert runner.reconcile(task.task_id)["action"] == "wait"


def test_doctor_compares_without_rewriting_lock(project_root, monkeypatch, capsys):
    report = CapabilitiesReport(
        generated_at="now",
        capabilities=[
            Capability(
                capability_id="blender.batch",
                provider="Blender",
                version="5.2.2",
                status="available",
                verified_at="now",
                evidence={"sha256": "actual"},
            )
        ],
    )
    path = project_root / "dependencies.lock.json"
    atomic_write_json(
        path,
        {
            "dependencies": {
                "blender.batch": {
                    "name": "Blender",
                    "version": "5.2.2",
                    "sha256": "locked",
                    "status": "available",
                }
            }
        },
    )
    before = path.read_bytes()
    monkeypatch.setattr("fluidblend.doctor.run_doctor", lambda *args, **kwargs: report)
    assert main(["doctor", "--project", str(project_root), "--json"]) == 2
    assert path.read_bytes() == before
    assert compare_lock(path, report)["differences"][0]["field"] == "sha256"
    explicit = project_root / "proposed-lock.json"
    main(["doctor", "--project", str(project_root), "--write-lock", str(explicit), "--json"])
    assert explicit.exists() and path.read_bytes() == before
    capsys.readouterr()


def test_evidence_rejects_stale_revision_and_modified_files(tmp_path: Path):
    report = tmp_path / "audit.json"
    report.write_text('{"passed":true}', encoding="utf-8")
    atomic_write_json(
        tmp_path / "evidence.json",
        {
            "project_id": "p",
            "shot_id": "s",
            "revision": 1,
            "scene_sha256": "source",
            "files": {"audit.json": sha256_file(report)},
        },
    )
    kwargs = dict(project_id="p", shot_id="s", revision=1, scene_sha256="source")
    assert verify_evidence(report, **kwargs)[0]
    assert not verify_evidence(report, **dict(kwargs, revision=2))[0]
    assert not verify_evidence(report, **dict(kwargs, scene_sha256="edited"))[0]
    report.write_text('{"passed":false}', encoding="utf-8")
    assert not verify_evidence(report, **kwargs)[0]


def test_pinned_binary_drift_is_refused(project, tmp_path):
    from fluidblend.core.dependencies import verify_executable

    binary = tmp_path / "test.exe"
    binary.write_bytes(b"locked version")
    atomic_write_json(
        project.root / "dependencies.lock.json",
        {
            "dependencies": {
                "blender.batch": {"name": "Blender", "sha256": sha256_file(binary), "status": "available"}
            }
        },
    )
    verify_executable(project, "blender.batch", str(binary))
    binary.write_bytes(b"unapproved update")
    with pytest.raises(ValueError, match="migration"):
        verify_executable(project, "blender.batch", str(binary))


@pytest.mark.parametrize("name", ["file:stream", "CON.txt", "nested/NUL", "folder./data", "C:relative"])
def test_windows_aliases_are_rejected(tmp_path, name):
    from fluidblend.core.paths import resolve_inside

    with pytest.raises(ValueError):
        resolve_inside(tmp_path, name)


def test_inside_root_symlink_is_rejected(tmp_path):
    import os

    from fluidblend.core.paths import resolve_inside

    target = tmp_path / "actual"
    target.mkdir()
    try:
        os.symlink(target, tmp_path / "alias", target_is_directory=True)
    except OSError:
        pytest.skip("not_run: Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="symlink"):
        resolve_inside(tmp_path, "alias/file")


def test_input_edit_during_execution_prevents_publication(project, monkeypatch):
    from fluidblend.contracts.common import OperationResult

    path = project.root / "audio/source/concurrent.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"original source")
    runner = TaskRunner(project)

    def edited_input(request, params, spec, task, source):
        path.write_bytes(b"human replacement")
        return OperationResult(
            operation_id=request.operation_id,
            operation=spec.name,
            task_id=task.task_id,
            status="succeeded",
        )

    monkeypatch.setattr(runner, "_execute", edited_input)
    outcome = runner.run(
        make_request(
            "audio.prepare",
            "concurrent-audio-input",
            parameters={"source_path": "audio/source/concurrent.wav"},
        )
    )
    assert outcome.result.errors[0].code == "SCENE_CONFLICT"
    assert path.read_bytes() == b"human replacement"
    assert not (project.root / "reviews/project/concurrent-audio-input").exists()
