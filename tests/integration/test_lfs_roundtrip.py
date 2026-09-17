"""Verify local LFS transport using a disposable repository, without touching kit history."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest


def test_lfs_binary_survives_fresh_clone(tmp_path):
    if not shutil.which("git"):
        pytest.skip("not_run: Git missing")

    def git(*args, cwd=None):
        return subprocess.run(
            ["git", *map(str, args)], cwd=cwd, capture_output=True, text=True, timeout=60, check=True
        )

    try:
        git("lfs", "version")
    except subprocess.CalledProcessError:
        pytest.skip("not_run: Git LFS missing")
    source, remote, clone = (tmp_path / name for name in ("source", "remote.git", "clone"))
    git("init", "--initial-branch=main", source)
    git("init", "--bare", "--initial-branch=main", remote)
    git("config", "user.name", "LFS fixture", cwd=source)
    git("config", "user.email", "fixture@example.invalid", cwd=source)
    git("lfs", "install", "--local", cwd=source)
    (source / ".gitattributes").write_text("*.blend filter=lfs diff=lfs merge=lfs -text\n")
    fixture = Path(__file__).resolve().parents[2] / "fixtures/vitruvian/character.blend"
    payload = fixture.read_bytes()
    (source / "transport.blend").write_bytes(payload)
    git("add", ".", cwd=source)
    git("commit", "-m", "LFS Vitruvian fixture roundtrip", cwd=source)
    pointer = git("show", "HEAD:transport.blend", cwd=source).stdout
    assert "https://git-lfs.github.com/spec/v1" in pointer
    git("remote", "add", "origin", remote, cwd=source)
    git("push", "origin", "main", cwd=source)
    git("clone", "--no-local", remote, clone)
    git("lfs", "pull", cwd=clone)
    git("lfs", "fsck", cwd=clone)
    assert (
        hashlib.sha256((clone / "transport.blend").read_bytes()).digest() == hashlib.sha256(payload).digest()
    )
