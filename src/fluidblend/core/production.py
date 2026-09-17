"""Admission of versioned assets and semantic rigs before a Blender worker starts."""

from fluidblend.contracts.production import AssetManifest, AssetPlacement, RigProfile
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import assert_not_protected, relpath_posix, resolve_inside

RIGIFY_CONTROLS = {
    "root": "root",
    "pelvis": "hips",
    "torso": "torso",
    "chest": "chest",
    "head": "head",
    "left_hand_ik": "hand_ik.L",
    "right_hand_ik": "hand_ik.R",
    "left_foot_ik": "foot_ik.L",
    "right_foot_ik": "foot_ik.R",
    "left_upper_arm_fk": "upper_arm_fk.L",
    "right_upper_arm_fk": "upper_arm_fk.R",
    "left_forearm_fk": "forearm_fk.L",
    "right_forearm_fk": "forearm_fk.R",
    "left_thigh_fk": "thigh_fk.L",
    "right_thigh_fk": "thigh_fk.R",
    "left_shin_fk": "shin_fk.L",
    "right_shin_fk": "shin_fk.R",
    "left_arm_switch": "upper_arm_parent.L",
    "right_arm_switch": "upper_arm_parent.R",
    "left_leg_switch": "thigh_parent.L",
    "right_leg_switch": "thigh_parent.R",
    # Deform bones are measurement control points: the control may reach a target the limb does not.
    "left_foot_deform": "DEF-foot.L",
    "right_foot_deform": "DEF-foot.R",
    "left_hand_deform": "DEF-hand.L",
    "right_hand_deform": "DEF-hand.R",
}


# Semantic face mapping -> the character's real controllers (here shape keys of the skinned mesh).
# Rhubarb shapes: A closed (M, B, P); B clenched (K, S, T); C open (EH, AE); D wide (AA);
# E rounded (AO, ER); F puckered (UW, OW, W); G teeth on lip (F, V); H tongue up (L); X rest.
FACE_PROFILES = {
    "charmorph-l3/1": {
        "kind": "shape_keys",
        "visemes": {
            "A": {"p_b_m_21": 1.0},
            "B": {"s_z_15": 1.0},
            "C": {"ey_eh_uh_04": 1.0},
            "D": {"aa_02": 1.0},
            "E": {"ao_03": 1.0},
            "F": {"w_uw_07": 1.0},
            "G": {"f_v_18": 1.0},
            "H": {"l_14": 1.0},
            "X": {},
        },
        "expressions": {
            "happy": {"Happy": 1.0},
            "sad": {"Sad": 1.0},
            "angry": {"Angry": 1.0},
            "scared": {"Scared": 1.0},
            "blink": {"Eyes_Closed_Max": 1.0},
        },
    }
}


def lipsync_cues(project, request):
    """Cues of a published analysis as exact frames: `start_frame + seconds x fps`, never rounded."""
    from fractions import Fraction

    analysis = read_json(admitted_path(project, request.parameters["analysis_path"]))
    cues, end = [], Fraction(0)
    try:
        for cue in analysis["mouthCues"]:
            start, stop = Fraction(str(cue["start"])), Fraction(str(cue["end"]))
            if start < end or stop <= start or cue["value"] not in set("ABCDEFGHX"):
                raise ValueError("invalid cue order, range or value")
            end = stop
            cues.append((cue["value"], start, stop))
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        raise ValueError(f"not a lipsync.analyze report: {exc}") from exc
    if not any(value != "X" for value, _, _ in cues):
        raise ValueError("the analysis contains no mouth shape other than rest")
    fps = project.manifest.fps.as_fraction()
    first = int(request.parameters.get("start_frame", 1))
    return {
        "source_path": analysis.get("source_path"),
        "source_sha256": analysis.get("source_sha256"),
        "cues": [
            {
                "value": value,
                "start_s": float(start),
                "end_s": float(stop),
                "start_frame": float(first + start * fps),
                "end_frame": float(first + stop * fps),
            }
            for value, start, stop in cues
        ],
    }


def admitted_path(project, value):
    path = resolve_inside(project.root, value, allow_missing=False)
    assert_not_protected(relpath_posix(project.root, path), project.permissions.protected_paths)
    return path


class StaleInput(ValueError):
    """An admitted input was produced for another scene revision: a conflict, not a bad request."""


def admitted_plan(project, request):
    from fluidblend.contracts.production import InteractionPlan
    from fluidblend.core.evidence import verify_evidence
    from fluidblend.core.revisions import RevisionStore

    path = admitted_path(project, request.parameters["plan_path"])
    plan = InteractionPlan.model_validate(read_json(path))
    if plan.shot_id != request.target.shot_id:
        raise ValueError("interaction plan belongs to another shot")
    revision = RevisionStore(project.root).get(f"shot:{plan.shot_id}")
    if revision is None:
        raise StaleInput("no revision recorded for the planned shot")
    ok, reason = verify_evidence(
        path,
        project_id=project.project_id,
        shot_id=plan.shot_id,
        revision=revision.revision,
        scene_sha256=revision.sha256,
    )
    if not ok:
        raise StaleInput(f"interaction plan: {reason}; plan again on the current revision")
    return plan.model_dump(mode="json")


def inputs_for(project, request):
    inputs = {"rigify_controls": RIGIFY_CONTROLS}
    if request.operation == "interaction.apply":
        inputs["interaction_plan"] = admitted_plan(project, request)
    if request.operation in ("lipsync.apply", "expression.apply"):
        inputs["face_profiles"] = FACE_PROFILES
    if request.operation == "lipsync.apply":
        inputs["lipsync"] = lipsync_cues(project, request)
    if request.operation == "tool.test":
        from fluidblend.core.custom_tools import limitations, load_tool

        tool, path = load_tool(project, request.parameters["tool_id"])
        limits = limitations(tool)
        if limits:
            raise ValueError("custom tool cannot be tested: " + "; ".join(limits))
        inputs["custom_tool"] = {**tool.model_dump(mode="json"), "tool_sha256": sha256_file(path)}
    if request.operation in ("adjustment.preview", "adjustment.apply") and request.parameters.get(
        "custom_tool_id"
    ):
        from fluidblend.core.custom_tools import enforce_bounds, load_registration

        registration, _paths = load_registration(project, request.parameters["custom_tool_id"])
        inputs["custom_tool_parameters"] = enforce_bounds(registration, request.parameters)
        inputs["custom_tool_rigs"] = registration.supported_rigs
    profile_path = request.parameters.get("profile_path")
    if profile_path:
        profile = RigProfile.model_validate(read_json(admitted_path(project, profile_path)))
        if profile.instance_id != request.target.instance_id:
            raise ValueError("rig profile belongs to a different instance")
        inputs["rig_profile"] = profile.model_dump()
    if request.operation == "shot.build":
        instances, assets = set(), []
        for placement in request.parameters["assets"]:
            if placement["instance_id"] in instances:
                raise ValueError("duplicate asset instance_id")
            instances.add(placement["instance_id"])
            manifest = AssetManifest.model_validate(
                read_json(admitted_path(project, placement["manifest_path"]))
            )
            blend = admitted_path(project, manifest.blend_path)
            admitted_path(project, manifest.license_path)
            if sha256_file(blend) != manifest.sha256:
                raise ValueError("asset hash differs from its versioned manifest")
            # Defaults must reach the runtime: it validates nothing beyond the envelope.
            placed = AssetPlacement.model_validate(placement).model_dump()
            assets.append({**manifest.model_dump(), "blend_path": str(blend), **placed})
        inputs["assets"] = assets
    return inputs


def input_fingerprints(project, request):
    """Capture admitted source files, including nested asset manifests and their dependencies."""
    paths = []
    for name, value in request.parameters.items():
        if name.endswith("_path") and value:
            paths.append(resolve_inside(project.root, value, allow_missing=False))
    if request.operation == "tool.test":
        from fluidblend.core.custom_tools import load_tool

        paths.append(load_tool(project, request.parameters["tool_id"])[1])
    if request.parameters.get("custom_tool_id"):
        from fluidblend.core.custom_tools import load_registration

        paths.extend(load_registration(project, request.parameters["custom_tool_id"])[1])
    if request.operation == "shot.build":
        for asset in inputs_for(project, request)["assets"]:
            for key in ("manifest_path", "blend_path", "license_path"):
                paths.append(resolve_inside(project.root, asset[key], allow_missing=False))
    return {relpath_posix(project.root, path): sha256_file(path) for path in paths}
