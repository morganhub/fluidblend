"""Revisions of protected sources: detection of manual changes (acceptance A07)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fluidblend.contracts.project import RevisionRecord, RevisionsFile
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import now_iso, sha256_file
from fluidblend.core.paths import relpath_posix


@dataclass
class RevisionCheck:
    ok: bool
    reason: str | None
    current: RevisionRecord | None
    observed_sha256: str | None = None


class RevisionStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "state" / "revisions.json"

    def load(self) -> RevisionsFile:
        if not self.path.exists():
            return RevisionsFile()
        return RevisionsFile.model_validate(read_json(self.path))

    def save(self, data: RevisionsFile) -> None:
        atomic_write_json(self.path, data.model_dump(mode="json"))

    def get(self, target: str) -> RevisionRecord | None:
        return self.load().revisions.get(target)

    def check(self, target: str, expected: int | None) -> RevisionCheck:
        record = self.get(target)
        if record is None:
            if expected not in (None, 0):
                return RevisionCheck(False, "revision_unknown", None)
            return RevisionCheck(True, None, None)
        path = self.root / record.path
        if not path.exists():
            return RevisionCheck(False, "source_missing", record)
        observed = sha256_file(path)
        if observed != record.sha256:
            return RevisionCheck(False, "external_change", record, observed)
        if expected is not None and expected != record.revision:
            return RevisionCheck(False, "revision_mismatch", record, observed)
        return RevisionCheck(True, None, record, observed)

    def record(self, target: str, path: Path, *, origin: str = "kit") -> RevisionRecord:
        data = self.load()
        previous = data.revisions.get(target)
        record = RevisionRecord(
            target=target,
            revision=(previous.revision + 1) if previous else 1,
            path=relpath_posix(self.root, path),
            sha256=sha256_file(path),
            bytes=path.stat().st_size,
            updated_at=now_iso(),
            origin=origin,  # type: ignore[arg-type]
        )
        data.revisions[target] = record
        self.save(data)
        return record

    def accept_external(self, target: str) -> RevisionRecord:
        record = self.get(target)
        if record is None:
            raise KeyError(target)
        return self.record(target, self.root / record.path, origin="external_accepted")
