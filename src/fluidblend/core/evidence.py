"""Bind technical evidence to a particular scene and to the files actually measured."""

from pathlib import Path

from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import resolve_inside


def verify_evidence(
    report: Path, *, project_id: str, shot_id: str, revision: int, scene_sha256: str
) -> tuple[bool, str]:
    try:
        evidence = read_json(report.parent / "evidence.json")
        expected = (project_id, shot_id, revision, scene_sha256)
        observed = tuple(evidence.get(k) for k in ("project_id", "shot_id", "revision", "scene_sha256"))
        if observed != expected:
            return False, "evidence belongs to a different scene revision"
        files = evidence.get("files", {})
        if report.name not in files:
            return False, "report not covered by evidence"
        for relative, digest in files.items():
            path = resolve_inside(report.parent, relative)
            if not path.is_file() or sha256_file(path) != digest:
                return False, f"evidence file missing or changed: {relative}"
        return True, "verified"
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return False, f"missing or invalid evidence: {exc}"
