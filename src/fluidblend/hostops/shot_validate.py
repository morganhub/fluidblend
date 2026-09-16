"""shot.validate: technical evidence for a shot (files, revision, preview, audit). Changes nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluidblend.contracts.common import ErrorCode
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.revisions import RevisionStore
from fluidblend.hostops.context import HostContext, HostOpError


def _latest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def run(ctx: HostContext) -> None:
    project = ctx.project
    shot_id = ctx.request.target.shot_id or ""
    try:
        shot = project.shot_manifest(shot_id)
    except Exception as exc:  # noqa: BLE001
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"shot.json is invalid: {exc}") from exc
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, **details: Any) -> None:
        checks.append({"check": name, "passed": bool(passed), **details})

    latest = project.latest_work_blend(shot_id)
    check(
        "work_version_exists",
        latest is not None,
        latest=str(latest[1].relative_to(project.root)) if latest else None,
    )
    revision = RevisionStore(project.root).get(f"shot:{shot_id}")
    if latest and revision:
        observed = sha256_file(latest[1])
        check(
            "revision_hash_matches",
            observed == revision.sha256,
            revision=revision.revision,
            expected=revision.sha256,
            observed=observed,
        )
    else:
        check("revision_recorded", revision is not None)

    renders = project.root / "renders" / shot_id
    probe_path = _latest(list(renders.glob("*/ffprobe.json"))) if renders.exists() else None
    require_preview = getattr(ctx.params, "require_preview", True)
    if probe_path is None:
        check("preview_exists", not require_preview, note="no published preview")
    else:
        probe = read_json(probe_path)
        video = probe.get("video") or {}
        render_report_path = probe_path.with_name("render-report.json")
        expected_frames = None
        if render_report_path.exists():
            expected_frames = read_json(render_report_path).get("expected_frames")
        check(
            "preview_frame_count",
            expected_frames is not None and video.get("nb_read_frames") == expected_frames,
            expected=expected_frames,
            observed=video.get("nb_read_frames"),
            source=str(probe_path.relative_to(project.root)),
        )
        fps = project.manifest.fps
        check(
            "preview_frame_rate",
            video.get("r_frame_rate") == f"{fps.numerator}/{fps.denominator}",
            observed=video.get("r_frame_rate"),
        )
        check("preview_pix_fmt", video.get("pix_fmt") == "yuv420p", observed=video.get("pix_fmt"))

    reviews = project.root / "reviews" / shot_id
    audit_path = _latest(list(reviews.glob("*/audit.json"))) if reviews.exists() else None
    if audit_path is not None:
        audit = read_json(audit_path)
        check(
            "latest_audit_passed",
            bool(audit.get("passed")),
            errors=audit.get("error_count"),
            source=str(audit_path.relative_to(project.root)),
        )
    else:
        check("audit_available", False, note="no published audit")

    passed = all(c["passed"] for c in checks)
    report = {
        "shot_id": shot_id,
        "frame_range": shot.frame_range.model_dump(),
        "checks": checks,
        "technical_pass": passed,
        "suggested_validation_state": "technical_pass" if passed else "draft",
        "note": "automatic technical validation; the artistic review (visual_review_pending -> art_approved) stays human",
    }
    ctx.write_report("shot-validation.json", report)
    ctx.metrics.update(
        {
            "technical_pass": passed,
            "checks": len(checks),
            "failed_checks": [c["check"] for c in checks if not c["passed"]],
        }
    )
    if not passed:
        ctx.warnings.append("technical validation failed; see shot-validation.json")
