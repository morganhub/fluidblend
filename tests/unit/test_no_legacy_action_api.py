"""Guard: the legacy Action API (removed in Blender 5.0) only shows up in comments of the slotted module."""

from __future__ import annotations

import re
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {KIT_ROOT / "blender_runtime" / "fluidblend_runtime" / "anim" / "slotted.py"}
LEGACY = re.compile(r"(?<![A-Za-z_])(action|act|a)\.(fcurves|groups|id_root)\b")


def test_runtime_does_not_use_legacy_action_api():
    offenders = []
    for path in (KIT_ROOT / "blender_runtime").rglob("*.py"):
        if path in ALLOWED:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if LEGACY.search(line):
                offenders.append(f"{path.relative_to(KIT_ROOT)}:{line_no}: {stripped}")
    assert offenders == [], "\n".join(offenders)


def test_runtime_has_no_third_party_imports():
    allowed_roots = {"bpy", "mathutils", "bmesh", "fluidblend_runtime"}
    stdlib_ok = {
        "os",
        "sys",
        "json",
        "math",
        "time",
        "hashlib",
        "secrets",
        "random",
        "re",
        "traceback",
        "dataclasses",
        "contextlib",
        "collections",
        "typing",
        "__future__",
    }
    offenders = []
    for path in (KIT_ROOT / "blender_runtime").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
            if match:
                root = match.group(1)
                if root not in allowed_roots and root not in stdlib_ok:
                    offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
