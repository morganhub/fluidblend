"""film.assemble: concatenation of the published shot previews (external FFmpeg, ffprobe evidence)."""

from __future__ import annotations

from pathlib import Path

from fluidblend.adapters import ffmpeg as ff
from fluidblend.contracts.common import ChangedEntity, ErrorCode
from fluidblend.core.paths import PathRejected, resolve_inside
from fluidblend.hostops.context import HostContext, HostOpError


def _latest_preview(project_root: Path, shot_id: str) -> Path | None:
    base = project_root / "renders" / shot_id
    if not base.exists():
        return None
    candidates = list(base.glob("*/preview.mp4"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def run(ctx: HostContext) -> None:
    project = ctx.project
    params = ctx.params
    ffmpeg = ff.find_tool("ffmpeg", project.local.ffmpeg_executable)
    ffprobe = ff.find_tool("ffprobe", project.local.ffprobe_executable)
    if not ffmpeg or not ffprobe:
        raise HostOpError(
            ErrorCode.MISSING_DEPENDENCY,
            "ffmpeg/ffprobe not found",
            recovery="install FFmpeg (winget Gyan.FFmpeg) or set the paths in config/local.json",
        )
    inputs: list[Path] = []
    for shot_id in params.shot_ids:  # type: ignore[attr-defined]
        preview = _latest_preview(project.root, shot_id)
        if preview is None:
            raise HostOpError(
                ErrorCode.VALIDATION_FAILED,
                f"no published preview for {shot_id}",
                recovery=f"run shot.preview on {shot_id}",
            )
        inputs.append(preview)
    audio: Path | None = None
    if getattr(params, "audio_path", None):
        try:
            audio = resolve_inside(project.root, params.audio_path, allow_missing=False)  # type: ignore[attr-defined]
        except PathRejected as exc:
            raise HostOpError(ErrorCode.VALIDATION_FAILED, str(exc), details={"reason": exc.reason}) from exc
    output = ctx.out_dir / f"{params.output_name}.mp4"  # type: ignore[attr-defined]
    result = ff.concat_videos(ffmpeg, inputs, output, audio=audio)
    if not result.ok:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "FFmpeg concatenation failed",
            details={"stderr": result.stderr_tail, "command": result.command},
        )
    probe = ff.probe(ffprobe, output)
    ctx.write_report("ffprobe.json", probe)
    expected_frames = 0
    for item in inputs:
        item_probe = ff.probe(ffprobe, item)
        expected_frames += int((item_probe.get("video") or {}).get("nb_read_frames") or 0)
    observed = int((probe.get("video") or {}).get("nb_read_frames") or 0)
    ctx.add_file("video", output, frames=observed, inputs=[str(p.relative_to(project.root)) for p in inputs])
    ctx.metrics.update(
        {
            "shots": len(inputs),
            "frames_expected": expected_frames,
            "frames_observed": observed,
            "duration_s": probe.get("duration_s"),
        }
    )
    if observed != expected_frames:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            f"concatenated frames {observed} != sum over the shots {expected_frames}",
        )
    ctx.changed.append(ChangedEntity(kind="file", id=output.name, change="created"))
