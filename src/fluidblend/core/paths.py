"""Path guard: nothing escapes the allowed roots (§15.3, acceptance A12).

Rejected: absolute paths outside the root, `..`, UNC, forbidden characters, symlinks and
Windows junctions along the way, protected patterns.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath

FORBIDDEN_CHARS = set('<>"|?*') | {chr(c) for c in range(32)}
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class PathRejected(ValueError):
    def __init__(self, candidate: str, reason: str):
        super().__init__(f"path rejected ({reason}): {candidate}")
        self.candidate = candidate
        self.reason = reason


def normalize_root(root: Path) -> Path:
    return Path(os.path.realpath(root))


def _normcase(path: Path) -> str:
    return os.path.normcase(str(path))


def is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_inside(root: Path, candidate: str | os.PathLike[str], *, allow_missing: bool = True) -> Path:
    """Resolve `candidate` (relative to `root` or absolute) and guarantee it stays under `root`."""
    text = os.fspath(candidate)
    if not text or text.strip() != text:
        raise PathRejected(text, "empty or surrounded by whitespace")
    if text.startswith(("\\\\", "//")):
        raise PathRejected(text, "UNC path")
    bad = {c for c in text if c in FORBIDDEN_CHARS and c not in ":"}
    if bad:
        raise PathRejected(text, "forbidden characters")
    if any(part == ".." for part in Path(text).parts):
        raise PathRejected(text, "parent segment '..'")

    root_real = normalize_root(root)
    raw = Path(text)
    # A colon is allowed only in an absolute drive prefix, never as an NTFS stream.
    tail = text[len(raw.drive) :] if raw.drive else text
    if ":" in tail or (raw.drive and not raw.is_absolute()):
        raise PathRejected(text, "alternate stream or drive-relative path")
    for part in raw.parts:
        if part in (raw.anchor, raw.drive, raw.root):
            continue
        if part.endswith((".", " ")):
            raise PathRejected(text, "ambiguous Windows path component")
        if part.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise PathRejected(text, "Windows device name")
    joined = raw if raw.is_absolute() else root_real / raw
    # Inspect the lexical path before realpath erases links pointing back inside the root.
    try:
        lexical_parts = joined.relative_to(root_real).parts
    except ValueError as exc:
        raise PathRejected(text, "outside the allowed root") from exc
    current = root_real
    for part in lexical_parts:
        current = current / part
        if is_reparse_point(current):
            raise PathRejected(text, "symlink or junction along the path")
    # realpath resolves existing links; missing segments are kept as-is.
    resolved = Path(os.path.realpath(joined))
    try:
        resolved.relative_to(root_real)
    except ValueError as exc:
        raise PathRejected(text, "outside the allowed root") from exc
    if not _normcase(resolved).startswith(_normcase(root_real)):
        raise PathRejected(text, "outside the allowed root")

    # No reparse point (symlink / junction) between the root and the target.
    current = root_real
    for part in resolved.relative_to(root_real).parts:
        current = current / part
        if not current.exists():
            if not allow_missing:
                raise PathRejected(text, "target does not exist")
            break
        if is_reparse_point(current):
            raise PathRejected(text, "symlink or junction along the path")
    return resolved


def relpath_posix(root: Path, path: Path) -> str:
    return PurePosixPath(Path(os.path.relpath(path, normalize_root(root))).as_posix()).as_posix()


def matches_any(rel_posix: str, patterns: list[str]) -> bool:
    pure = PurePosixPath(rel_posix)
    for pattern in patterns:
        if pure.full_match(pattern):
            return True
    return False


def assert_not_protected(rel_posix: str, protected: list[str]) -> None:
    if matches_any(rel_posix, protected):
        raise PathRejected(rel_posix, "path protected by config/permissions.json")
