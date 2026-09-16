"""Documented check of the skill format: agentskills.io frontmatter, internal links, request examples."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fluidblend.contracts.operations import validate_request

KIT_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = KIT_ROOT / "skills" / "fluidblend"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = [
    "environment",
    "project",
    "characters",
    "animation",
    "interactions",
    "film",
    "game",
    "tool-development",
    "recovery",
]


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), "the YAML frontmatter must start on the first line"
    end = text.index("\n---", 4)
    block = text[4:end]
    data: dict[str, str] = {}
    current: str | None = None
    for line in block.splitlines():
        if re.match(r"^[a-z_-]+:", line):
            key, _, value = line.partition(":")
            current = key.strip()
            data[current] = value.strip()
        elif current and line.startswith((" ", "\t")):
            data[current] = (data[current] + " " + line.strip()).strip()
    return data


@pytest.fixture(scope="module")
def skill_text() -> str:
    if not SKILL_MD.exists():
        pytest.skip("SKILL.md missing")
    return SKILL_MD.read_text(encoding="utf-8")


def test_frontmatter_matches_agentskills_spec(skill_text: str):
    meta = _frontmatter(skill_text)
    assert meta["name"] == SKILL_DIR.name == "fluidblend"
    assert re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", meta["name"]) and "--" not in meta["name"]
    description = meta["description"].strip("'\"")
    assert 1 <= len(description) <= 1024
    assert "blender" in description.lower()


def test_skill_body_size_and_mode_loading(skill_text: str):
    lines = skill_text.splitlines()
    assert 120 <= len(lines) <= 320, f"{len(lines)} lines: aim for 150-250"
    assert "references/" in skill_text


def test_reference_files_exist_and_are_linked(skill_text: str):
    missing = [name for name in REFERENCES if not (SKILL_DIR / "references" / f"{name}.md").exists()]
    assert missing == [], f"missing references: {missing}"
    linked = set(re.findall(r"references/([a-z-]+)\.md", skill_text))
    assert set(REFERENCES) <= linked, f"references not cited in SKILL.md: {set(REFERENCES) - linked}"
    for match in re.findall(r"\]\(((?:references|assets|scripts)/[^)#]+)\)", skill_text):
        assert (SKILL_DIR / match).exists(), f"broken internal link: {match}"


def test_example_requests_validate():
    assets = sorted((SKILL_DIR / "assets").glob("request-*.json"))
    assert assets, "no request example in skills/fluidblend/assets/"
    for path in assets:
        payload = json.loads(path.read_text(encoding="utf-8"))
        request, _params, spec = validate_request(payload)
        assert spec.available, f"{path.name} references an unavailable operation ({spec.name})"
        assert request.operation_id


def test_wrapper_script_exists():
    assert (SKILL_DIR / "scripts" / "fluidblend.ps1").exists()
