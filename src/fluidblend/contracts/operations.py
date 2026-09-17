"""Registry of business operations, typed requests and parameter models.

Every operation declares: backend (`host` or `blender`), class (`read`, `write`, `render`,
`export`), batch (`P0`, `P1`, `P2`) and real availability. An unavailable operation stays
listed in the help but returns `UNSUPPORTED_CAPABILITY` - never a fake success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from fluidblend.contracts.common import SCHEMA_VERSION, StrictModel
from fluidblend.contracts.production import (
    AdjustmentRevertParams,
    AnimationApplyParams,
    AnimationBakeParams,
    AnimationCreateParams,
    AnimationLoopParams,
    AudioPrepareParams,
    CharacterInspectParams,
    ContactLockParams,
    InteractionApplyParams,
    InteractionPlanParams,
    InteractionValidateParams,
    LipsyncAnalyzeParams,
    RigMapParams,
    RigValidateParams,
    ShotBuildParams,
    ToolInspectParams,
    ToolRegisterParams,
    ToolTestParams,
)
from fluidblend.contracts.project import IDENT_PATTERN

Backend = Literal["host", "blender"]
OpClass = Literal["read", "write", "render", "export"]
Lot = Literal["P0", "P1", "P2"]
LIVE_OPERATIONS = frozenset({"scene.inspect", "scene.audit", "animation.retime", "scene.checkpoint"})


class Target(StrictModel):
    shot_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    instance_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    clip_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    asset_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    expected_revision: int | None = Field(default=None, ge=0)


class OperationRequest(StrictModel):
    """Common envelope (§6.4). `parameters` is validated by the operation's own model."""

    schema_version: str = SCHEMA_VERSION
    operation: str = Field(pattern=r"^[a-z_]+\.[a-z_]+$")
    operation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")
    project_id: str = Field(pattern=IDENT_PATTERN)
    target: Target = Field(default_factory=Target)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False

    @field_validator("schema_version")
    @classmethod
    def _supported_schema(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version {value!r} is not supported (expected {SCHEMA_VERSION!r}); explicit migration required"
            )
        return value


# --- Per-operation parameters --------------------------------------------------------------


class NoParams(StrictModel):
    pass


class SceneBuildParams(StrictModel):
    preset: Literal["two_characters_prop"] = "two_characters_prop"
    frames: int = Field(default=240, ge=2, le=100_000)
    seed: int = Field(default=0, ge=0)


class SceneInspectParams(StrictModel):
    include_actions: bool = True
    include_bones: bool = False


class SceneCheckpointParams(StrictModel):
    label: str = Field(default="manual", pattern=r"^[A-Za-z0-9._-]{1,64}$")


class AnimationRetimeParams(StrictModel):
    duration_scale: float = Field(gt=0.05, le=20, description="1.2 = duration x 1.2, therefore slower")
    preserve_contact_markers: bool = True
    output_variant: str = Field(pattern=IDENT_PATTERN)
    preview_samples: int = Field(
        default=8, ge=0, le=64, description="Before/after frames rendered with Workbench"
    )


class ShotPreviewParams(StrictModel):
    frame_start: int | None = None
    frame_end_exclusive: int | None = None
    step: int = Field(default=1, ge=1, le=100)
    engine: Literal["WORKBENCH", "EEVEE"] | None = None
    width: int | None = Field(default=None, ge=16, le=8192)
    height: int | None = Field(default=None, ge=16, le=8192)
    label: str = Field(default="preview", pattern=r"^[A-Za-z0-9._-]{1,64}$")


class GameExportParams(StrictModel):
    output_name: str = Field(pattern=r"^[A-Za-z0-9._-]{1,80}$")
    instance_ids: list[str] | None = None
    reimport_check: bool = True
    export_def_bones: bool = False
    export_influence_nb: int = Field(default=4, ge=1, le=8)
    animation_mode: Literal["ACTIONS", "ACTIVE_ACTIONS", "NLA_TRACKS", "SCENE"] = "ACTIONS"
    slide_to_zero: bool = True
    include_cameras: bool = False
    include_lights: bool = False


class FilmAssembleParams(StrictModel):
    shot_ids: list[str] = Field(min_length=1)
    output_name: str = Field(default="film-preview", pattern=r"^[A-Za-z0-9._-]{1,80}$")
    audio_path: str | None = None


class ShotValidateParams(StrictModel):
    require_preview: bool = True


class ProjectPlanParams(StrictModel):
    request_path: str


@dataclass(frozen=True)
class OperationSpec:
    name: str
    params_model: type[StrictModel]
    backend: Backend
    op_class: OpClass
    lot: Lot
    available: bool
    description: str
    requires_shot: bool = False
    creates_version: bool = False
    cli_command: str | None = None
    """Dedicated CLI subcommand when the operation does not go through `fluidblend run`."""

    def execution_contract(self) -> dict[str, Any]:
        """Machine-readable execution scope shared by CLI help and generated schemas."""
        required = ["blender.batch"] if self.backend == "blender" else []
        optional = []
        if self.name in ("audio.prepare", "film.assemble"):
            required.append("video.ffmpeg")
        if self.name == "film.assemble":
            required.append("video.ffprobe")
        if self.name == "shot.preview":
            optional.extend(["video.ffmpeg", "video.ffprobe"])
        if self.name == "lipsync.analyze":
            required.append("audio.rhubarb")
        if self.name == "game.export":
            optional.append("gltf.khronos_validator")
        targets = ["shot_id"] if self.requires_shot else []
        if self.name in {
            "character.inspect",
            "rig.map",
            "rig.validate",
            "animation.create",
            "animation.apply",
            "animation.loop",
            "animation.bake",
            "animation.retime",
            "adjustment.preview",
            "adjustment.apply",
            "adjustment.revert",
        }:
            targets.append("instance_id")
        if self.name in {"animation.loop", "animation.retime"}:
            targets.append("clip_id")
        paths = [name for name in self.params_model.model_fields if name.endswith("_path")]
        if self.name == "shot.build":
            paths.append("assets[].manifest_path")
        return {
            "modes": (["batch", "live"] if self.name in LIVE_OPERATIONS else ["batch"])
            if self.available and not self.cli_command
            else [],
            "required_dependencies": required,
            "optional_dependencies": optional,
            "live_dependencies": ["blender.mcp_live", "blender.runtime_addon"]
            if self.name in LIVE_OPERATIONS
            else [],
            "required_targets": targets,
            "input_paths": paths,
            "publication": "shot_revision_and_reports" if self.creates_version else "reports_and_artifacts",
            "cli_command": self.cli_command,
        }


def _spec(
    name: str,
    params: type[StrictModel],
    backend: Backend,
    op_class: OpClass,
    lot: Lot,
    description: str,
    *,
    available: bool = True,
    requires_shot: bool = False,
    creates_version: bool = False,
    cli: str | None = None,
) -> OperationSpec:
    return OperationSpec(
        name, params, backend, op_class, lot, available, description, requires_shot, creates_version, cli
    )


OPERATIONS: dict[str, OperationSpec] = {
    s.name: s
    for s in [
        # Environment
        _spec(
            "environment.doctor",
            NoParams,
            "host",
            "read",
            "P0",
            "Diagnose the workstation and its capabilities",
            cli="fluidblend doctor --project <p>",
        ),
        _spec(
            "capabilities.list",
            NoParams,
            "host",
            "read",
            "P0",
            "Read capabilities.json",
            cli="fluidblend capabilities --project <p>",
        ),
        _spec(
            "providers.check",
            NoParams,
            "host",
            "read",
            "P0",
            "Check the declared providers (none enabled in P0)",
        ),
        # Project
        _spec(
            "project.init",
            NoParams,
            "host",
            "write",
            "P0",
            "Scaffold a project",
            cli="fluidblend init --path <p>",
        ),
        _spec(
            "project.inspect",
            NoParams,
            "host",
            "read",
            "P0",
            "Inspect manifests, state and revisions",
            cli="fluidblend inspect --project <p>",
        ),
        _spec(
            "project.plan",
            ProjectPlanParams,
            "host",
            "read",
            "P0",
            "Plan a request without mutating anything",
            cli="fluidblend plan --project <p> --request <r>",
        ),
        _spec(
            "project.resume",
            NoParams,
            "host",
            "read",
            "P0",
            "Rebuild the state and list what can be resumed",
            cli="fluidblend resume --project <p>",
        ),
        # Scene
        _spec(
            "scene.inspect",
            SceneInspectParams,
            "blender",
            "read",
            "P0",
            "JSON summary of a shot",
            requires_shot=True,
        ),
        _spec(
            "scene.audit",
            NoParams,
            "blender",
            "read",
            "P0",
            "Technical checks on a scene",
            requires_shot=True,
        ),
        _spec(
            "scene.build",
            SceneBuildParams,
            "blender",
            "write",
            "P0",
            "Build the demonstration scene of a shot",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "scene.checkpoint",
            SceneCheckpointParams,
            "host",
            "write",
            "P0",
            "Snapshot of the current work file",
            requires_shot=True,
        ),
        # Character (P1)
        _spec(
            "character.inspect",
            CharacterInspectParams,
            "blender",
            "read",
            "P1",
            "Audit a character",
            requires_shot=True,
        ),
        _spec(
            "rig.validate",
            RigValidateParams,
            "blender",
            "read",
            "P1",
            "Test poses and rig checks",
            requires_shot=True,
        ),
        _spec(
            "rig.map", RigMapParams, "host", "write", "P1", "Semantic mapping of a rig", requires_shot=True
        ),
        # Animation
        _spec(
            "animation.create",
            AnimationCreateParams,
            "blender",
            "write",
            "P1",
            "Create a clip from the library",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "animation.apply",
            AnimationApplyParams,
            "blender",
            "write",
            "P1",
            "Apply a clip to an instance",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "animation.retime",
            AnimationRetimeParams,
            "blender",
            "write",
            "P0",
            "Slow down or speed up a clip on a variant",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "animation.loop",
            AnimationLoopParams,
            "blender",
            "write",
            "P1",
            "Loop a clip",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "animation.retarget", NoParams, "blender", "write", "P1", "Bounded retargeting", available=False
        ),
        _spec(
            "animation.bake",
            AnimationBakeParams,
            "blender",
            "write",
            "P1",
            "Bake constraints/NLA",
            requires_shot=True,
            creates_version=True,
        ),
        # Interactions (P1)
        _spec(
            "interaction.plan",
            InteractionPlanParams,
            "host",
            "read",
            "P1",
            "Plan a bounded prop hand-off between two characters",
            requires_shot=True,
        ),
        _spec(
            "interaction.apply",
            InteractionApplyParams,
            "blender",
            "write",
            "P1",
            "Apply a planned prop hand-off on a new version",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "interaction.validate",
            InteractionValidateParams,
            "blender",
            "read",
            "P1",
            "Measure contacts, hand-off jump and prop ownership",
            requires_shot=True,
        ),
        # Audio / face (P1)
        _spec("audio.prepare", AudioPrepareParams, "host", "write", "P1", "Normalize an audio track"),
        _spec("lipsync.analyze", LipsyncAnalyzeParams, "host", "read", "P1", "Rhubarb -> mouth cues"),
        _spec("lipsync.apply", NoParams, "blender", "write", "P1", "Mouth cues -> face", available=False),
        _spec("expression.apply", NoParams, "blender", "write", "P1", "Facial expressions", available=False),
        # Adjustment (P1)
        _spec(
            "adjustment.preview",
            ContactLockParams,
            "blender",
            "read",
            "P1",
            "Measure and render an adjustment before/after without saving it",
            requires_shot=True,
        ),
        _spec(
            "adjustment.apply",
            ContactLockParams,
            "blender",
            "write",
            "P1",
            "Apply an adjustment as an additive layer on a new version",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "adjustment.revert",
            AdjustmentRevertParams,
            "blender",
            "write",
            "P1",
            "Remove an applied adjustment on a new version",
            requires_shot=True,
            creates_version=True,
        ),
        # Film
        _spec(
            "shot.build",
            ShotBuildParams,
            "blender",
            "write",
            "P1",
            "Assemble a shot from the assets",
            requires_shot=True,
            creates_version=True,
        ),
        _spec(
            "shot.preview",
            ShotPreviewParams,
            "blender",
            "render",
            "P0",
            "Render the preview of a shot then assemble it",
            requires_shot=True,
        ),
        _spec(
            "shot.validate",
            ShotValidateParams,
            "host",
            "read",
            "P0",
            "Check the frames, video and evidence of a shot",
            requires_shot=True,
        ),
        _spec("film.assemble", FilmAssembleParams, "host", "render", "P0", "Concatenate the shot previews"),
        # Game
        _spec(
            "game.export",
            GameExportParams,
            "blender",
            "export",
            "P0",
            "Export a GLB and re-import it",
            requires_shot=True,
        ),
        _spec(
            "game.import_test",
            NoParams,
            "host",
            "read",
            "P1",
            "Import into the target engine",
            available=False,
        ),
        _spec("game.smoke_test", NoParams, "host", "read", "P1", "Launch the prototype", available=False),
        # Tasks
        _spec(
            "task.status",
            NoParams,
            "host",
            "read",
            "P0",
            "State of a task",
            cli="fluidblend task status --project <p> --id <t>",
        ),
        _spec(
            "task.cancel",
            NoParams,
            "host",
            "write",
            "P0",
            "Stop the identified worker of a task",
            cli="fluidblend task cancel --project <p> --id <t>",
        ),
        _spec(
            "task.reconcile",
            NoParams,
            "host",
            "write",
            "P0",
            "Reconcile a task in an uncertain state",
            cli="fluidblend task reconcile --project <p> --id <t>",
        ),
        # Tools (P1)
        _spec("tool.inspect", ToolInspectParams, "host", "read", "P1", "Inspect a declarative custom tool"),
        _spec(
            "tool.test",
            ToolTestParams,
            "blender",
            "read",
            "P1",
            "Run the declared tests of a custom tool on a shot",
            requires_shot=True,
        ),
        _spec(
            "tool.register", ToolRegisterParams, "host", "write", "P1", "Register a custom tool that passed"
        ),
    ]
}


class RequestValidationError(ValueError):
    def __init__(self, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.details = details or []


def validate_request(payload: dict[str, Any]) -> tuple[OperationRequest, StrictModel, OperationSpec]:
    """Validate the envelope, then the parameters against the operation model."""
    try:
        request = OperationRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError("invalid request", exc.errors(include_url=False)) from exc
    spec = OPERATIONS.get(request.operation)
    if spec is None:
        raise RequestValidationError(f"unknown operation: {request.operation}")
    try:
        params = spec.params_model.model_validate(request.parameters)
    except ValidationError as exc:
        raise RequestValidationError(
            f"invalid parameters for {request.operation}", exc.errors(include_url=False)
        ) from exc
    if spec.requires_shot and not request.target.shot_id:
        raise RequestValidationError(f"{request.operation} requires target.shot_id")
    return request, params, spec
