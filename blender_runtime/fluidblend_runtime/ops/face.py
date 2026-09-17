"""Mouth cues and bounded expressions on a character's real face controllers.

The semantic face profile names the controllers (here shape keys of the skinned mesh). Animation is
keyed on the shape-key datablock through the slotted-Action helper and placed on its own NLA track, so
a manual correction can live above it and `REPLACE` channels are never shared silently.
"""

import os

import bpy
from mathutils import Vector

from fluidblend_runtime import render
from fluidblend_runtime.anim import slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.ops.animation_library import add_strip, channels, refuse_overlap
from fluidblend_runtime.ops.rig_validate import positions
from fluidblend_runtime.production import character, meshes_for, save_version

REST_TOLERANCE_M = 5e-5
# Some upstream visemes move the lips by 4-6 mm at full strength: 1 mm still means "it moved".
VISIBLE_M = 0.001


def face_of(ctx, rig):
    """(profile, mesh, shape-key datablock) or a stated refusal: nothing is guessed from names."""
    profile_id = rig.get("fluidblend_face_profile")
    profile = ctx.inputs.get("face_profiles", {}).get(profile_id)
    if profile is None:
        raise OpError(
            "RIG_MAPPING_REQUIRED",
            "this character has no supported face profile; its mouth cannot be driven",
            details={"face_profile": profile_id, "supported": sorted(ctx.inputs.get("face_profiles", {}))},
        )
    meshes = [m for m in meshes_for(rig) if m.data.shape_keys]
    if len(meshes) != 1:
        raise OpError("RIG_MAPPING_REQUIRED", "face profile expects exactly one skinned mesh with shape keys")
    keys = meshes[0].data.shape_keys
    needed = {name for group in ("visemes", "expressions") for mix in profile[group].values() for name in mix}
    missing = sorted(needed - set(keys.key_blocks.keys()))
    if missing:
        raise OpError("RIG_MAPPING_REQUIRED", "face controllers are missing", details={"missing": missing})
    return profile, meshes[0], keys


def path_of(name):
    return f'key_blocks["{name}"].value'


def key_envelopes(keys, name, envelopes, layer, start, end):
    """One Action on the shape-key datablock, its channels refused if already owned, one NLA strip."""
    anim = keys.animation_data or keys.animation_data_create()
    previous, previous_slot = anim.action, anim.action_slot
    action, _slot, bag = slotted.ensure_action(keys, f"{keys.name}.{name}")
    anim.action = previous
    if previous_slot is not None:
        anim.action_slot = previous_slot
    for shape, points in envelopes.items():
        merged = {}
        for frame, value in points:
            merged[frame] = max(value, merged.get(frame, 0.0))
        slotted.set_keys(slotted.fcurve(bag, path_of(shape)), sorted(merged.items()), interpolation="LINEAR")
    refuse_overlap(keys, action)
    action.use_fake_user = True
    action["fluidblend_face_clip"] = name
    first, last = int(start // 1), int(-(-end // 1))
    track, _strip = add_strip(keys, action, layer, name, first, {"start": first, "end_exclusive": last})
    return action, track


def displacement(mesh, track, shapes):
    """Largest vertex move caused by this track alone at the current frame (body motion cancels out)."""
    scene = bpy.context.scene
    scene.frame_set(scene.frame_current)
    with_track = positions([mesh])
    # A muted track stops driving its properties but leaves their last value in place: the
    # reference state is the same frame with these shapes explicitly at rest.
    track.mute = True
    for name in shapes:
        mesh.data.shape_keys.key_blocks[name].value = 0.0
    bpy.context.view_layer.update()
    without = positions([mesh])
    track.mute = False
    scene.frame_set(scene.frame_current)
    return max(((a - b).length for a, b in zip(with_track, without, strict=True)), default=0.0)


def moved_vertices(mesh, shapes):
    """Indices of the vertices these shapes really move: the region a close-up must show."""
    blocks = mesh.data.shape_keys.key_blocks
    basis = blocks[0].data
    found = set()
    for name in shapes:
        data = blocks[name].data
        found.update(i for i in range(len(basis)) if (data[i].co - basis[i].co).length > 0.001)
    return sorted(found)


def close_ups(ctx, rig, mesh, shapes, frames, folder):
    """Render the deformed region through the shot camera moved in front of it, then put it back."""
    scene = bpy.context.scene
    camera = scene.camera
    region = moved_vertices(mesh, shapes)
    if camera is None or not frames or not region:
        return False
    saved = camera.matrix_world.copy(), camera.data.lens, scene.frame_current
    render.configure(
        scene,
        engine="WORKBENCH",
        width=ctx.preview_width,
        height=ctx.preview_height,
        fps_numerator=ctx.fps_numerator,
        fps_denominator=ctx.fps_denominator,
    )
    try:
        camera.data.lens = 85
        for frame in frames:
            scene.frame_set(int(round(frame)))
            bpy.context.view_layer.update()
            evaluated = positions([mesh])
            target = sum((evaluated[i] for i in region), Vector()) / len(region)
            forward = (rig.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
            camera.location = target + forward * 0.8 + Vector((0.1, 0, 0.02))
            camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = ctx.out("review", folder, f"frame_{int(round(frame)):04d}.png")
            bpy.ops.render.render(write_still=True)
    finally:
        camera.matrix_world, camera.data.lens = saved[0], saved[1]
        scene.frame_set(saved[2])
    return True


def lipsync(ctx, request, builder):
    rig = character(request)
    profile, mesh, keys = face_of(ctx, rig)
    params, data = request["parameters"], ctx.inputs["lipsync"]
    strength, transition = params.get("strength", 1.0), params.get("transition_frames", 2.0)
    # Same shape twice in a row is one held shape, not a dip to rest and back.
    cues = []
    for cue in data["cues"]:
        if (
            cues
            and cues[-1]["value"] == cue["value"]
            and abs(cues[-1]["end_frame"] - cue["start_frame"]) < 1e-6
        ):
            cues[-1] = {**cues[-1], "end_frame": cue["end_frame"], "end_s": cue["end_s"]}
        else:
            cues.append(dict(cue))
    start, end = cues[0]["start_frame"], cues[-1]["end_frame"] + transition
    shapes = sorted({name for mix in profile["visemes"].values() for name in mix})
    envelopes = {name: [(start, 0.0), (end, 0.0)] for name in shapes}
    for cue in cues:
        ramp = min(transition, (cue["end_frame"] - cue["start_frame"]) / 2)
        cue["ramp"] = ramp
        for name, weight in profile["visemes"][cue["value"]].items():
            value = weight * strength
            envelopes[name] += [
                (cue["start_frame"], 0.0),
                (cue["start_frame"] + ramp, value),
                (cue["end_frame"], value),
                (cue["end_frame"] + ramp, 0.0),
            ]
    action, track = key_envelopes(keys, params["lipsync_id"], envelopes, "mouth", start, end)
    curves = {fc.data_path: fc for fc in slotted.iter_fcurves(action)}
    scene = bpy.context.scene
    current = scene.frame_current
    checks, samples = [], []
    try:
        for cue in cues:
            if cue["end_frame"] - cue["start_frame"] < 2 * cue["ramp"] + 1e-6:
                continue  # too short to hold its shape: it is only passed through
            middle = (cue["start_frame"] + cue["ramp"] + cue["end_frame"]) / 2
            own = profile["visemes"][cue["value"]]
            values = {name: curves[path_of(name)].evaluate(middle) for name in shapes}
            dominant = all(abs(values[n] - w * strength) <= 0.02 for n, w in own.items())
            others = max((v for n, v in values.items() if n not in own), default=0.0)
            scene.frame_set(int(round(middle)))
            moved = displacement(mesh, track, shapes)
            visible = moved <= REST_TOLERANCE_M if cue["value"] == "X" else moved >= VISIBLE_M * strength
            checks.append(
                {
                    "value": cue["value"],
                    "start_s": cue["start_s"],
                    "start_frame": cue["start_frame"],
                    "end_frame": cue["end_frame"],
                    "sampled_frame": int(round(middle)),
                    "own_shape_reached": dominant,
                    "other_shapes_max": others,
                    "mouth_displacement_m": moved,
                    "passed": dominant and others <= 0.05 and visible,
                }
            )
            if cue["value"] != "X":
                samples.append(middle)
    finally:
        scene.frame_set(current)
    if not checks:
        raise OpError(
            "VALIDATION_FAILED", "every cue is shorter than its transition; lower transition_frames"
        )
    passed = all(c["passed"] for c in checks)
    if not passed:
        raise OpError(
            "VALIDATION_FAILED",
            "mouth keys do not reproduce the analysed cues; nothing was published",
            details={"failed": [c for c in checks if not c["passed"]][:10]},
        )
    count = params.get("preview_samples", 4)
    picked = (
        samples
        if len(samples) <= count
        else [samples[round(i * (len(samples) - 1) / (count - 1))] for i in range(count)]
        if count > 1
        else samples[:count]
    )
    if count and close_ups(ctx, rig, mesh, shapes, sorted(set(picked)), "lipsync"):
        builder.add_dir("frames", os.path.join(ctx.out_dir, "review"))
    save_version(ctx, request, builder)
    builder.write_report(
        "lipsync-apply.json",
        {
            "lipsync_id": params["lipsync_id"],
            "instance_id": request["target"]["instance_id"],
            "face_profile": rig.get("fluidblend_face_profile"),
            "audio_source": {"path": data.get("source_path"), "sha256": data.get("source_sha256")},
            "time_mapping": "frame = start_frame + seconds x fps, kept fractional (no rounding drift)",
            "start_frame": params.get("start_frame", 1),
            "frame_span": [start, end],
            "track": track.name,
            "owned_channels": [list(c) for c in sorted(channels(action))],
            "cues": len(data["cues"]),
            "checked_cues": checks,
            "technical_pass": passed,
            "visual_review": "pending",
            "limits": [
                "shape recognition is Rhubarb's; the text and the voice are not approved by this operation",
                "upstream sculpted visemes, some subtle (4-6 mm); no tongue, jaw bone or co-articulation model",
                "cues shorter than two transitions are passed through, not held, and are not checked",
                "technical mapping check, not an approval of the performance",
            ],
        },
    )
    builder.changed("lipsync", params["lipsync_id"], "created")
    builder.metrics.update(
        {
            "technical_pass": passed,
            "cues": len(data["cues"]),
            "checked_cues": len(checks),
            "mouth_displacement_max_m": max(c["mouth_displacement_m"] for c in checks),
        }
    )


def expression(ctx, request, builder):
    rig = character(request)
    profile, mesh, keys = face_of(ctx, rig)
    params = request["parameters"]
    start, last = params["frame_range"]["start"], params["frame_range"]["end_exclusive"] - 1
    ease, strength = params.get("ease_frames", 4.0), params.get("strength", 1.0)
    envelopes = {
        name: [(start, 0.0), (start + ease, weight * strength), (last - ease, weight * strength), (last, 0.0)]
        for name, weight in profile["expressions"][params["expression"]].items()
    }
    action, track = key_envelopes(keys, params["expression_id"], envelopes, "face", start, last)
    scene = bpy.context.scene
    current = scene.frame_current
    middle = (start + last) // 2
    try:
        scene.frame_set(middle)
        moved = displacement(mesh, track, list(envelopes))
        scene.frame_set(start)
        at_rest = displacement(mesh, track, list(envelopes))
    finally:
        scene.frame_set(current)
    passed = moved >= VISIBLE_M * strength and at_rest <= REST_TOLERANCE_M
    if not passed:
        raise OpError(
            "VALIDATION_FAILED",
            "expression does not deform the face as keyed; nothing was published",
            details={"displacement_m": moved, "rest_m": at_rest},
        )
    if close_ups(ctx, rig, mesh, list(envelopes), [start, middle], "expression"):
        builder.add_dir("frames", os.path.join(ctx.out_dir, "review"))
    save_version(ctx, request, builder)
    builder.write_report(
        "expression-apply.json",
        {
            "expression_id": params["expression_id"],
            "expression": params["expression"],
            "instance_id": request["target"]["instance_id"],
            "track": track.name,
            "owned_channels": [list(c) for c in sorted(channels(action))],
            "face_displacement_m": moved,
            "rest_displacement_m": at_rest,
            "technical_pass": passed,
            "visual_review": "pending",
            "limits": [
                "one upstream sculpted morph per expression; it adds to the mouth shapes and can over-deform",
                "technical deformation check, not an approval of the acting",
            ],
        },
    )
    builder.changed("expression", params["expression_id"], "created")
    builder.metrics.update({"technical_pass": passed, "face_displacement_m": moved})
