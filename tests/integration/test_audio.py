import math
import struct
import wave

import pytest
from tests.conftest import make_request

from fluidblend.adapters.ffmpeg import find_tool
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.tasks import TaskRunner


def audio_source(project, channels=1):
    source = project.root / "audio/source/test.wav"
    source.parent.mkdir(parents=True)
    with wave.open(str(source), "wb") as wav:
        wav.setparams((channels, 2, 44100, 0, "NONE", "not compressed"))
        wav.writeframes(
            b"".join(
                struct.pack("<h", int(6000 * math.sin(2 * math.pi * 220 * i / 44100))) * channels
                for i in range(88200)
            )
        )
    return source


@pytest.mark.parametrize("channels", [1, 2])
def test_real_audio_prepare_and_phonetic_analysis(project, channels):
    if not find_tool("ffmpeg", None) or not find_tool("rhubarb", None):
        pytest.skip("not_run: FFmpeg or Rhubarb missing")
    source = audio_source(project, channels)
    before = sha256_file(source)
    runner = TaskRunner(project)
    preparation = runner.run(
        make_request(
            "audio.prepare", "prepare-audio-001", parameters={"source_path": "audio/source/test.wav"}
        )
    )
    assert preparation.exit_code == 0, preparation.result.model_dump()
    path = project.root / next(a.path for a in preparation.result.artifacts if a.kind == "audio")
    with wave.open(str(path), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (48000, 1, 96000)
    report = read_json(
        project.root / next(a.path for a in preparation.result.artifacts if a.kind == "report")
    )
    assert report["duration_frames"] == {"numerator": 48, "denominator": 1}
    assert abs(float(report["second_pass"]["output_i"]) - (-16)) <= 1
    assert "aresample=48000" in report["filter"] and "measured_I=" in report["filter"]
    analysis = runner.run(
        make_request(
            "lipsync.analyze",
            "analyze-audio-001",
            parameters={"source_path": path.relative_to(project.root).as_posix()},
        )
    )
    assert analysis.exit_code == 0, analysis.result.model_dump()
    assert analysis.result.metrics["rig_applied"] is False
    assert sha256_file(source) == before


def test_audio_missing_tool_is_reported(project, monkeypatch):
    audio_source(project)
    monkeypatch.setattr("fluidblend.hostops.audio.find_tool", lambda *args: None)
    outcome = TaskRunner(project).run(
        make_request(
            "audio.prepare", "missing-audio-001", parameters={"source_path": "audio/source/test.wav"}
        )
    )
    assert outcome.result.errors[0].code == "MISSING_DEPENDENCY"
