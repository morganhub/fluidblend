"""scene.audit: technical checks (§16.1, Scene row). Reports, does not fix."""

from __future__ import annotations

import math
import re

import bpy

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import slotted
from fluidblend_runtime.ops import scene_inspect

DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")


def audit() -> dict:
    scene = bpy.context.scene
    issues: list[dict] = []

    def issue(severity: str, code: str, message: str, **details) -> None:
        issues.append({"severity": severity, "code": code, "message": message, "details": details})

    if scene.camera is None:
        issue("error", "NO_CAMERA", "no active camera in the scene")
    if scene.frame_end < scene.frame_start:
        issue(
            "error",
            "BAD_FRAME_RANGE",
            "frame_end < frame_start",
            start=scene.frame_start,
            end=scene.frame_end,
        )
    if scene.render.fps <= 0:
        issue("error", "BAD_FPS", "frame rate is zero")
    for obj in bpy.data.objects:
        values = list(obj.location) + list(obj.rotation_euler) + list(obj.scale)
        if not all(math.isfinite(float(v)) for v in values):
            issue("error", "NON_FINITE_TRANSFORM", f"NaN/Inf transform on {obj.name}", object=obj.name)
        if any(abs(s) < 1e-6 for s in obj.scale):
            issue("warning", "ZERO_SCALE", f"zero scale on {obj.name}", object=obj.name)
        if DUPLICATE_SUFFIX.search(obj.name) and obj.get("fluidblend_instance_id") is None:
            issue(
                "warning",
                "SUFFIXED_NAME",
                f"name suffixed with .NNN (accidental duplicate?): {obj.name}",
                object=obj.name,
            )
        if obj.parent_type == "BONE" and obj.parent and obj.parent_bone not in obj.parent.data.bones:
            issue(
                "error", "MISSING_PARENT_BONE", f"{obj.name} parented to a missing bone", bone=obj.parent_bone
            )
    missing = blendio.missing_external_files()
    for path in missing:
        issue("error", "MISSING_FILE", f"missing external reference: {path}", path=path)
    for action in bpy.data.actions:
        extent = slotted.key_extent(action)
        if extent is None:
            issue("warning", "EMPTY_ACTION", f"action without any key: {action.name}", action=action.name)
            continue
        if extent[0] < scene.frame_start - 1000 or extent[1] > scene.frame_end + 1000:
            issue(
                "warning",
                "KEYS_FAR_OUT_OF_RANGE",
                f"keys far outside the shot range: {action.name}",
                extent=list(extent),
            )
        for fc in slotted.iter_fcurves(action):
            for point in fc.keyframe_points:
                if not (math.isfinite(point.co.x) and math.isfinite(point.co.y)):
                    issue(
                        "error",
                        "NON_FINITE_KEY",
                        f"NaN/Inf key in {action.name} {fc.data_path}[{fc.array_index}]",
                    )
                    break
    for obj in blendio.instance_objects("character"):
        anim = obj.animation_data
        # Library clips are applied as NLA strips: that is animation too, without an active Action.
        if anim and not anim.action and any(track.strips for track in anim.nla_tracks):
            continue
        if not obj.animation_data or not obj.animation_data.action:
            issue(
                "warning",
                "INSTANCE_WITHOUT_ACTION",
                f"instance without an Action: {obj.get('fluidblend_instance_id')}",
            )
        elif obj.animation_data.action_slot is None:
            issue(
                "error",
                "ACTION_WITHOUT_SLOT",
                f"Action assigned without a slot: {obj.get('fluidblend_instance_id')}",
            )
    errors = [i for i in issues if i["severity"] == "error"]
    return {
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
        "issues": issues,
        "coverage": [
            "active camera",
            "frame range and frame rate",
            "finite transforms, zero scales, suffixed names",
            "bone parenting",
            "missing external files",
            "empty actions / non-finite keys / range",
            "instances with an Action + slot",
        ],
        "not_covered": ["geometry intersections", "skinning weights (P1)", "cyclic constraints (P1)"],
    }


def run(ctx, request, builder) -> None:
    report = audit()
    report["summary"] = scene_inspect.summarize(include_actions=False)
    builder.write_report("audit.json", report)
    builder.metrics["audit_passed"] = report["passed"]
    builder.metrics["audit_errors"] = report["error_count"]
    builder.metrics["audit_warnings"] = report["warning_count"]
    if not report["passed"]:
        builder.warn(f"audit: {report['error_count']} technical error(s) detected")
