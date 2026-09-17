"""Declarative custom tools: a bounded narrowing of a built-in tool, its tests and its registration.

No code is loaded from `tools/custom/`. A tool that asks for an unimplemented base tool or an
unsupported rig gets a stated limitation, never a registration.
"""

from fluidblend.contracts.production import ADJUSTMENT_TOOLS, CustomTool, ToolRegistration
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import assert_not_protected, relpath_posix, resolve_inside


def tool_dir(project, tool_id):
    path = resolve_inside(project.root, f"tools/custom/{tool_id}")
    assert_not_protected(relpath_posix(project.root, path), project.permissions.protected_paths)
    return path


def load_tool(project, tool_id):
    path = tool_dir(project, tool_id) / "tool.json"
    if not path.is_file():
        raise ValueError(f"no custom tool declared at tools/custom/{tool_id}/tool.json")
    tool = CustomTool.model_validate(read_json(path))
    if tool.tool_id != tool_id:
        raise ValueError("tool.json declares another tool_id than its folder")
    return tool, path


def limitations(tool):
    """Why this declaration cannot become a capability; empty when it can be tested."""
    base = ADJUSTMENT_TOOLS.get(tool.base_tool)
    if base is None:
        return [
            f"base tool {tool.base_tool!r} is not implemented; available: {sorted(ADJUSTMENT_TOOLS)}. "
            "A custom tool narrows an existing tool, it cannot add an algorithm."
        ]
    found = []
    unsupported = sorted(set(tool.supported_rigs) - set(base["supported_rigs"]))
    if unsupported:
        found.append(
            f"rig profiles {unsupported} are not supported by {tool.base_tool} "
            f"(supported: {base['supported_rigs']}); it needs IK controls and a semantic rig profile"
        )
    # `ToolBounds` already caps every bound at the base tool's own limits: narrowing only.
    return found


def load_registration(project, tool_id):
    """Registration still matching the declaration it was tested from, or ValueError."""
    tool, path = load_tool(project, tool_id)
    registration_path = tool_dir(project, tool_id) / "registration.json"
    if not registration_path.is_file():
        raise ValueError(f"custom tool {tool_id} is not registered; run tool.test then tool.register")
    registration = ToolRegistration.model_validate(read_json(registration_path))
    if registration.tool_sha256 != sha256_file(path):
        raise ValueError(f"custom tool {tool_id} changed after registration; test and register it again")
    return registration, [path, registration_path]


def enforce_bounds(registration, parameters):
    bounds = registration.bounds
    if parameters["effector"] not in bounds.effectors:
        raise ValueError(f"{registration.tool_id} is registered for {bounds.effectors} only")
    requested = parameters.get("max_correction_m", bounds.max_correction_m)
    if requested > bounds.max_correction_m:
        raise ValueError(f"{registration.tool_id} bounds max_correction_m to {bounds.max_correction_m}")
    if parameters.get("blend_frames", 3) > bounds.blend_frames_max:
        raise ValueError(f"{registration.tool_id} bounds blend_frames to {bounds.blend_frames_max}")
    # An omitted bound means the tool's bound, not the wider default of the base tool.
    return {**parameters, "max_correction_m": requested}
