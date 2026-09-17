"""Adjustment tools as additive, removable layers: Preview / Apply / Revert share one computation.

An adjustment never edits a source Action or strip. It adds one Action on one NLA track (blend ADD)
and records itself in the scene, so `revert` removes exactly what `apply` added.
"""

import json
import os

import bpy
from mathutils import Vector

from fluidblend_runtime import blendio, render
from fluidblend_runtime.anim import measures, slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.ops.animation_library import hand_point, require_roles
from fluidblend_runtime.production import character, controls_for, save_version

REGISTRY = "fluidblend_adjustments"
MAX_PASSES = 3


def registry(scene):
    return json.loads(scene.get(REGISTRY, "{}"))


def effector_roles(controls, effector):
    side, limb = effector.split("_")
    if limb == "foot":
        roles = (f"{side}_foot_ik", f"{side}_leg_switch", f"{side}_foot_deform")
        require_roles(controls, roles)
        return controls[roles[0]], controls[roles[1]], controls[roles[2]].name
    roles = (f"{side}_hand_ik", f"{side}_arm_switch", f"{side}_hand_deform")
    require_roles(controls, roles)
    return controls[roles[0]], controls[roles[1]], hand_point(controls, side)


def contact(params, point, anchor):
    return {
        "effector": params["effector"],
        "control_point": point,
        "support_instance_id": params.get("support_instance_id"),
        "frame_range": params["frame_range"],
        "anchor": list(anchor),
    }


def measure(ctx, rig, params, point, anchor, support):
    supports = {params["support_instance_id"]: support} if support is not None else None
    records = measures.contact_records(
        rig, [contact(params, point, anchor)], quality=ctx.quality, supports=supports
    )
    # World windows carry no anchor record; the slide from the first frame is the contact error there.
    return records


def worst(records):
    return max(r["value"] for r in records)


def lock(ctx, rig, params):
    """Add the correction layer in memory and return (before, after, track, action, point)."""
    controls = controls_for(ctx, rig)
    control, switch, point = effector_roles(controls, params["effector"])
    adjustment_id = params["adjustment_id"]
    if adjustment_id in registry(bpy.context.scene):
        raise OpError("SCENE_CONFLICT", "adjustment id already applied in this scene; choose a new one")
    support_id = params.get("support_instance_id")
    support = blendio.find_instance_object(support_id) if support_id else None
    if support_id and support is None:
        raise OpError("VALIDATION_FAILED", f"support instance is not in the scene: {support_id}")
    window = params["frame_range"]
    frames = measures.window_frames(window)
    scene = bpy.context.scene
    current = scene.frame_current
    try:
        for frame in frames:
            scene.frame_set(frame)
            if switch.get("IK_FK", 0.0) > 0.5:
                raise OpError(
                    "VALIDATION_FAILED",
                    "limb is in FK inside the window; contact_lock drives the IK control only",
                    details={"frame": frame},
                )
    finally:
        scene.frame_set(current)
    start_points = measures.sample(rig, [point], frames[:1], support=support)[point]
    anchor = start_points[0]
    before = measure(ctx, rig, params, point, anchor, support)
    tolerance = before[0]["tolerance"]
    drift = worst(before)
    if drift <= tolerance:
        raise OpError(
            "VALIDATION_FAILED",
            "contact already within tolerance; nothing to lock",
            details={"drift_m": drift, "tolerance_m": tolerance},
        )
    if drift > params.get("max_correction_m", 0.15):
        raise OpError(
            "VALIDATION_FAILED",
            "drift exceeds max_correction_m: this window is travel, not a sliding stance; narrow it to the stance",
            details={"drift_m": drift, "max_correction_m": params.get("max_correction_m", 0.15)},
        )
    blend = params.get("blend_frames", 3)
    anim = rig.animation_data or rig.animation_data_create()
    previous, previous_slot = anim.action, anim.action_slot
    action, _slot, bag = slotted.ensure_action(rig, f"{rig.name}.adjust.{adjustment_id}")
    anim.action = previous
    if previous_slot is not None:
        anim.action_slot = previous_slot
    action.use_fake_user = True
    action["fluidblend_adjustment_id"] = adjustment_id
    curves = [slotted.fcurve(bag, control.path_from_id("location"), index) for index in range(3)]
    to_local = (rig.matrix_world.to_3x3() @ control.bone.matrix_local.to_3x3()).inverted()
    total = {frame: Vector((0, 0, 0)) for frame in frames}
    track = strip = None
    after = before
    for _ in range(MAX_PASSES):
        points = measures.sample(rig, [point], frames)[point]
        for frame, observed in zip(frames, points, strict=True):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            target = support.matrix_world @ Vector(anchor) if support is not None else Vector(anchor)
            total[frame] += to_local @ (target - Vector(observed))
        scene.frame_set(current)
        keys = [(frames[0] - blend, Vector((0, 0, 0)))] + [(f, total[f]) for f in frames]
        keys.append((frames[-1] + blend, Vector((0, 0, 0))))
        for index, curve in enumerate(curves):
            curve.keyframe_points.clear()
            slotted.set_keys(curve, [(frame, value[index]) for frame, value in keys], interpolation="LINEAR")
        if track is None:
            track = anim.nla_tracks.new()
            track.name = f"fluidblend.adjust.{adjustment_id}"
            strip = track.strips.new(adjustment_id, frames[0] - blend, action)
            strip.action_slot = action.slots[0]
            strip.action_frame_start, strip.action_frame_end = frames[0] - blend, frames[-1] + blend
            # The layer adds to whatever drives the control below it; it owns nothing.
            strip.blend_type = "ADD"
            strip.extrapolation = "NOTHING"
        bpy.context.view_layer.update()
        after = measure(ctx, rig, params, point, anchor, support)
        if worst(after) <= tolerance:
            break
    return before, after, track, action, point


def render_frames(ctx, params, folder):
    count = params.get("preview_samples", 4)
    if not count:
        return
    scene = bpy.context.scene
    render.configure(
        scene,
        engine="WORKBENCH",
        width=ctx.preview_width,
        height=ctx.preview_height,
        fps_numerator=ctx.fps_numerator,
        fps_denominator=ctx.fps_denominator,
    )
    frames = measures.window_frames(params["frame_range"])
    picked = sorted({frames[round(i * (len(frames) - 1) / max(1, count - 1))] for i in range(count)})
    current = scene.frame_current
    try:
        for frame in picked:
            scene.frame_set(frame)
            scene.render.filepath = ctx.out("review", folder, f"frame_{frame:04d}.png")
            bpy.ops.render.render(write_still=True)
    finally:
        scene.frame_set(current)


def report(params, before, after):
    return {
        "adjustment_id": params["adjustment_id"],
        "tool": "contact_lock",
        "parameters": params,
        "before": before,
        "after": after,
        "technical_pass": not measures.failures(after),
        "visual_review": "pending",
        "effects_on_sources": "none; one additive NLA track and its Action",
        "limits": [
            "translation of the IK control only; no foot roll or wrist orientation",
            "other contacts of the character are not re-planted",
            "technical measurement, not an artistic approval",
        ],
    }


def summary(data):
    return {
        "technical_pass": data["technical_pass"],
        "contact_before_m": worst(data["before"]),
        "contact_after_m": worst(data["after"]),
    }


def resolved(ctx, request, rig):
    """Request parameters, or those the engine narrowed to a registered custom tool's bounds."""
    rigs = ctx.inputs.get("custom_tool_rigs")
    if rigs is not None and rig.get("fluidblend_rig_profile") not in rigs:
        raise OpError(
            "RIG_MAPPING_REQUIRED",
            "this custom tool is not registered for the target's rig profile",
            details={"rig_profile": rig.get("fluidblend_rig_profile"), "supported_rigs": rigs},
        )
    return ctx.inputs.get("custom_tool_parameters") or request["parameters"]


def tool_test(ctx, request, builder):
    """Run every declared test of a custom tool in memory, each on a freshly opened scene."""
    tool = ctx.inputs["custom_tool"]
    results = []
    for test in tool["tests"]:
        blendio.open_blend(ctx.work_blend)
        params = {
            "adjustment_id": f"tooltest-{test['name']}",
            "effector": test["effector"],
            "frame_range": test["frame_range"],
            "support_instance_id": test.get("support_instance_id"),
            "max_correction_m": tool["bounds"]["max_correction_m"],
            "blend_frames": min(3, tool["bounds"]["blend_frames_max"]),
        }
        outcome = {"name": test["name"], "expect": test["expect"]}
        try:
            rig = blendio.find_instance_object(test["instance_id"])
            if rig is None or rig.type != "ARMATURE":
                raise OpError("VALIDATION_FAILED", f"test instance is not a character: {test['instance_id']}")
            if rig.get("fluidblend_rig_profile") not in tool["supported_rigs"]:
                raise OpError("RIG_MAPPING_REQUIRED", "test instance rig profile is outside supported_rigs")
            if test["effector"] not in tool["bounds"]["effectors"]:
                raise OpError("VALIDATION_FAILED", "test effector is outside the tool's own bounds")
            before, after, _track, _action, _point = lock(ctx, rig, params)
            fixed = not measures.failures(after)
            outcome.update(
                refused=False, contact_before_m=worst(before), contact_after_m=worst(after), fixed=fixed
            )
            outcome["passed"] = fixed and test["expect"] == "pass"
        except OpError as exc:
            outcome.update(refused=True, code=exc.code, message=str(exc), details=exc.details)
            outcome["passed"] = test["expect"] == "refuse" and exc.code == "VALIDATION_FAILED"
        results.append(outcome)
    all_passed = all(r["passed"] for r in results)
    builder.write_report(
        "tool-test.json",
        {
            "tool_id": tool["tool_id"],
            "version": tool["version"],
            "tool_sha256": tool["tool_sha256"],
            "shot_id": request["target"]["shot_id"],
            "results": results,
            "all_passed": all_passed,
            "limits": ["tests run in memory on this shot's current revision; nothing was saved"],
        },
    )
    builder.metrics.update({"all_passed": all_passed, "tests": len(results)})
    if not all_passed:
        builder.warn("custom tool tests failed; tool.register will refuse this report")


def preview(ctx, request, builder):
    rig = character(request)
    params = resolved(ctx, request, rig)
    if params.get("preview_samples", 4) and bpy.context.scene.camera:
        render_frames(ctx, params, "before")
    before, after, _track, _action, _point = lock(ctx, rig, params)
    if params.get("preview_samples", 4) and bpy.context.scene.camera:
        render_frames(ctx, params, "after")
        builder.add_dir("frames", os.path.join(ctx.out_dir, "review"))
    data = {**report(params, before, after), "saved": False}
    builder.write_report("adjustment-preview.json", data)
    builder.metrics.update(summary(data))
    builder.next_safe_actions.append("adjustment.apply with the same parameters and a new operation_id")


def apply(ctx, request, builder):
    rig = character(request)
    params = resolved(ctx, request, rig)
    before, after, track, action, point = lock(ctx, rig, params)
    data = report(params, before, after)
    if not data["technical_pass"]:
        raise OpError(
            "VALIDATION_FAILED",
            "contact_lock could not bring the contact within tolerance; nothing was published",
            details={"after": measures.failures(after)},
        )
    scene = bpy.context.scene
    known = registry(scene)
    known[params["adjustment_id"]] = {
        "tool": "contact_lock",
        "instance_id": request["target"]["instance_id"],
        "track": track.name,
        "action": action.name,
        "control_point": point,
        "parameters": params,
    }
    scene[REGISTRY] = json.dumps(known)
    save_version(ctx, request, builder)
    builder.write_report("adjustment-apply.json", {**data, "saved": True, "track": track.name})
    builder.changed("adjustment", params["adjustment_id"], "created")
    builder.metrics.update(summary(data))


def revert(ctx, request, builder):
    scene = bpy.context.scene
    adjustment_id = request["parameters"]["adjustment_id"]
    known = registry(scene)
    entry = known.get(adjustment_id)
    if entry is None:
        raise OpError("VALIDATION_FAILED", f"no applied adjustment in this scene: {adjustment_id}")
    if entry["instance_id"] != request["target"].get("instance_id"):
        raise OpError("VALIDATION_FAILED", "adjustment belongs to another instance")
    rig = character(request)
    track = rig.animation_data.nla_tracks.get(entry["track"]) if rig.animation_data else None
    action = bpy.data.actions.get(entry["action"])
    if track is None or action is None:
        raise OpError(
            "SCENE_CONFLICT",
            "the adjustment layer was changed outside the kit; it is left as found",
            details={"track_found": track is not None, "action_found": action is not None},
        )
    rig.animation_data.nla_tracks.remove(track)
    bpy.data.actions.remove(action)
    del known[adjustment_id]
    scene[REGISTRY] = json.dumps(known)
    bpy.context.view_layer.update()
    params = entry["parameters"]
    support_id = params.get("support_instance_id")
    support = blendio.find_instance_object(support_id) if support_id else None
    point = entry["control_point"]
    frames = measures.window_frames(params["frame_range"])
    anchor = measures.sample(rig, [point], frames[:1], support=support)[point][0]
    restored = measure(ctx, rig, params, point, anchor, support)
    save_version(ctx, request, builder)
    builder.write_report(
        "adjustment-revert.json",
        {"adjustment_id": adjustment_id, "removed": [entry["track"], entry["action"]], "restored": restored},
    )
    builder.changed("adjustment", adjustment_id, "deleted")
    builder.metrics.update({"reverted": True, "contact_restored_m": worst(restored)})
