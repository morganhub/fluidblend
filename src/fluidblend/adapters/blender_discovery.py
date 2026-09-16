"""Discovery and probing of the locked Blender (Windows)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fluidblend.contracts.project import LocalConfig

LOCKED_BLENDER_SERIES = "5.2"
LOCKED_BLENDER_VERSION = "5.2.2"

PROBE_SCRIPT = r"""
import bpy, sys, json, addon_utils
mods = sorted(m.__name__ for m in addon_utils.modules())
a = bpy.data.actions.new("fluidblend_probe")
info = {
    "version_string": bpy.app.version_string,
    "version": list(bpy.app.version),
    "python": sys.version.split()[0],
    "binary_path": bpy.app.binary_path,
    "build_date": bpy.app.build_date.decode() if isinstance(bpy.app.build_date, bytes) else str(bpy.app.build_date),
    "slotted_actions": hasattr(a, "slots") and hasattr(a, "layers"),
    "legacy_fcurves": hasattr(a, "fcurves"),
    "gltf_export": hasattr(bpy.ops.export_scene, "gltf"),
    "gltf_import": hasattr(bpy.ops.import_scene, "gltf"),
    "addons": [m for m in mods if m in ("rigify", "io_scene_gltf2", "io_anim_bvh", "io_scene_fbx", "pose_library")],
    "background": bpy.app.background,
}
print("FLUIDBLEND_PROBE=" + json.dumps(info))
"""


@dataclass
class BlenderCandidate:
    path: str
    source: str
    version_hint: str | None = None


@dataclass
class BlenderProbe:
    ok: bool
    executable: str
    info: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    elapsed_s: float = 0.0


def _registry_candidates() -> list[BlenderCandidate]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    found: list[BlenderCandidate] = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, base in roots:
        try:
            with winreg.OpenKey(hive, base) as key:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, sub) as item:
                            name = str(winreg.QueryValueEx(item, "DisplayName")[0])
                            if "blender" not in name.lower():
                                continue
                            location = str(winreg.QueryValueEx(item, "InstallLocation")[0])
                            version = None
                            try:
                                version = str(winreg.QueryValueEx(item, "DisplayVersion")[0])
                            except OSError:
                                pass
                            exe = Path(location) / "blender.exe"
                            if exe.exists():
                                found.append(BlenderCandidate(str(exe), f"registry:{sub}", version))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def discover_blender(local: LocalConfig | None = None) -> list[BlenderCandidate]:
    candidates: list[BlenderCandidate] = []
    seen: set[str] = set()

    def add(path: str | None, source: str, hint: str | None = None) -> None:
        if not path:
            return
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen or not Path(path).exists():
            return
        seen.add(norm)
        candidates.append(BlenderCandidate(str(Path(path)), source, hint))

    if local and local.blender_executable:
        add(local.blender_executable, "config/local.json")
    add(os.environ.get("FLUIDBLEND_BLENDER"), "env:FLUIDBLEND_BLENDER")
    for cand in _registry_candidates():
        add(cand.path, cand.source, cand.version_hint)
    for base in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if not base:
            continue
        for exe in sorted(Path(base).glob("Blender Foundation/Blender */blender.exe")):
            add(str(exe), "glob:Program Files", exe.parent.name.split()[-1])
    add(shutil.which("blender"), "PATH")
    return candidates


def probe_blender(executable: str, *, timeout: float = 90.0) -> BlenderProbe:
    import time

    cmd = [
        executable,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "2",
        "--python-expr",
        PROBE_SCRIPT,
    ]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return BlenderProbe(
            False, executable, error=f"{type(exc).__name__}: {exc}", elapsed_s=time.perf_counter() - start
        )
    elapsed = time.perf_counter() - start
    for line in completed.stdout.splitlines():
        if line.startswith("FLUIDBLEND_PROBE="):
            try:
                info = json.loads(line[len("FLUIDBLEND_PROBE=") :])
            except json.JSONDecodeError as exc:
                return BlenderProbe(
                    False, executable, error=f"probe output unreadable: {exc}", elapsed_s=elapsed
                )
            return BlenderProbe(True, executable, info=info, elapsed_s=elapsed)
    tail = (completed.stderr or completed.stdout)[-800:]
    return BlenderProbe(
        False,
        executable,
        error=f"exit {completed.returncode} without probe output: {tail}",
        elapsed_s=elapsed,
    )


def is_locked_series(info: dict[str, Any]) -> bool:
    version = info.get("version") or []
    return len(version) >= 2 and f"{version[0]}.{version[1]}" == LOCKED_BLENDER_SERIES


def select_blender(
    local: LocalConfig | None = None, *, allow_unlocked: bool = False, probe: bool = True
) -> tuple[BlenderCandidate | None, BlenderProbe | None, list[str]]:
    """Return the first Blender of the locked series (probed), or None along with the reasons."""
    notes: list[str] = []
    for cand in discover_blender(local):
        if not probe:
            if cand.version_hint and cand.version_hint.startswith(LOCKED_BLENDER_SERIES):
                return cand, None, notes
            continue
        result = probe_blender(cand.path)
        if not result.ok:
            notes.append(f"{cand.path}: {result.error}")
            continue
        if is_locked_series(result.info) or allow_unlocked:
            return cand, result, notes
        notes.append(
            f"{cand.path}: version {result.info.get('version_string')} outside the locked series {LOCKED_BLENDER_SERIES}"
        )
    return None, None, notes
