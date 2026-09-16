from __future__ import annotations

import os
from pathlib import Path

import pytest

from fluidblend.core.paths import PathRejected, matches_any, relpath_posix, resolve_inside


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "Projet é"
    (base / "shots" / "shot010").mkdir(parents=True)
    (base / "shots" / "shot010" / "shot.json").write_text("{}", encoding="utf-8")
    return base


def test_relative_inside_is_accepted(root: Path):
    resolved = resolve_inside(root, "shots/shot010/shot.json", allow_missing=False)
    assert resolved.exists()
    assert relpath_posix(root, resolved) == "shots/shot010/shot.json"


def test_missing_relative_is_accepted_when_allowed(root: Path):
    assert resolve_inside(root, "renders/new/frame.png").name == "frame.png"
    with pytest.raises(PathRejected):
        resolve_inside(root, "renders/new/frame.png", allow_missing=False)


@pytest.mark.parametrize(
    "candidate, reason",
    [
        ("../outside.txt", "parent segment '..'"),
        ("shots/../../outside.txt", "parent segment '..'"),
        ("\\\\server\\share\\x", "UNC path"),
        ("shots/<x>.json", "forbidden characters"),
        ("", "empty"),
    ],
)
def test_escapes_are_rejected(root: Path, candidate: str, reason: str):
    with pytest.raises(PathRejected) as exc:
        resolve_inside(root, candidate)
    assert reason.split()[0] in exc.value.reason


def test_absolute_outside_is_rejected(root: Path, tmp_path: Path):
    outside = tmp_path / "elsewhere" / "x.blend"
    with pytest.raises(PathRejected) as exc:
        resolve_inside(root, str(outside))
    assert "outside" in exc.value.reason


def test_absolute_inside_is_accepted(root: Path):
    inside = root / "shots" / "shot010" / "shot.json"
    assert resolve_inside(root, str(inside), allow_missing=False) == inside.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_junction_on_path_is_rejected(root: Path, tmp_path: Path):
    import _winapi

    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    junction = root / "assets_link"
    _winapi.CreateJunction(str(outside), str(junction))
    with pytest.raises(PathRejected) as exc:
        resolve_inside(root, "assets_link/secret.txt")
    assert exc.value.reason in ("symlink or junction along the path", "outside the allowed root")


def test_protected_patterns():
    protected = ["shots/*/approved/**", "audio/source/**"]
    assert matches_any("shots/shot010/approved/v001/shot010.blend", protected)
    assert matches_any("audio/source/voice.wav", protected)
    assert not matches_any("shots/shot010/work/v001/shot010.blend", protected)
