"""Bounded ZIP admission. Extract only into a new directory, never over project files."""

import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fluidblend.core.paths import resolve_inside


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 512 * 1024 * 1024
    max_expanded_bytes: int = 1024 * 1024 * 1024
    max_files: int = 10_000
    max_expansion_ratio: float = 100.0


DEFAULT_LIMITS = ArchiveLimits()


def _members(archive: zipfile.ZipFile, destination: Path, limits: ArchiveLimits):
    entries = archive.infolist()
    if len(entries) > limits.max_files:
        raise ValueError("archive member count exceeds limit")
    seen, total = set(), 0
    for entry in entries:
        name = entry.filename.rstrip("/")
        if ":" in name or "\\" in name:
            raise ValueError("archive paths must be relative POSIX paths without alternate streams")
        for part in name.split("/"):
            if not part or part in (".", "..") or part.endswith((".", " ")):
                raise ValueError("ambiguous archive path")
            if part.split(".")[0].upper() in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }:
                raise ValueError("Windows device name in archive")
        resolve_inside(destination, name)
        normalized = name.replace("\\", "/").casefold()
        if normalized in seen:
            raise ValueError("duplicate archive member (Windows case-insensitive)")
        seen.add(normalized)
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError("archive links and special files are forbidden")
        if entry.flag_bits & 1:
            raise ValueError("encrypted archive members are unsupported")
        total += entry.file_size
        if total > limits.max_expanded_bytes:
            raise ValueError("archive expansion exceeds byte limit")
        if entry.file_size > limits.max_expansion_ratio * max(1, entry.compress_size):
            raise ValueError("archive expansion ratio exceeds limit")
    return entries


def extract_zip(
    root: Path, source: str, destination: str, *, limits: ArchiveLimits = DEFAULT_LIMITS
) -> list[str]:
    source_path = resolve_inside(root, source)
    target = resolve_inside(root, destination)
    if target.exists():
        raise ValueError("archive destination already exists")
    if source_path.stat().st_size > limits.max_archive_bytes:
        raise ValueError("compressed archive exceeds byte limit")
    # Validate the entire directory before creating the staging directory.
    with zipfile.ZipFile(source_path) as archive:
        entries = _members(archive, target, limits)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=target.parent) as staging:
            stage = Path(staging) / "contents"
            stage.mkdir()
            total = 0
            for entry in entries:
                path = resolve_inside(stage, entry.filename.rstrip("/"))
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with archive.open(entry) as inp, path.open("xb") as out:
                    while chunk := inp.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > entry.file_size or total > limits.max_expanded_bytes:
                            raise ValueError("actual archive expansion exceeds limit")
                        out.write(chunk)
                if size != entry.file_size:
                    raise ValueError("archive member size mismatch")
            # On supported Windows, rename refuses an occupied target.
            if target.exists():
                raise ValueError("archive destination created concurrently")
            os.rename(stage, target)
    return [entry.filename for entry in entries if not entry.is_dir()]
