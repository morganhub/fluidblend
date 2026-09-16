from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import make_request

from fluidblend.contracts import OPERATIONS, FrameRange, OperationResult, validate_request
from fluidblend.contracts.common import Fps
from fluidblend.contracts.operations import RequestValidationError
from fluidblend.contracts.schema_export import build_schemas, check_up_to_date, export_all


def test_frame_range_half_open_to_blender_inclusive():
    rng = FrameRange(start=1, end_exclusive=241)
    assert rng.count == 240
    assert rng.to_blender_inclusive() == (1, 240)
    assert FrameRange.from_blender_inclusive(1, 240) == rng
    with pytest.raises(ValueError):
        FrameRange(start=10, end_exclusive=10)


def test_fps_rational():
    fps = Fps(numerator=30000, denominator=1001)
    assert abs(fps.as_float() - 29.97) < 0.001
    assert fps.blender_settings() == (30000, 1001.0)


def test_validate_request_accepts_known_operation():
    request, params, spec = validate_request(
        make_request(
            "animation.retime",
            "retime-001",
            target={"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk"},
            parameters={"duration_scale": 1.2, "output_variant": "walk-slower-v001"},
        )
    )
    assert spec.backend == "blender" and spec.op_class == "write"
    assert params.duration_scale == 1.2
    assert request.target.expected_revision is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"parameters": {"duration_scale": 1.2, "output_variant": "x", "shell": "rm -rf /"}},
        {"parameters": {"duration_scale": 0.0, "output_variant": "x"}},
        {"operation": "animation.explode"},
        {"schema_version": "0.9"},
        {"operation_id": "a"},
        {"target": {"shot_id": "../escape"}},
    ],
)
def test_validate_request_rejects_invalid(mutation):
    payload = make_request(
        "animation.retime",
        "retime-001",
        target={"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk"},
        parameters={"duration_scale": 1.2, "output_variant": "x"},
    )
    payload.update(mutation)
    with pytest.raises(RequestValidationError):
        validate_request(payload)


def test_shot_required_for_scene_ops():
    with pytest.raises(RequestValidationError):
        validate_request(make_request("scene.build", "build-001"))


def test_unavailable_operations_are_declared_not_hidden():
    unavailable = [name for name, spec in OPERATIONS.items() if not spec.available]
    assert "animation.retarget" in unavailable and "lipsync.apply" in unavailable
    assert all(OPERATIONS[n].lot in ("P1", "P2") for n in unavailable)


def test_operation_result_defaults_are_empty_not_missing():
    result = OperationResult(operation_id="op-001", operation="scene.inspect", status="succeeded")
    data = result.model_dump()
    assert (
        data["artifacts"] == []
        and data["errors"] == []
        and data["checkpoint_id"] is None
        and data["new_revision"] is None
    )


def test_schema_export_is_deterministic(tmp_path: Path):
    written = export_all(tmp_path)
    assert (tmp_path / "operation-request.json").exists() and (
        tmp_path / "operations" / "animation.retime.json"
    ).exists()
    assert check_up_to_date(tmp_path) == []
    first = {p.name: p.read_text(encoding="utf-8") for p in written}
    export_all(tmp_path)
    assert {p.name: p.read_text(encoding="utf-8") for p in written} == first
    schemas = build_schemas()
    assert schemas["operations/animation.retime"]["x-fluidblend"]["available"] is True
    assert schemas["operations/lipsync.apply"]["x-fluidblend"]["available"] is False


def test_repo_schemas_are_up_to_date():
    stale = check_up_to_date(Path(__file__).resolve().parents[2] / "schemas")
    assert stale == [], f"stale schemas: {stale} -> `fluidblend schema export`"
