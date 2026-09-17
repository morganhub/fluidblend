"""Facial lip-sync and expressions (B04) on the CC0 Vitruvian face fixture."""

import shutil
import subprocess

import pytest
from tests.acceptance.test_characters import install_character
from tests.acceptance.test_interactions import artifact
from tests.conftest import make_request, note

from fluidblend.adapters.ffmpeg import find_tool
from fluidblend.core.atomic import atomic_write_json, read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root
from fluidblend.core.tasks import TaskRunner

pytestmark = pytest.mark.blender

SPEECH = "Hello, my name is Vitruvian. We make a movie together, above the blue water."
HANDMADE = [
    {"start": 0.0, "end": 0.5, "value": "X"},
    {"start": 0.5, "end": 1.0, "value": "D"},
    {"start": 1.0, "end": 1.5, "value": "A"},
    {"start": 1.5, "end": 1.54, "value": "F"},
    {"start": 1.54, "end": 2.0, "value": "C"},
    {"start": 2.0, "end": 2.5, "value": "X"},
]


def install_face_character(project):
    fixture = kit_root() / "fixtures/vitruvian-face/character.blend"
    if not fixture.exists():
        pytest.skip("not_run: generate the pinned Vitruvian face fixture first")
    metadata = read_json(fixture.with_name("asset.json"))
    assert sha256_file(fixture) == metadata["sha256"]
    folder = project.root / "assets/characters/vitruvian-face/v001"
    folder.mkdir(parents=True)
    shutil.copy2(fixture, folder / "character.blend")
    manifest = {
        key: metadata[key]
        for key in (
            "asset_id",
            "version",
            "sha256",
            "license",
            "objects",
            "armature",
            "rig_profile",
            "face_profile",
        )
    }
    manifest.update(
        blend_path="assets/characters/vitruvian-face/v001/character.blend",
        license_path="licenses/vitruvian.md",
    )
    atomic_write_json(folder / "asset.json", manifest)
    return "assets/characters/vitruvian-face/v001/asset.json"


def build(project, runner):
    body = install_character(project)  # also copies the shared license and frames the shot camera
    face = install_face_character(project)
    outcome = runner.run(
        make_request(
            "shot.build",
            "face-build-001",
            target={"shot_id": "shot010"},
            parameters={
                "assets": [
                    {"manifest_path": face, "instance_id": "hero-01"},
                    {"manifest_path": body, "instance_id": "mute-01", "location": [2, 0, 0]},
                ]
            },
        )
    )
    assert outcome.exit_code == 0, outcome.result.model_dump()


def hero(**extra):
    return {"shot_id": "shot010", "instance_id": "hero-01", **extra}


def test_mouth_keys_follow_handmade_cues_exactly(project):
    runner = TaskRunner(project)
    build(project, runner)
    analysis = project.root / "reviews/handmade/lipsync-analysis.json"
    analysis.parent.mkdir(parents=True)
    atomic_write_json(
        analysis, {"source_path": "audio/none.wav", "source_sha256": "0" * 64, "mouthCues": HANDMADE}
    )
    parameters = {
        "lipsync_id": "line-01",
        "analysis_path": "reviews/handmade/lipsync-analysis.json",
        "start_frame": 11,
    }

    no_face = runner.run(
        make_request("lipsync.apply", "lips-mute", target=hero(instance_id="mute-01"), parameters=parameters)
    )
    assert no_face.result.errors[0].code == "RIG_MAPPING_REQUIRED", "a body without a face profile is refused"

    applied = runner.run(make_request("lipsync.apply", "lips-001", target=hero(), parameters=parameters))
    assert applied.exit_code == 0, applied.result.model_dump()
    report = read_json(project.root / artifact(applied.result, "lipsync-apply.json"))
    checked = {c["value"]: c for c in report["checked_cues"]}
    # 24 fps, audio time 0 on frame 11: 0.5 s -> frame 23, 1.0 s -> 35; the 0.04 s F is passed through.
    assert checked["D"]["start_frame"] == pytest.approx(23.0) and checked["A"][
        "start_frame"
    ] == pytest.approx(35.0)
    assert set(checked) == {"X", "D", "A", "C"} and all(c["passed"] for c in report["checked_cues"])
    assert checked["D"]["mouth_displacement_m"] > 0.01 > checked["A"]["mouth_displacement_m"] > 0.001
    assert checked["X"]["mouth_displacement_m"] < 1e-4
    assert ['key_blocks["aa_02"].value', 0] in report["owned_channels"]
    frames = project.root / next(a.path for a in applied.result.artifacts if a.kind == "frames")
    assert len(list((frames / "lipsync").glob("*.png"))) == 3

    twice = runner.run(
        make_request(
            "lipsync.apply", "lips-002", target=hero(), parameters={**parameters, "lipsync_id": "line-02"}
        )
    )
    assert twice.result.errors[0].code == "SCENE_CONFLICT", "two mouth tracks never share channels silently"

    for expression_id, expression, interval in (
        ("smile-01", "happy", (20, 60)),
        ("blink-01", "blink", (30, 42)),
    ):
        acted = runner.run(
            make_request(
                "expression.apply",
                f"face-{expression_id}",
                target=hero(),
                parameters={
                    "expression_id": expression_id,
                    "expression": expression,
                    "frame_range": {"start": interval[0], "end_exclusive": interval[1]},
                },
            )
        )
        assert acted.exit_code == 0, acted.result.model_dump()
        assert acted.result.metrics["face_displacement_m"] > 0.003


def speech_wav(path):
    """Offline Windows voice: real speech for Rhubarb without shipping or downloading any audio."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{SPEECH}'); $s.Dispose()"
    )
    for shell in ("pwsh", "powershell"):
        if shutil.which(shell):
            done = subprocess.run([shell, "-NoProfile", "-Command", script], capture_output=True, timeout=120)
            if done.returncode == 0 and path.exists() and path.stat().st_size > 10_000:
                return True
    return False


@pytest.mark.acceptance(
    "B04", title="Dialogue line: audio prepared, cues analysed, mouth keyed on the real face"
)
def test_B04_lipsync_from_speech(project):
    if not find_tool("ffmpeg", None) or not find_tool("rhubarb", None):
        pytest.skip("not_run: FFmpeg or Rhubarb missing")
    source = project.root / "audio/source/line-01.wav"
    source.parent.mkdir(parents=True)
    if not speech_wav(source):
        pytest.skip("not_run: no offline Windows voice (System.Speech) to synthesize a test line")
    source_hash = sha256_file(source)
    runner = TaskRunner(project)
    build(project, runner)
    prepared = runner.run(
        make_request("audio.prepare", "line-prepare", parameters={"source_path": "audio/source/line-01.wav"})
    )
    assert prepared.exit_code == 0, prepared.result.model_dump()
    wav = next(a.path for a in prepared.result.artifacts if a.kind == "audio")
    analysed = runner.run(make_request("lipsync.analyze", "line-analyze", parameters={"source_path": wav}))
    assert analysed.exit_code == 0, analysed.result.model_dump()
    assert analysed.result.metrics["cues"] >= 8
    applied = runner.run(
        make_request(
            "lipsync.apply",
            "line-apply",
            target=hero(),
            parameters={
                "lipsync_id": "line-01",
                "analysis_path": artifact(analysed.result, "lipsync-analysis.json"),
                "start_frame": 1,
            },
        )
    )
    assert applied.exit_code == 0, applied.result.model_dump()
    report = read_json(project.root / artifact(applied.result, "lipsync-apply.json"))
    shapes = {c["value"] for c in report["checked_cues"]}
    assert report["technical_pass"] and len(shapes - {"X"}) >= 3, shapes
    assert report["audio_source"]["path"] == wav and sha256_file(source) == source_hash
    duration = read_json(project.root / artifact(prepared.result, "audio-preparation.json"))[
        "duration_frames"
    ]
    last = report["frame_span"][1]
    # The mouth never runs past the audio by more than the transition and the tolerated drift.
    assert (
        last
        <= 1 + duration["numerator"] / duration["denominator"] + 2.0 + project.quality.audio_drift_max_frames
    )
    note(
        "B04",
        f"offline Windows voice -> two-pass normalization -> Rhubarb {analysed.result.metrics['cues']} cues -> "
        f"{len(report['checked_cues'])} held cues checked on shape keys ({', '.join(sorted(shapes))}), mouth up to "
        f"{applied.result.metrics['mouth_displacement_max_m'] * 1000:.1f} mm; fractional frames, source audio "
        "untouched; recognition, text, voice and performance are not approved; artistic review pending",
    )
