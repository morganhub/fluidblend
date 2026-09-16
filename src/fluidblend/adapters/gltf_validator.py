"""Khronos glTF-Validator (external binary, Apache-2.0). Missing = `not_installed` capability, never simulated."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from fluidblend.core.atomic import atomic_write_text

IGNORED_BY_DEFAULT = {"ACCESSOR_JOINTS_USED_ZERO_WEIGHT"}


def find_validator(configured: str | None) -> str | None:
    from fluidblend.adapters.tool_paths import find_executable

    return find_executable("gltf_validator", configured)


def validate(executable: str, glb_path: Path, report_path: Path, *, timeout: float = 300.0) -> dict[str, Any]:
    """`gltf_validator -r -a -o asset.glb` -> JSON report on stdout, copied into `report_path`."""
    cmd = [executable, "-r", "-a", "-o", str(glb_path)]
    completed = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"validator produced no output (exit {completed.returncode}): {completed.stderr[-500:]}"
        )
    report = json.loads(stdout)
    atomic_write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    issues = report.get("issues", {})
    messages = issues.get("messages", [])
    blocking = [m for m in messages if m.get("severity") == 0 and m.get("code") not in IGNORED_BY_DEFAULT]
    return {
        "validator_version": report.get("validatorVersion"),
        "num_errors": issues.get("numErrors", 0),
        "num_warnings": issues.get("numWarnings", 0),
        "num_infos": issues.get("numInfos", 0),
        "blocking_errors": [m.get("code") for m in blocking],
        "info": report.get("info", {}),
        "exit_code": completed.returncode,
        "report_path": str(report_path),
        "passed": not blocking,
    }
