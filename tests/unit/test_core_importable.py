"""The reusable core: a sibling kit imports these and gets no Blender with them.

Two halves, both needed. A module that quietly starts importing an adapter would break
`fluidunreal` at a distance, and a table in the docs that no longer matches the code is worse
than no table at all.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from fluidblend.core.project import kit_root

REUSABLE = (
    "fluidblend.contracts.common",
    "fluidblend.contracts.capabilities",
    "fluidblend.contracts.handoff",
    "fluidblend.contracts.operations",
    "fluidblend.core.paths",
    "fluidblend.core.atomic",
    "fluidblend.core.hashing",
    "fluidblend.core.journal",
    "fluidblend.core.locks",
    "fluidblend.core.exit_codes",
    "fluidblend.core.budgets",
    "fluidblend.core.checkpoints",
    "fluidblend.core.revisions",
    "fluidblend.core.state",
    "fluidblend.core.dependencies",
    "fluidblend.adapters.tool_paths",
    "fluidblend.adapters.gltf_validator",
)

FORBIDDEN = "bpy, a Blender adapter or core.tasks"

PROBE = (
    "import importlib, sys;"
    "importlib.import_module({module!r});"
    "print(sorted(n for n in sys.modules if n == 'bpy'"
    " or n.startswith('fluidblend.adapters.blender_')"
    " or n == 'fluidblend.core.tasks'))"
)


@pytest.mark.parametrize("module", REUSABLE)
def test_a_reusable_module_drags_in_no_blender(module: str):
    done = subprocess.run(
        [sys.executable, "-c", PROBE.format(module=module)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(kit_root()),
    )
    assert done.returncode == 0, f"{module} does not import: {done.stderr[-800:]}"
    assert done.stdout.strip() == "[]", f"{module} dragged in {FORBIDDEN}: {done.stdout.strip()}"


def test_the_documented_surface_and_this_test_say_the_same_thing():
    """docs/architecture.md is the promise; this list is what is enforced. They must agree."""
    doc = (kit_root() / "docs/architecture.md").read_text(encoding="utf-8")
    section = doc.split("## Reusable core", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([a-z_.]+)` \|", section, re.M))
    assert documented == {m.removeprefix("fluidblend.") for m in REUSABLE}
    assert "breaking for fluidunreal" in section


def test_the_runtime_is_not_part_of_the_promise():
    """`core.runtime_install` reaches for Blender discovery: it is correctly left out."""
    source = (Path(kit_root()) / "src/fluidblend/core/runtime_install.py").read_text(encoding="utf-8")
    assert "adapters.blender_discovery" in source
    assert "fluidblend.core.runtime_install" not in REUSABLE
