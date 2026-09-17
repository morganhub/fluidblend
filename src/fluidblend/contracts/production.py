"""Versioned production inputs; runtime receives plain JSON."""

import math
from typing import Literal

from pydantic import Field, field_validator

from fluidblend.contracts.common import FrameRange, StrictModel
from fluidblend.contracts.project import IDENT_PATTERN


class CharacterInspectParams(StrictModel):
    include_bones: bool = True


class RigMapParams(StrictModel):
    inspection_path: str
    profile_id: Literal["rigify/0.6.10"] = "rigify/0.6.10"
    controls: dict[str, str | None] = Field(default_factory=dict)


class RigValidateParams(StrictModel):
    profile_path: str | None = None
    preview: bool = True


class AssetPlacement(StrictModel):
    manifest_path: str
    instance_id: str = Field(pattern=IDENT_PATTERN)
    location: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)

    @field_validator("location")
    @classmethod
    def finite_location(cls, value):
        if not all(math.isfinite(v) for v in value):
            raise ValueError("asset location must be finite")
        return value


class ShotBuildParams(StrictModel):
    assets: list[AssetPlacement] = Field(min_length=1)
    import_mode: Literal["append"] = "append"


class AssetManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    asset_id: str = Field(pattern=IDENT_PATTERN)
    version: int = Field(ge=1)
    blend_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: str = Field(min_length=1)
    license_path: str
    objects: list[str] = Field(min_length=1)
    armature: str
    rig_profile: str


class RigProfile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    controls: dict[str, str | None]
    missing_controls: list[str] = Field(default_factory=list)
    unsupported_operations: list[str] = Field(default_factory=list)
    source_sha256: str
    instance_id: str


class AnimationCreateParams(StrictModel):
    preset: Literal["idle_neutral", "turn", "look_at", "reach", "react"]
    output_clip: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange = Field(default_factory=lambda: FrameRange(start=1, end_exclusive=49))
    amplitude: float = Field(default=0.3, ge=0, le=0.6)
    seed: int = Field(default=0, ge=0)
    stage: Literal["blocking", "spline", "polish"] = "spline"
    profile_path: str | None = None


class AnimationApplyParams(StrictModel):
    clip_id: str = Field(pattern=IDENT_PATTERN)
    start_frame: int = Field(default=1, ge=-100000, le=1_000_000)


class AnimationLoopParams(StrictModel):
    output_clip: str = Field(pattern=IDENT_PATTERN)
    repetitions: int = Field(default=2, ge=2, le=100)


class AnimationBakeParams(StrictModel):
    output_clip: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange
    step: int = Field(default=1, ge=1, le=10)


class AudioPrepareParams(StrictModel):
    source_path: str
    integrated_lufs: float = Field(default=-16, ge=-30, le=-5)
    true_peak_db: float = Field(default=-1.5, ge=-9, le=0)
    loudness_range_lu: float = Field(default=11, ge=1, le=20)


class LipsyncAnalyzeParams(StrictModel):
    source_path: str


class ContactWindow(StrictModel):
    effector: str = Field(min_length=1)
    support_instance_id: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange
    anchor: list[float] = Field(min_length=3, max_length=3)

    @field_validator("anchor")
    @classmethod
    def finite_anchor(cls, value):
        if not all(math.isfinite(v) for v in value):
            raise ValueError("contact anchor must be finite")
        return value


class ClipEvent(StrictModel):
    name: str = Field(pattern=IDENT_PATTERN)
    frame: float = Field(ge=-100000, le=1_000_001)


class ClipManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    clip_id: str = Field(pattern=IDENT_PATTERN)
    action: str = Field(min_length=1)
    slot: str = Field(min_length=1)
    rig_profile: str = Field(min_length=1)
    frame_range: FrameRange
    root_motion: Literal["in_place", "root_bone", "object"]
    contacts: list[ContactWindow]
    events: list[ClipEvent]
    layer: str = Field(min_length=1)
    owned_channels: list[tuple[str, int]] = Field(min_length=1)
    loop: bool = False
    preset: str | None = None
    seed: int | None = Field(default=None, ge=0)
    amplitude: float | None = Field(default=None, ge=0, le=0.6)
    stage: Literal["blocking", "spline", "polish"] | None = None
    limits: list[str] = Field(default_factory=list)
    source_clip: str | None = None
    repetitions: int | None = Field(default=None, ge=2, le=100)
    loop_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("owned_channels")
    @classmethod
    def unique_channels(cls, value):
        if len(value) != len(set(value)) or any(index < 0 or not path for path, index in value):
            raise ValueError("owned channels must be unique valid path/index pairs")
        return value


class ClipIndex(ClipManifest):
    source_blend: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
