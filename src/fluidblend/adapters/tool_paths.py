"""Known locations of the external executables (PATH, user tools folder, Windows installers).

The `%LOCALAPPDATA%\\fluidblend\\tools\\<tool>\\` folder holds the binaries downloaded after approval
(glTF-Validator, Rhubarb, ...) without touching the PATH nor the system.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

GODOT_GLOBS = (
    "Godot_v*-stable_win64_console.exe",
    "Godot_v*-stable_win64.exe",
    "Godot_v*_win64_console.exe",
    "Godot_v*_win64.exe",
    "godot*.exe",
)


def user_tools_dir() -> Path:
    base = os.environ.get("FLUIDBLEND_TOOLS_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", str(Path.home())), "fluidblend", "tools"
    )
    return Path(base)


def _windows_program_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        value = os.environ.get(env)
        if value:
            roots.append(Path(value))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Programs")
        roots.append(Path(local) / "Microsoft" / "WinGet" / "Packages")
        roots.append(Path(local) / "Microsoft" / "WinGet" / "Links")
    return [r for r in roots if r.exists()]


def find_executable(
    name: str, configured: str | None = None, *, extra_globs: tuple[str, ...] = ()
) -> str | None:
    """Order: configured path -> PATH -> user tools folder -> known Windows installers."""
    if configured and Path(configured).exists():
        return configured
    found = shutil.which(name)
    if found:
        return found
    tools = user_tools_dir()
    if tools.exists():
        for candidate in sorted(tools.rglob(f"{name}.exe")) + sorted(tools.rglob(name)):
            if candidate.is_file():
                return str(candidate)
        for pattern in extra_globs:
            for candidate in sorted(tools.rglob(pattern)):
                if candidate.is_file():
                    return str(candidate)
    if os.name == "nt" and extra_globs:
        for root in _windows_program_roots():
            for pattern in extra_globs:
                for candidate in sorted(root.glob(f"*/{pattern}")) + sorted(root.glob(f"*/*/{pattern}")):
                    if candidate.is_file():
                        return str(candidate)
    return None


_VERSION = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")


def _godot_sort_key(path: Path) -> tuple[int, int, int, int]:
    match = _VERSION.search(path.name)
    version = tuple(int(g or 0) for g in match.groups()) if match else (0, 0, 0)
    # The console variant exposes stdout/stderr in headless mode: preferred at equal version.
    return (*version, 1 if "console" in path.name.lower() else 0)


def find_godot(configured: str | None = None) -> str | None:
    """Most recent Godot among PATH, the tools folder and the known Windows installations."""
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("godot")
    if found:
        return found
    candidates: list[Path] = []
    roots = [user_tools_dir()] + (_windows_program_roots() if os.name == "nt" else [])
    for root in roots:
        if not root.exists():
            continue
        for pattern in GODOT_GLOBS:
            candidates.extend(p for p in root.glob(f"*/{pattern}") if p.is_file())
            candidates.extend(p for p in root.glob(f"*/*/{pattern}") if p.is_file())
    if not candidates:
        return None
    return str(max(candidates, key=_godot_sort_key))
