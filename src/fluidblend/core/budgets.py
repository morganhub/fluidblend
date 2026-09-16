"""Budgets: estimate before running, check afterwards, calibrate from real measurements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.contracts.common import ErrorCode, ErrorRecord
from fluidblend.contracts.project import Budgets
from fluidblend.core.atomic import atomic_write_json, read_json

# Values measured on 2026-09-16 on a GTX 1080 Ti / i7-9700K, 640x360 (cube). Recalibrated in use.
DEFAULT_SECONDS_PER_FRAME = {"WORKBENCH": 0.2, "EEVEE": 2.5}
DEFAULT_FRAME_MIB = 0.25
BLENDER_STARTUP_SECONDS = 4.0
GLB_EXPORT_SECONDS = 6.0


def metrics_path(root: Path) -> Path:
    return root / "state" / "metrics.json"


def load_metrics(root: Path) -> dict[str, Any]:
    path = metrics_path(root)
    if path.exists():
        try:
            return read_json(path)
        except (OSError, ValueError):
            return {}
    return {}


def record_metric(root: Path, key: str, value: float, *, window: int = 8) -> None:
    data = load_metrics(root)
    history = [float(v) for v in data.get(key, {}).get("history", [])][-(window - 1) :]
    history.append(float(value))
    data[key] = {"history": history, "mean": sum(history) / len(history)}
    atomic_write_json(metrics_path(root), data)


def seconds_per_frame(root: Path, engine: str) -> float:
    data = load_metrics(root).get(f"render.seconds_per_frame.{engine}")
    if data and data.get("mean"):
        return float(data["mean"])
    return DEFAULT_SECONDS_PER_FRAME.get(engine, 2.5)


def estimate_render(root: Path, engine: str, frames: int) -> dict[str, float]:
    per_frame = seconds_per_frame(root, engine)
    return {
        "frames": frames,
        "seconds": BLENDER_STARTUP_SECONDS + frames * per_frame,
        "disk_mib": frames * DEFAULT_FRAME_MIB,
    }


def check_budget(budgets: Budgets, estimate: dict[str, float]) -> list[ErrorRecord]:
    errors: list[ErrorRecord] = []
    frames = int(estimate.get("frames", 0))
    if frames > budgets.max_preview_frames:
        errors.append(
            ErrorRecord(
                code=ErrorCode.BUDGET_EXCEEDED,
                message=f"{frames} frames requested > max_preview_frames={budgets.max_preview_frames}",
                recovery="reduce the range or raise budgets.max_preview_frames in project.json (user decision)",
                details={"frames": frames, "max_preview_frames": budgets.max_preview_frames},
            )
        )
    seconds = float(estimate.get("seconds", 0))
    if seconds > budgets.max_task_minutes * 60:
        errors.append(
            ErrorRecord(
                code=ErrorCode.BUDGET_EXCEEDED,
                message=f"estimated duration {seconds:.0f} s > max_task_minutes={budgets.max_task_minutes}",
                recovery="split the task or raise the time budget",
                details={"estimated_seconds": seconds, "max_task_minutes": budgets.max_task_minutes},
            )
        )
    disk_mib = float(estimate.get("disk_mib", 0))
    if disk_mib > budgets.max_new_disk_gib * 1024:
        errors.append(
            ErrorRecord(
                code=ErrorCode.BUDGET_EXCEEDED,
                message=f"estimated disk usage {disk_mib:.0f} MiB > max_new_disk_gib={budgets.max_new_disk_gib}",
                recovery="reduce the resolution or the frame count, or raise the disk budget",
                details={"estimated_mib": disk_mib},
            )
        )
    return errors


def dir_size_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total
