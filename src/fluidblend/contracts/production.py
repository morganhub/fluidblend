"""Versioned production inputs; runtime receives plain JSON."""

import math
from typing import Annotated, Literal

from pydantic import Discriminator, Field, RootModel, Tag, field_validator, model_validator

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


def _finite_point(value):
    if value is not None and not all(math.isfinite(v) for v in value):
        raise ValueError("point coordinates must be finite")
    return value


class AssetPlacement(StrictModel):
    manifest_path: str
    instance_id: str = Field(pattern=IDENT_PATTERN)
    location: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    rotation_z: float = Field(
        default=0.0, ge=-2 * math.pi, le=2 * math.pi, description="Placement yaw in radians"
    )

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
    kind: Literal["character", "prop"] = "character"
    armature: str | None = None
    rig_profile: str | None = None
    face_profile: str | None = Field(
        default=None, description="Semantic face mapping of a character, e.g. charmorph-l3/1; None = no face"
    )
    root_object: str | None = Field(default=None, description="Prop object that carries the instance")
    grips: dict[str, list[float]] = Field(
        default_factory=dict, description="Named grip points in the prop root's local space, metres"
    )

    @model_validator(mode="after")
    def kind_is_complete(self):
        if self.kind == "character" and not (self.armature and self.rig_profile):
            raise ValueError("a character asset needs armature and rig_profile")
        if self.kind == "prop":
            if self.root_object not in self.objects:
                raise ValueError("a prop asset needs root_object among its objects")
            if "primary" not in self.grips:
                raise ValueError("a prop asset needs a primary grip")
            if self.armature or self.rig_profile or self.face_profile:
                raise ValueError("a prop asset carries no armature or rig profile")
        for name, point in self.grips.items():
            if not name or len(point) != 3:
                raise ValueError("grips are named 3D points")
            _finite_point(point)
        return self


class RigProfile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str
    controls: dict[str, str | None]
    missing_controls: list[str] = Field(default_factory=list)
    unsupported_operations: list[str] = Field(default_factory=list)
    source_sha256: str
    instance_id: str


class AnimationCreateParams(StrictModel):
    preset: Literal["idle_neutral", "walk", "turn", "look_at", "reach", "take_prop", "give_prop", "react"]
    output_clip: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange = Field(default_factory=lambda: FrameRange(start=1, end_exclusive=49))
    amplitude: float = Field(
        default=0.3,
        ge=0,
        le=0.6,
        description="Recipe scale; for walk the stride per cycle is 2 x amplitude metres",
    )
    seed: int = Field(default=0, ge=0)
    stage: Literal["blocking", "spline", "polish"] = "spline"
    profile_path: str | None = None
    hand: Literal["left", "right"] = Field(default="right", description="take_prop / give_prop only")
    prop_instance_id: str | None = Field(
        default=None,
        pattern=IDENT_PATTERN,
        description="take_prop: static prop whose primary grip is reached",
    )
    target_point: list[float] | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="give_prop: world point the hand extends to, metres",
    )

    @field_validator("target_point")
    @classmethod
    def finite_target(cls, value):
        return _finite_point(value)

    @model_validator(mode="after")
    def hand_recipe_inputs(self):
        if self.preset == "take_prop" and not self.prop_instance_id:
            raise ValueError("take_prop needs prop_instance_id")
        if self.preset == "give_prop" and self.target_point is None:
            raise ValueError("give_prop needs target_point")
        if self.preset not in ("take_prop", "give_prop") and (self.prop_instance_id or self.target_point):
            raise ValueError("prop_instance_id and target_point belong to take_prop / give_prop")
        return self


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
    rigid_limbs: bool = Field(
        default=False,
        description=(
            "Disable IK chain stretch in the new work version before sampling. Compressed limbs carry a "
            "non-uniform scale that neither baked TRS keys nor glTF can represent; the pose change is "
            "measured and reported, never hidden"
        ),
    )


class AnimationRetargetParams(StrictModel):
    """Bounded retargeting: one named preset between two known rig profiles, never a universal solver."""

    preset: Literal["simple_biped_to_rigify"] = "simple_biped_to_rigify"
    source_instance_id: str = Field(pattern=IDENT_PATTERN)
    source_clip: str = Field(pattern=IDENT_PATTERN, description="Clip assigned to the source instance")
    output_clip: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange
    test_poses: int = Field(
        default=3, ge=2, le=9, description="Poses transferred and measured before the rest"
    )

    @model_validator(mode="after")
    def bounded_length(self):
        length = self.frame_range.end_exclusive - self.frame_range.start
        if not 2 <= length <= 600:
            raise ValueError("retarget frame_range must hold 2 to 600 frames")
        return self


class GameImportTestParams(StrictModel):
    export_path: str = Field(description="Published .glb from game.export, project-relative")
    template: Literal["godot"] = "godot"


class GameSmokeTestParams(StrictModel):
    game_dir: str = Field(description="Game folder published by game.import_test, project-relative")


class AudioPrepareParams(StrictModel):
    source_path: str
    integrated_lufs: float = Field(default=-16, ge=-30, le=-5)
    true_peak_db: float = Field(default=-1.5, ge=-9, le=0)
    loudness_range_lu: float = Field(default=11, ge=1, le=20)


class LipsyncAnalyzeParams(StrictModel):
    source_path: str


class LipsyncApplyParams(StrictModel):
    """Key the character's mouth from a published `lipsync-analysis.json` (Rhubarb cues A-H, X)."""

    lipsync_id: str = Field(pattern=IDENT_PATTERN)
    analysis_path: str
    start_frame: int = Field(default=1, ge=-100000, le=1_000_000, description="Frame of audio time 0")
    transition_frames: float = Field(
        default=2.0, ge=0.5, le=6, description="Cross-fade between two mouth shapes, shortened on short cues"
    )
    strength: float = Field(default=1.0, ge=0.1, le=1.0)
    preview_samples: int = Field(default=4, ge=0, le=8, description="Face close-ups at cue midpoints")


class ExpressionApplyParams(StrictModel):
    expression_id: str = Field(pattern=IDENT_PATTERN)
    expression: Literal["happy", "sad", "angry", "scared", "blink"]
    frame_range: FrameRange
    strength: float = Field(default=1.0, ge=0.05, le=1.0)
    ease_frames: float = Field(default=4.0, ge=1, le=24, description="Ease in and out inside frame_range")

    @model_validator(mode="after")
    def eases_fit(self):
        if self.frame_range.end_exclusive - 1 - self.frame_range.start < 2 * self.ease_frames:
            raise ValueError("frame_range is shorter than the ease in plus the ease out")
        return self


class ContactWindow(StrictModel):
    effector: str = Field(min_length=1)
    control_point: str = Field(min_length=1, description="Evaluated bone whose head is measured")
    support_instance_id: str | None = Field(
        default=None, pattern=IDENT_PATTERN, description="None = static world ground"
    )
    frame_range: FrameRange
    anchor: list[float] = Field(
        min_length=3,
        max_length=3,
        description="Control point at the window start, in support space (rig object space for the world)",
    )

    @field_validator("anchor")
    @classmethod
    def finite_anchor(cls, value):
        if not all(math.isfinite(v) for v in value):
            raise ValueError("contact anchor must be finite")
        return value


class ClipEvent(StrictModel):
    name: str = Field(pattern=IDENT_PATTERN)
    frame: float = Field(ge=-100000, le=1_000_001)


class Measurement(StrictModel):
    """A figure with its definition (§16.1); `passed` is None when no tolerance gates it."""

    kind: Literal[
        "foot_slide",
        "contact_slide",
        "contact_error",
        "loop_pose",
        "loop_velocity",
        "retarget_limb_direction",
        "handoff_jump",
        "handoff_rotation_jump",
    ]
    effector: str = Field(min_length=1)
    control_point: str = Field(min_length=1)
    space: str = Field(min_length=1)
    frame_range: FrameRange
    sampling_step: int = Field(ge=1)
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["m", "m/frame", "rad", "deg"]
    tolerance: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    passed: bool | None = None


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
    root_motion_channels: list[tuple[str, int]] = Field(default_factory=list)
    stride_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    measurements: list[Measurement] = Field(default_factory=list)

    @field_validator("owned_channels")
    @classmethod
    def unique_channels(cls, value):
        if len(value) != len(set(value)) or any(index < 0 or not path for path, index in value):
            raise ValueError("owned channels must be unique valid path/index pairs")
        return value


MIN_REACH_FRAMES = 8


class Participant(StrictModel):
    instance_id: str = Field(pattern=IDENT_PATTERN)
    hand: Literal["left", "right"]


class InteractionPlanParams(StrictModel):
    """Bounded prop hand-off: the giver holds the prop, both reach, ownership moves once."""

    interaction_id: str = Field(pattern=IDENT_PATTERN)
    kind: Literal["prop_handoff"] = "prop_handoff"
    giver: Participant
    receiver: Participant
    prop_instance_id: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange
    handoff_frame: int = Field(ge=-100000, le=1_000_000)
    overlap_frames: int = Field(
        default=6, ge=2, le=48, description="Shared hold on each side of the hand-off"
    )
    meeting_point: list[float] | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="World point; computed from the shoulders if omitted",
    )

    @field_validator("meeting_point")
    @classmethod
    def finite_meeting_point(cls, value):
        return _finite_point(value)

    @model_validator(mode="after")
    def windows_fit(self):
        if len({self.giver.instance_id, self.receiver.instance_id, self.prop_instance_id}) != 3:
            raise ValueError("giver, receiver and prop must be three distinct instances")
        reach_in = self.handoff_frame - self.overlap_frames - self.frame_range.start
        reach_out = self.frame_range.end_exclusive - 1 - (self.handoff_frame + self.overlap_frames)
        if reach_in < MIN_REACH_FRAMES or reach_out < MIN_REACH_FRAMES:
            raise ValueError(f"each reach needs at least {MIN_REACH_FRAMES} frames around the shared hold")
        return self


class InteractionWindow(StrictModel):
    name: Literal["giver_holds", "shared_hold", "receiver_holds"]
    participant: str = Field(pattern=IDENT_PATTERN)
    grip: str = Field(min_length=1)
    frame_range: FrameRange


class Ownership(StrictModel):
    owner_instance_id: str = Field(pattern=IDENT_PATTERN)
    frame_range: FrameRange


class InteractionPlan(InteractionPlanParams):
    """Reviewable choreography derived from the parameters; nothing is written to a scene."""

    schema_version: Literal["1.0"] = "1.0"
    shot_id: str = Field(pattern=IDENT_PATTERN)
    windows: list[InteractionWindow]
    ownership: list[Ownership] = Field(min_length=2, max_length=2)
    events: list[ClipEvent]


class InteractionApplyParams(StrictModel):
    plan_path: str


class InteractionValidateParams(StrictModel):
    interaction_id: str = Field(pattern=IDENT_PATTERN)


class ContactLockParams(StrictModel):
    """`contact_lock`: hold one IK effector on its anchor over a stance window (§12.3)."""

    adjustment_id: str = Field(pattern=IDENT_PATTERN)
    tool: Literal["contact_lock"] = "contact_lock"
    custom_tool_id: str | None = Field(
        default=None, pattern=IDENT_PATTERN, description="Registered custom tool whose narrower bounds apply"
    )
    effector: Literal["left_foot", "right_foot", "left_hand", "right_hand"]
    frame_range: FrameRange
    support_instance_id: str | None = Field(
        default=None,
        pattern=IDENT_PATTERN,
        description="None = static world; else the contact is held in that instance's space",
    )
    blend_frames: int = Field(default=3, ge=1, le=24, description="Ramp in and out around the window")
    max_correction_m: float = Field(
        default=0.15, gt=0, le=0.5, description="Above this drift the window is travel, not a slide: refused"
    )
    preview_samples: int = Field(default=4, ge=0, le=16, description="Before/after frames (preview only)")

    @model_validator(mode="after")
    def window_is_long_enough(self):
        if self.frame_range.end_exclusive - self.frame_range.start < 2:
            raise ValueError("a contact window needs at least 2 frames")
        return self


class LookAtTargetParams(StrictModel):
    """`look_at_target`: turn the head towards a point or an instance over a window (§12.3)."""

    adjustment_id: str = Field(pattern=IDENT_PATTERN)
    tool: Literal["look_at_target"]
    frame_range: FrameRange
    target_point: list[float] | None = Field(default=None, description="World point, metres")
    target_instance_id: str | None = Field(
        default=None, pattern=IDENT_PATTERN, description="Instance origin, followed on every frame"
    )
    blend_frames: int = Field(default=8, ge=1, le=48, description="Ramp in and out around the window")
    max_angle_deg: float = Field(
        default=60.0, gt=0, le=80, description="Beyond this head turn the request is refused, never clamped"
    )
    max_step_deg: float = Field(
        default=12.0, gt=0, le=45, description="Largest head rotation per frame, ramps included"
    )
    preview_samples: int = Field(default=4, ge=0, le=16, description="Before/after frames (preview only)")

    @model_validator(mode="after")
    def one_finite_target(self):
        if (self.target_point is None) == (self.target_instance_id is None):
            raise ValueError("give exactly one of target_point and target_instance_id")
        if self.target_point is not None:
            if len(self.target_point) != 3:
                raise ValueError("target_point is a 3D point")
            _finite_point(self.target_point)
        if self.frame_range.end_exclusive - self.frame_range.start < 2:
            raise ValueError("a gaze window needs at least 2 frames")
        return self


def _adjustment_tool(value) -> str:
    # Requests written before the second tool carry no `tool`: they are contact_lock requests.
    tool = value.get("tool", "contact_lock") if isinstance(value, dict) else getattr(value, "tool", None)
    return tool if tool in ("contact_lock", "look_at_target") else "contact_lock"


class AdjustmentParams(
    RootModel[
        Annotated[
            Annotated[ContactLockParams, Tag("contact_lock")]
            | Annotated[LookAtTargetParams, Tag("look_at_target")],
            Discriminator(_adjustment_tool),
        ]
    ]
):
    """Parameters of `adjustment.preview` / `adjustment.apply`: one built-in tool, chosen by `tool`."""


Effector = Literal["left_foot", "right_foot", "left_hand", "right_hand"]


class ToolBounds(StrictModel):
    """A custom tool may only narrow its base tool, never widen it."""

    effectors: list[Effector] = Field(min_length=1)
    max_correction_m: float = Field(gt=0, le=0.5)
    blend_frames_max: int = Field(default=24, ge=1, le=24)


class CustomToolTest(StrictModel):
    name: str = Field(pattern=IDENT_PATTERN)
    instance_id: str = Field(pattern=IDENT_PATTERN)
    effector: Effector
    frame_range: FrameRange
    support_instance_id: str | None = Field(default=None, pattern=IDENT_PATTERN)
    expect: Literal["pass", "refuse"] = Field(description="refuse = the tool must decline this case")


class CustomTool(StrictModel):
    """`tools/custom/<tool_id>/tool.json`: declarative, no code. `base_tool` and `supported_rigs` are
    free text so an unsupported request gets an inspection report instead of a parse error."""

    schema_version: Literal["1.0"] = "1.0"
    tool_id: str = Field(pattern=IDENT_PATTERN)
    version: int = Field(ge=1)
    purpose: str = Field(min_length=10)
    base_tool: str = Field(min_length=1)
    supported_rigs: list[str] = Field(min_length=1)
    bounds: ToolBounds
    preconditions: list[str] = Field(default_factory=list)
    known_limits: list[str] = Field(min_length=1)
    tests: list[CustomToolTest] = Field(min_length=1)

    @model_validator(mode="after")
    def tests_are_distinct_and_cover_a_pass(self):
        names = [t.name for t in self.tests]
        if len(names) != len(set(names)):
            raise ValueError("custom tool tests need distinct names")
        if not any(t.expect == "pass" for t in self.tests):
            raise ValueError("a custom tool needs at least one test it is expected to pass")
        return self


class ToolInspectParams(StrictModel):
    tool_id: str = Field(pattern=IDENT_PATTERN)


class ToolTestParams(StrictModel):
    tool_id: str = Field(pattern=IDENT_PATTERN)


class ToolRegisterParams(StrictModel):
    tool_id: str = Field(pattern=IDENT_PATTERN)
    test_report_path: str


class ToolRegistration(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    tool_id: str = Field(pattern=IDENT_PATTERN)
    version: int = Field(ge=1)
    base_tool: str
    supported_rigs: list[str]
    bounds: ToolBounds
    tool_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_report: str
    test_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tests_passed: int = Field(ge=1)


class AdjustmentRevertParams(StrictModel):
    adjustment_id: str = Field(pattern=IDENT_PATTERN)


# Tool contract (§12.2). One entry per built-in tool; nothing is registered without its tests.
ADJUSTMENT_TOOLS = {
    "contact_lock": {
        "tool_id": "contact_lock",
        "version": "1.0",
        "purpose": "hold one IK hand or foot on its anchor over a marked stance window",
        "supported_rigs": ["rigify/0.6.10"],
        "parameters": "ContactLockParams (metres, frames)",
        "time_scope": "frame_range widened by blend_frames on each side",
        "affected_channels": "location of the effector's IK control, through an additive NLA strip",
        "preconditions": [
            "limb in IK over the window",
            "drift above the project tolerance and at most max_correction_m",
            "no adjustment with the same id",
        ],
        "preview_mode": "adjustment.preview: same computation in memory, before/after measurements and frames, nothing saved",
        "effects_on_sources": "none: source Actions and strips are untouched; one new Action and one NLA track are added",
        "revert": "adjustment.revert removes that track and Action in a new version",
        "tests": [
            "tests/unit/test_adjustment_contracts.py",
            "tests/acceptance/test_adjustments.py::test_B05_contact_lock_preview_apply_revert",
        ],
        "known_limits": [
            "translation only: no foot roll or wrist orientation",
            "refuses travel (walking through the window) instead of guessing a stance",
            "does not re-plant later steps or fix the other foot",
        ],
    },
    "look_at_target": {
        "tool_id": "look_at_target",
        "version": "1.0",
        "purpose": "turn the head towards a world point or an instance over a marked window",
        "supported_rigs": ["rigify/0.6.10"],
        "parameters": "LookAtTargetParams (metres, frames, degrees)",
        "time_scope": "frame_range widened by blend_frames on each side",
        "affected_channels": "rotation_quaternion of the head control, through a COMBINE NLA strip",
        "preconditions": [
            "head control in quaternion rotation mode",
            "target within max_angle_deg of the current gaze on every frame",
            "head turn per frame within max_step_deg, ramps included",
            "no adjustment with the same id",
        ],
        "preview_mode": "adjustment.preview: same computation in memory, before/after measurements and frames, nothing saved",
        "effects_on_sources": "none: source Actions and strips are untouched; one new Action and one NLA track are added",
        "revert": "adjustment.revert removes that track and Action in a new version",
        "tests": [
            "tests/unit/test_adjustment_contracts.py",
            "tests/acceptance/test_adjustments.py::test_look_at_target_preview_apply_revert",
        ],
        "known_limits": [
            "head only: eyes, neck share and torso are not driven",
            "refuses a target beyond max_angle_deg instead of turning the body",
            "custom tools cannot narrow it yet: ToolBounds describes contact_lock only",
        ],
    },
}

# Custom tools narrow these only: `ToolBounds` speaks of effectors and correction distances.
CUSTOMIZABLE_TOOLS = ("contact_lock",)


class ClipIndex(ClipManifest):
    source_blend: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
