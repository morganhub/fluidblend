"""Offline two-pass loudness normalization and phonetic cues; source audio is immutable."""

import json
import math
import subprocess
import time
import wave
from fractions import Fraction

from fluidblend.adapters.ffmpeg import find_tool
from fluidblend.contracts.common import ErrorCode
from fluidblend.core.dependencies import verify_executable
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import resolve_inside
from fluidblend.hostops.context import HostOpError


def run_tool(ctx, command):
    remaining = ctx.project.manifest.budgets.max_task_minutes * 60 - (
        time.monotonic() - ctx.started_monotonic
    )
    if remaining <= 0:
        raise HostOpError(ErrorCode.BUDGET_EXCEEDED, "audio task time budget exhausted")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=remaining,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"audio tool failed: {exc}") from exc
    if result.returncode:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "audio tool returned an error",
            details={"exit_code": result.returncode, "stderr": result.stderr[-2000:]},
        )
    return result


def source_for(ctx):
    path = resolve_inside(ctx.project.root, ctx.params.source_path, allow_missing=False)
    if not path.is_file():
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "audio source must be a file")
    return path, sha256_file(path)


def tool_for(ctx, name, configured, capability):
    tool = find_tool(name, configured)
    if not tool:
        raise HostOpError(ErrorCode.MISSING_DEPENDENCY, f"{name} missing")
    try:
        verify_executable(ctx.project, capability, tool)
    except (OSError, ValueError) as exc:
        raise HostOpError(ErrorCode.MISSING_DEPENDENCY, str(exc)) from exc
    return tool


def prepare(ctx):
    source, digest = source_for(ctx)
    tool = tool_for(ctx, "ffmpeg", ctx.project.local.ffmpeg_executable, "video.ffmpeg")
    p = ctx.params
    target = f"I={p.integrated_lufs}:TP={p.true_peak_db}:LRA={p.loudness_range_lu}"
    first = run_tool(
        ctx,
        [
            tool,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            f"aformat=channel_layouts=mono,loudnorm={target}:print_format=json",
            "-f",
            "null",
            "-",
        ],
    )
    try:
        measured, _ = json.JSONDecoder().raw_decode(first.stderr[first.stderr.rfind("{") :])
        values = {
            key: float(measured[key])
            for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        }
    except (ValueError, KeyError) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "FFmpeg did not return loudness measurements") from exc
    if not all(math.isfinite(v) for v in values.values()):
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "source is silent or loudness cannot be measured")
    output = ctx.out_dir / "prepared.wav"
    filter_text = (
        f"aformat=channel_layouts=mono,loudnorm={target}:measured_I={values['input_i']}:measured_TP={values['input_tp']}:"
        f"measured_LRA={values['input_lra']}:measured_thresh={values['input_thresh']}:"
        f"offset={values['target_offset']}:linear=true:print_format=json,aresample=48000"
    )
    second = run_tool(
        ctx,
        [
            tool,
            "-nostdin",
            "-n",
            "-hide_banner",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            filter_text,
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
    )
    with wave.open(str(output), "rb") as wav:
        samples, rate, channels = wav.getnframes(), wav.getframerate(), wav.getnchannels()
    if rate != 48000 or channels != 1:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "prepared WAV format mismatch")
    if sha256_file(source) != digest:
        raise HostOpError(ErrorCode.SCENE_CONFLICT, "source changed during audio preparation")
    try:
        second_pass, _ = json.JSONDecoder().raw_decode(second.stderr[second.stderr.rfind("{") :])
        output_i, output_tp = float(second_pass["output_i"]), float(second_pass["output_tp"])
    except (ValueError, KeyError) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "second-pass measurement missing") from exc
    if not math.isfinite(output_i) or not math.isfinite(output_tp):
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "non-finite normalized loudness")
    if abs(output_i - p.integrated_lufs) > 1 or output_tp > p.true_peak_db + 0.2:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "normalized loudness is outside target tolerance")
    duration = Fraction(samples, rate)
    frames = duration * ctx.project.manifest.fps.as_fraction()
    ctx.add_file("audio", output)
    ctx.write_report(
        "audio-preparation.json",
        {
            "source_path": ctx.params.source_path,
            "source_sha256": digest,
            "output_sha256": sha256_file(output),
            "sample_rate": rate,
            "channels": channels,
            "samples": samples,
            "duration_seconds": {"numerator": duration.numerator, "denominator": duration.denominator},
            "duration_frames": {"numerator": frames.numerator, "denominator": frames.denominator},
            "first_pass": measured,
            "second_pass": second_pass,
            "filter": filter_text,
        },
    )
    ctx.metrics.update(
        {"sample_rate": rate, "channels": channels, "samples": samples, "source_preserved": True}
    )


def analyze(ctx):
    source, digest = source_for(ctx)
    tool = tool_for(ctx, "rhubarb", ctx.project.local.rhubarb_executable, "audio.rhubarb")
    version = run_tool(ctx, [tool, "--version"])
    if "1.14" not in version.stdout + version.stderr:
        raise HostOpError(ErrorCode.MISSING_DEPENDENCY, "Rhubarb 1.14 required")
    output = ctx.out_dir / "rhubarb.json"
    run_tool(ctx, [tool, "-f", "json", "-r", "phonetic", "-o", str(output), str(source)])
    try:
        result = json.loads(output.read_text(encoding="utf-8"))
        cues = result["mouthCues"]
        end = 0.0
        for cue in cues:
            start, stop = float(cue["start"]), float(cue["end"])
            if (
                not math.isfinite(start)
                or not math.isfinite(stop)
                or start < end
                or stop < start
                or cue["value"] not in set("ABCDEFGHX")
            ):
                raise ValueError("invalid cue order, range or value")
            end = stop
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"invalid Rhubarb result: {exc}") from exc
    if sha256_file(source) != digest:
        raise HostOpError(ErrorCode.SCENE_CONFLICT, "source changed during lip-sync analysis")
    ctx.add_file("json", output)
    ctx.write_report(
        "lipsync-analysis.json",
        {
            "source_path": ctx.params.source_path,
            "source_sha256": digest,
            "recognizer": "phonetic",
            "version": (version.stdout + version.stderr).strip(),
            "mouthCues": cues,
            "rig_applied": False,
        },
    )
    ctx.metrics.update({"cues": len(cues), "rig_applied": False})
