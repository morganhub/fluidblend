"""Manifests of a production project (project.json, config/*.json, shots/*/shot.json)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from fluidblend.contracts.common import SCHEMA_VERSION, Fps, FrameRange, StrictModel

Profile = Literal["film", "game", "hybrid"]
AutonomyMode = Literal["inspect", "assisted", "local_autonomous", "batch_approved"]
GameEngine = Literal["godot", "web", "none"]

IDENT_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"


class Autonomy(StrictModel):
    mode: AutonomyMode = "assisted"
    approval_record: str = "state/approvals/project-scope.json"
    max_repair_attempts: int = Field(default=3, ge=0, le=10)


class Budgets(StrictModel):
    max_task_minutes: int = Field(default=20, ge=1, le=24 * 60)
    max_preview_frames: int = Field(default=240, ge=1, le=100_000)
    max_new_disk_gib: float = Field(default=5.0, ge=0.01, le=10_000)
    max_external_spend: float = Field(default=0.0, ge=0)


class PreviewSettings(StrictModel):
    width: int = Field(default=640, ge=16, le=8192)
    height: int = Field(default=360, ge=16, le=8192)
    engine: Literal["WORKBENCH", "EEVEE"] = "WORKBENCH"


class Targets(StrictModel):
    film: bool = True
    game_engine: GameEngine = "none"


class ProjectManifest(StrictModel):
    """`project.json` (example §6.2)."""

    schema_version: str = SCHEMA_VERSION
    project_id: str = Field(pattern=IDENT_PATTERN)
    name: str = Field(default="", max_length=200)
    profile: Profile = "film"
    style: str = Field(default="stylized", max_length=64)
    units: Literal["meters"] = "meters"
    fps: Fps = Field(default_factory=lambda: Fps(numerator=24, denominator=1))
    targets: Targets = Field(default_factory=Targets)
    autonomy: Autonomy = Field(default_factory=Autonomy)
    budgets: Budgets = Field(default_factory=Budgets)
    preview: PreviewSettings = Field(default_factory=PreviewSettings)
    dependency_lock: str = "dependencies.lock.json"
    created_at: str | None = None
    fluidblend_version: str | None = None


class McpLocalConfig(StrictModel):
    server_name: str = "blender"
    host: str = "localhost"
    port: int = Field(default=9876, ge=1024, le=65535)
    startup_timeout_s: float = Field(default=20.0, ge=1, le=600)
    call_timeout_s: float = Field(default=60.0, ge=1, le=3600)


class LocalConfig(StrictModel):
    """`config/local.json`: absolute machine paths, not versioned, no secrets."""

    schema_version: str = SCHEMA_VERSION
    blender_executable: str | None = None
    ffmpeg_executable: str | None = None
    ffprobe_executable: str | None = None
    gltf_validator_executable: str | None = None
    godot_executable: str | None = None
    rhubarb_executable: str | None = None
    mcp: McpLocalConfig = Field(default_factory=McpLocalConfig)
    blender_startup_timeout_s: float = Field(default=90.0, ge=5, le=3600)


class Permissions(StrictModel):
    """`config/permissions.json`: approved scope. The kit reads this file, it never writes it."""

    schema_version: str = SCHEMA_VERSION
    profile: AutonomyMode = "assisted"
    allowed_roots: list[str] = Field(default_factory=lambda: ["."])
    allowed_operations: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Operation names or `domain.*` patterns; `*` = every local operation",
    )
    protected_paths: list[str] = Field(
        default_factory=lambda: ["shots/*/approved/**", "audio/source/**", "assets/*/*/source/**"],
        description="Glob patterns (relative to the project) that the kit never modifies",
    )
    allow_new_dependencies: bool = False
    allow_network: bool = False
    approved_by: str | None = None
    approved_at: str | None = None


class QualityThresholds(StrictModel):
    schema_version: str = SCHEMA_VERSION
    foot_slide_max_m: float = Field(default=0.02, ge=0)
    contact_error_max_m: float = Field(default=0.02, ge=0)
    audio_drift_max_frames: float = Field(default=1.0, ge=0)
    loop_pose_error_max: float = Field(default=1e-3, ge=0)
    preview_missing_frames_max: int = Field(default=0, ge=0)


class ProviderRef(StrictModel):
    provider_id: str
    kind: str
    enabled: bool = False
    secret_ref: str | None = Field(
        default=None, description="Name of an environment variable, never its value"
    )
    license: str | None = None
    notes: str | None = None


class ProvidersConfig(StrictModel):
    schema_version: str = SCHEMA_VERSION
    providers: list[ProviderRef] = Field(default_factory=list)


class InstanceRef(StrictModel):
    instance_id: str = Field(pattern=IDENT_PATTERN)
    asset_id: str = Field(pattern=IDENT_PATTERN)
    rig_profile: str = "fluidblend.simple_biped/1"
    initial_location: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    clip_id: str | None = None
    phase_offset_frames: int = 0
    scale: float = Field(default=1.0, gt=0, le=10)


class CameraSpec(StrictModel):
    location: list[float] = Field(default_factory=lambda: [5.5, 0.0, 1.4], min_length=3, max_length=3)
    look_at: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0], min_length=3, max_length=3)
    focal_length_mm: float = Field(default=35.0, gt=1, le=1200)


class ShotManifest(StrictModel):
    """`shots/<shot_id>/shot.json`: declarative timeline of a shot."""

    schema_version: str = SCHEMA_VERSION
    shot_id: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange = Field(default_factory=lambda: FrameRange(start=1, end_exclusive=241))
    instances: list[InstanceRef] = Field(default_factory=list)
    props: list[InstanceRef] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    audio: list[str] = Field(default_factory=list)
    validation_state: Literal["draft", "technical_pass", "visual_review_pending", "art_approved"] = "draft"
    notes: str = ""

    @field_validator("instances")
    @classmethod
    def _unique_instances(cls, value: list[InstanceRef]) -> list[InstanceRef]:
        ids = [i.instance_id for i in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate instance_id in the shot")
        return value


class RevisionRecord(StrictModel):
    target: str
    revision: int = Field(ge=0)
    path: str
    sha256: str
    bytes: int
    updated_at: str
    origin: Literal["kit", "external_accepted", "init"] = "kit"


class RevisionsFile(StrictModel):
    schema_version: str = SCHEMA_VERSION
    revisions: dict[str, RevisionRecord] = Field(default_factory=dict)


class DependencyEntry(StrictModel):
    name: str
    version: str | None = None
    path: str | None = None
    sha256: str | None = None
    source: str | None = None
    verified_at: str | None = None
    status: str = "unverified"


class DependencyLock(StrictModel):
    schema_version: str = SCHEMA_VERSION
    dependencies: dict[str, DependencyEntry] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
