"""FFmpeg / ffprobe: image sequence assembly, concatenation, evidence."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from fluidblend.contracts.common import Fps


def find_tool(name: str, configured: str | None) -> str | None:
    from fluidblend.adapters.tool_paths import find_executable

    return find_executable(name, configured)


def tool_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (completed.stdout or completed.stderr).splitlines()[:1]
    return first[0].strip() if first else None


@dataclass
class FfmpegResult:
    ok: bool
    command: list[str]
    returncode: int | None
    stderr_tail: str


def _run(cmd: list[str], timeout: float) -> FfmpegResult:
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FfmpegResult(False, cmd, None, f"{type(exc).__name__}: {exc}")
    return FfmpegResult(
        completed.returncode == 0, cmd, completed.returncode, (completed.stderr or "")[-1500:]
    )


def assemble_sequence(
    ffmpeg: str,
    pattern: Path,
    *,
    start_number: int,
    fps: Fps,
    output: Path,
    crf: int = 18,
    timeout: float = 600.0,
) -> FfmpegResult:
    """`pattern` sequence (e.g. frame_%04d.png) -> MP4 H.264 yuv420p playable everywhere."""
    rate = f"{fps.numerator}/{fps.denominator}"
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-framerate",
        rate,
        "-start_number",
        str(start_number),
        "-i",
        str(pattern),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        "medium",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    return _run(cmd, timeout)


def concat_videos(
    ffmpeg: str, inputs: list[Path], output: Path, *, audio: Path | None = None, timeout: float = 600.0
) -> FfmpegResult:
    list_file = output.with_suffix(".concat.txt")
    lines = []
    for item in inputs:
        escaped = str(item).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio is not None:
        cmd += [
            "-i",
            str(audio),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-shortest",
        ]
    cmd += ["-c:v", "copy", "-movflags", "+faststart", str(output)]
    result = _run(cmd, timeout)
    if result.ok:
        list_file.unlink(missing_ok=True)
    return result


def probe(ffprobe: str, path: Path, *, count_frames: bool = True, timeout: float = 300.0) -> dict[str, Any]:
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if count_frames:
        cmd.append("-count_frames")
    cmd.append(str(path))
    completed = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed ({completed.returncode}): {completed.stderr[-500:]}")
    data = json.loads(completed.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    summary: dict[str, Any] = {
        "path": str(path),
        "format_name": data.get("format", {}).get("format_name"),
        "duration_s": float(data.get("format", {}).get("duration", 0) or 0),
        "video": None,
        "audio_streams": len(audio),
    }
    if video:
        summary["video"] = {
            "codec": video.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"),
            "width": video.get("width"),
            "height": video.get("height"),
            "r_frame_rate": video.get("r_frame_rate"),
            "avg_frame_rate": video.get("avg_frame_rate"),
            "nb_read_frames": int(video["nb_read_frames"]) if video.get("nb_read_frames") else None,
            "nb_frames": int(video["nb_frames"]) if video.get("nb_frames") else None,
        }
    summary["raw"] = data
    return summary


def frame_rate_matches(rate: str | None, fps: Fps) -> bool:
    if not rate:
        return False
    try:
        return Fraction(rate) == fps.as_fraction()
    except (ValueError, ZeroDivisionError):
        return False
