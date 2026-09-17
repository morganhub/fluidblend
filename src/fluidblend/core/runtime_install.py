"""Install the approved runtime as a Blender add-on for live mode (§7.2: identifiable, approved runtime).

The batch mode never needs this: `blender_runtime/entrypoint.py` imports the package from the kit.
Live mode goes through the MCP add-on, whose safe mode only allows `import bpy`; the runtime is
therefore reached through registered operators (`bpy.ops.fluidblend.*`) of an enabled add-on.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fluidblend import __version__
from fluidblend.adapters.blender_discovery import LOCKED_BLENDER_SERIES
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso
from fluidblend.core.project import kit_root

RUNTIME_PACKAGE = "fluidblend_runtime"
MANIFEST_NAME = "RUNTIME_MANIFEST.json"


def runtime_source_dir() -> Path:
    return kit_root() / "blender_runtime" / RUNTIME_PACKAGE


def blender_user_addons_dir(series: str = LOCKED_BLENDER_SERIES) -> Path:
    override = os.environ.get("FLUIDBLEND_BLENDER_ADDONS_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; cannot locate the Blender user add-ons directory")
    return Path(appdata) / "Blender Foundation" / "Blender" / series / "scripts" / "addons"


def _runtime_files(source: Path) -> list[Path]:
    return sorted(p for p in source.rglob("*.py") if "__pycache__" not in p.parts)


def runtime_tree_hash(source: Path) -> str:
    """Stable hash of the runtime's Python files (relative path + content), independent of timestamps."""
    digest = hashlib.sha256()
    for path in _runtime_files(source):
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_status(addons_dir: Path | None = None) -> dict[str, Any]:
    addons_dir = addons_dir or blender_user_addons_dir()
    target = addons_dir / RUNTIME_PACKAGE
    source = runtime_source_dir()
    kit_hash = runtime_tree_hash(source)
    status: dict[str, Any] = {
        "package": RUNTIME_PACKAGE,
        "path": str(target),
        "installed": target.is_dir() and (target / "__init__.py").exists(),
        "kit_version": __version__,
        "kit_hash": kit_hash,
        "manifest": None,
        "installed_hash": None,
        "up_to_date": False,
    }
    if not status["installed"]:
        return status
    manifest_path = target / MANIFEST_NAME
    if manifest_path.exists():
        try:
            status["manifest"] = read_json(manifest_path)
        except (OSError, ValueError):
            status["manifest"] = None
    status["installed_hash"] = runtime_tree_hash(target)
    status["up_to_date"] = (
        status["installed_hash"] == kit_hash and (status["manifest"] or {}).get("version") == __version__
    )
    return status


def install_runtime(addons_dir: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    """Copy the runtime package into the Blender user add-ons directory; idempotent (hash-checked)."""
    addons_dir = addons_dir or blender_user_addons_dir()
    source = runtime_source_dir()
    target = addons_dir / RUNTIME_PACKAGE
    before = runtime_status(addons_dir)
    if before["installed"] and before["up_to_date"] and not force:
        return {**before, "action": "up_to_date"}
    action = "replaced" if before["installed"] else "installed"
    addons_dir.mkdir(parents=True, exist_ok=True)
    staging = addons_dir / f".{RUNTIME_PACKAGE}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    manifest = {
        "schema_version": "1.0",
        "package": RUNTIME_PACKAGE,
        "version": __version__,
        "hash": runtime_tree_hash(source),
        "source": str(source),
        # The Director panel runs the very same engine the user installed from, never a copy.
        "cli": [sys.executable, "-m", "fluidblend.cli"],
        "installed_at": now_iso(),
    }
    atomic_write_json(staging / MANIFEST_NAME, manifest)
    if target.exists():
        shutil.rmtree(target)
    os.replace(staging, target)
    return {**runtime_status(addons_dir), "action": action}


def uninstall_runtime(addons_dir: Path | None = None) -> bool:
    addons_dir = addons_dir or blender_user_addons_dir()
    target = addons_dir / RUNTIME_PACKAGE
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


ENABLE_SCRIPT = """
import bpy, json
result = bpy.ops.preferences.addon_enable(module="fluidblend_runtime")
bpy.ops.wm.save_userpref()
print("FLUIDBLEND_ENABLE=" + json.dumps({"result": list(result), "enabled": "fluidblend_runtime" in bpy.context.preferences.addons}))
"""


def enable_runtime_addon(blender_executable: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """Enable the add-on in the user preferences (headless, no --factory-startup so the prefs persist)."""
    cmd = [blender_executable, "--background", "--python-exit-code", "2", "--python-expr", ENABLE_SCRIPT]
    completed = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    for line in completed.stdout.splitlines():
        if line.startswith("FLUIDBLEND_ENABLE="):
            data = json.loads(line[len("FLUIDBLEND_ENABLE=") :])
            return {"ok": bool(data.get("enabled")), **data, "exit_code": completed.returncode}
    return {"ok": False, "exit_code": completed.returncode, "stderr": completed.stderr[-800:]}
