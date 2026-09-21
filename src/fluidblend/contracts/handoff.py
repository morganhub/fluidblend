"""Hand-off bundle: what this kit publishes for another kit to import (fluidunreal §5.1).

A bundle is a folder plus this manifest: a GLB, the reports that prove what came out of Blender,
the licence of everything it redistributes, and the measurements a consumer needs to check the
import rather than assume it. `reference_pose` exists for exactly that: the consumer measures the
scale and the up axis it really got instead of trusting a conversion factor.

`contacts`, `events` and `measurements` stay free-form here on purpose. Their source of truth is
`ClipManifest` in `contracts.production`; copying them verbatim keeps the bundle a transfer format
instead of a second definition that can drift.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from fluidblend.contracts.common import Fps, FrameRange, StrictModel
from fluidblend.contracts.project import IDENT_PATTERN

BUNDLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class BundleProducer(StrictModel):
    """Who made the bundle, from which project state. `external` means: wrapped, not produced here."""

    kit: Literal["fluidblend", "external"] = "fluidblend"
    version: str = Field(min_length=1, max_length=40)
    operation: str = Field(min_length=1, max_length=64)
    operation_id: str = Field(pattern=BUNDLE_ID_PATTERN)
    project_id: str = Field(pattern=IDENT_PATTERN)
    shot_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    source_revision: int = Field(default=0, ge=0)
    created_at: str = Field(min_length=1, max_length=40)


class AxisPair(StrictModel):
    up: str = Field(min_length=2, max_length=4)
    forward: str = Field(min_length=2, max_length=4)


class AxisConvention(StrictModel):
    """Written down rather than assumed: the consumer reports the conversion it applied."""

    blender: AxisPair
    gltf: AxisPair


class BundleFile(StrictModel):
    role: Literal["model", "export_report", "khronos_report", "license", "other"]
    path: str = Field(min_length=1, max_length=400, description="POSIX, relative to the bundle folder")
    format: Literal["glb", "gltf", "json", "md", "txt"] | None = None
    sha256: str = Field(pattern=SHA256_PATTERN)
    bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _contained(self) -> BundleFile:
        parts = self.path.split("/")
        if self.path.startswith("/") or ".." in parts or "" in parts or "\\" in self.path:
            raise ValueError("a bundle path stays inside the bundle folder")
        return self


class BundleValidation(StrictModel):
    """`not_run` is a result, not a failure — and never to be read as `passed`."""

    khronos: Literal["passed", "failed", "not_run"] = "not_run"
    reimport_passed: bool | None = None
    skeleton_fidelity_max_error_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ReferenceBone(StrictModel):
    """World head of a deform bone at rest, in metres, Blender space (see `axis_convention`)."""

    bone: str = Field(min_length=1, max_length=120)
    head_m: list[float] = Field(min_length=3, max_length=3)


class BundleInstance(StrictModel):
    instance_id: str = Field(pattern=IDENT_PATTERN)
    kind: Literal["character", "prop"] = "character"
    asset_id: str = Field(pattern=IDENT_PATTERN)
    asset_version: int = Field(ge=1)
    license: str = Field(min_length=1, max_length=120)
    license_file: str = Field(min_length=1, max_length=400)
    rig_profile: str | None = Field(default=None, max_length=120)
    armature: str | None = Field(default=None, max_length=120)
    skinned: bool = False
    baked: bool = False
    export_def_bones: bool = False
    bone_count: int = Field(default=0, ge=0)
    gltf_node_name: str = Field(min_length=1, max_length=200)
    reference_pose: list[ReferenceBone] = Field(default_factory=list, max_length=5)
    grips: dict[str, list[float]] = Field(default_factory=dict)


class BundleClip(StrictModel):
    clip_id: str = Field(pattern=IDENT_PATTERN)
    instance_id: str = Field(pattern=IDENT_PATTERN)
    gltf_animation_name: str = Field(min_length=1, max_length=200)
    frame_range: FrameRange
    loop: bool = False
    root_motion: Literal["in_place", "root_bone", "object"] = "in_place"
    stride_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    repetitions: int | None = Field(default=None, ge=2, le=100)
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    measurements: list[dict[str, Any]] = Field(default_factory=list)


class HandoffBundle(StrictModel):
    """`handoff-bundle.json`, the contract between this kit and an engine-side kit."""

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["handoff-bundle"] = "handoff-bundle"
    bundle_id: str = Field(pattern=BUNDLE_ID_PATTERN)
    producer: BundleProducer
    units: Literal["meters"] = "meters"
    fps: Fps
    axis_convention: AxisConvention
    files: list[BundleFile] = Field(min_length=1)
    validation: BundleValidation = Field(default_factory=BundleValidation)
    instances: list[BundleInstance] = Field(default_factory=list)
    clips: list[BundleClip] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherent(self) -> HandoffBundle:
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("two bundle files share a path")
        roles = [f.role for f in self.files]
        if roles.count("model") != 1:
            raise ValueError("a bundle carries exactly one model file")
        # Redistributing an asset without its licence is the one thing a bundle may never do.
        if self.producer.kit == "fluidblend" and "license" not in roles:
            raise ValueError("a fluidblend bundle carries its licence file")
        known = {i.instance_id for i in self.instances}
        unknown = sorted({c.instance_id for c in self.clips} - known)
        if unknown:
            raise ValueError(f"clips refer to unknown instances: {', '.join(unknown)}")
        if len({i.instance_id for i in self.instances}) != len(self.instances):
            raise ValueError("two instances share an instance_id")
        return self

    def file(self, role: str) -> BundleFile | None:
        return next((f for f in self.files if f.role == role), None)
