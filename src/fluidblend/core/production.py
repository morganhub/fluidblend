"""Admission of versioned assets and semantic rigs before a Blender worker starts."""

from fluidblend.contracts.production import AssetManifest, RigProfile
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
}


def admitted_path(project, value):
    path = resolve_inside(project.root, value, allow_missing=False)
    assert_not_protected(relpath_posix(project.root, path), project.permissions.protected_paths)
    return path


def inputs_for(project, request):
    inputs = {"rigify_controls": RIGIFY_CONTROLS}
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
            assets.append({**manifest.model_dump(), "blend_path": str(blend), **placement})
        inputs["assets"] = assets
    return inputs


def input_fingerprints(project, request):
    """Capture admitted source files, including nested asset manifests and their dependencies."""
    paths = []
    for name, value in request.parameters.items():
        if name.endswith("_path") and value:
            paths.append(resolve_inside(project.root, value, allow_missing=False))
    if request.operation == "shot.build":
        for asset in inputs_for(project, request)["assets"]:
            for key in ("manifest_path", "blend_path", "license_path"):
                paths.append(resolve_inside(project.root, asset[key], allow_missing=False))
    return {relpath_posix(project.root, path): sha256_file(path) for path in paths}
