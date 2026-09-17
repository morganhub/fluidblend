"""Running an operation in a dedicated Blender process (batch mode, §7.1).

Pattern: `blender --background --factory-startup --offline-mode --python-exit-code 2
--python entrypoint.py -- request.json result.json --fluidblend-task <task_id>`.
The worker is identified by its PID and by the task marker present in its command line.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso
from fluidblend.core.project import kit_root

EXIT_PYTHON_EXCEPTION = 2


@dataclass
class BatchOutcome:
    exit_code: int | None
    result: dict[str, Any] | None
    timed_out: bool
    elapsed_s: float
    pid: int | None
    stdout_path: Path
    stderr_path: Path
    error: str | None = None
    stderr_tail: str = field(default="")


def entrypoint_path() -> Path:
    return kit_root() / "blender_runtime" / "entrypoint.py"


def build_command(executable: str, request_path: Path, result_path: Path, task_id: str) -> list[str]:
    return [
        executable,
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "--python-exit-code",
        str(EXIT_PYTHON_EXCEPTION),
        "--python",
        str(entrypoint_path()),
        "--",
        str(request_path),
        str(result_path),
        "--fluidblend-task",
        task_id,
    ]


def run_operation(
    executable: str,
    envelope: dict[str, Any],
    task_dir: Path,
    *,
    task_id: str,
    timeout_s: float,
    on_worker_started=None,
) -> BatchOutcome:
    task_dir.mkdir(parents=True, exist_ok=True)
    request_path = task_dir / "request.json"
    result_path = task_dir / "result.json"
    stdout_path = task_dir / "blender.stdout.log"
    stderr_path = task_dir / "blender.stderr.log"
    atomic_write_json(request_path, envelope)
    if result_path.exists():
        result_path.unlink()

    env = dict(os.environ)
    env["FLUIDBLEND_TASK_ID"] = task_id
    env.pop("PYTHONPATH", None)  # the Blender interpreter only loads the approved runtime
    cmd = build_command(executable, request_path, result_path, task_id)
    start = time.perf_counter()
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        try:
            proc = subprocess.Popen(cmd, stdout=out, stderr=err, env=env, cwd=str(task_dir))
        except OSError as exc:
            return BatchOutcome(
                None, None, False, 0.0, None, stdout_path, stderr_path, error=f"cannot launch: {exc}"
            )
        if on_worker_started is not None:
            on_worker_started(
                {"pid": proc.pid, "executable": executable, "started_at": now_iso(), "task_marker": task_id}
            )
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
    elapsed = time.perf_counter() - start
    result: dict[str, Any] | None = None
    error: str | None = None
    if result_path.exists():
        try:
            result = read_json(result_path)
        except ValueError as exc:
            error = f"result.json is unreadable: {exc}"
    tail = ""
    try:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
    except OSError:
        pass
    return BatchOutcome(
        proc.returncode,
        result,
        timed_out,
        elapsed,
        proc.pid,
        stdout_path,
        stderr_path,
        error=error,
        stderr_tail=tail,
    )


def worker_command_line(pid: int) -> str | None:
    """Command line of a process (Windows), used to check the task marker before stopping anything."""
    if os.name != "nt":
        try:
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return None
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine',
    ]
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = completed.stdout.strip()
    return line or None


def kill_worker(pid: int, task_id: str) -> tuple[bool, str]:
    """Only stop the process whose command line carries the task marker."""
    line = worker_command_line(pid)
    if not line:
        return False, "process not found (already finished?)"
    if task_id not in line or "blender" not in line.lower():
        return False, "the process does not match this task worker; nothing was stopped"
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, text=True
        )
        return completed.returncode == 0, completed.stdout.strip() or completed.stderr.strip()
    os.kill(pid, 9)
    return True, "SIGKILL sent"
