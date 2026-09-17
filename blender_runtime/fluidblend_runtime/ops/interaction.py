"""Bounded prop hand-off: one prop, two characters, one ownership transfer that keeps the world transform.

`apply` and `validate` share `measure`: the numbers that gate the write are the numbers re-read later,
after a human edit or a timing change.
"""

import json

import bpy
from mathutils import Matrix, Vector

from fluidblend_runtime import blendio
from fluidblend_runtime.anim import measures, slotted
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.ops.animation_library import (
    add_strip,
    author_hand_reach,
    channels,
    hand_point,
    refuse_overlap,
)
from fluidblend_runtime.production import controls_for, grip_local, grip_world, prop_object, save_version

REGISTRY = "fluidblend_interactions"
LOWER_MEETING_M = 0.2


def registry(scene):
    return json.loads(scene.get(REGISTRY, "{}"))


def participant_rig(instance_id):
    rig = blendio.find_instance_object(instance_id)
    if rig is None or rig.type != "ARMATURE":
        raise OpError("VALIDATION_FAILED", f"participant is not a character in the scene: {instance_id}")
    if rig.get("fluidblend_baked"):
        raise OpError("UNSUPPORTED_CAPABILITY", "a baked export skeleton has no IK control to reach with")
    return rig


def refuse_other_authority(prop):
    """A prop transform has one authority at a time; anything already driving it is a conflict."""
    anim = prop.animation_data
    driven = anim and (anim.action or anim.drivers or any(track.strips for track in anim.nla_tracks))
    if prop.parent or len(prop.constraints) or driven:
        raise OpError(
            "SCENE_CONFLICT",
            "prop transform already has an authority (parent, constraint or animation); nothing was changed",
            details={
                "parent": prop.parent.name if prop.parent else None,
                "constraints": [c.name for c in prop.constraints],
                "animated": bool(driven),
            },
        )
    if any(abs(value - 1) > 1e-5 for value in prop.matrix_world.to_scale()):
        raise OpError("UNSUPPORTED_CAPABILITY", "grip distances are metric: a scaled prop is not qualified")


def child_of(prop, name, rig, bone_name, world):
    """CHILD_OF whose inverse is chosen so the prop sits at `world` for the bone's current pose."""
    constraint = prop.constraints.new("CHILD_OF")
    constraint.name = name
    constraint.target = rig
    constraint.subtarget = bone_name
    parent = rig.matrix_world @ rig.pose.bones[bone_name].matrix
    constraint.inverse_matrix = parent.inverted() @ world @ prop.matrix_basis.inverted()
    return constraint


def set_frame(frame):
    bpy.context.scene.frame_set(int(frame))
    bpy.context.view_layer.update()


def apply(ctx, request, builder):
    plan = ctx.inputs["interaction_plan"]
    scene = bpy.context.scene
    interaction_id = plan["interaction_id"]
    known = registry(scene)
    if interaction_id in known:
        raise OpError(
            "SCENE_CONFLICT", "interaction already applied in this scene; plan a new interaction_id"
        )
    giver, receiver = plan["giver"], plan["receiver"]
    rigs = {p["instance_id"]: participant_rig(p["instance_id"]) for p in (giver, receiver)}
    controls = {instance_id: controls_for(ctx, rig) for instance_id, rig in rigs.items()}
    prop = prop_object(plan["prop_instance_id"])
    refuse_other_authority(prop)
    start, last = plan["frame_range"]["start"], plan["frame_range"]["end_exclusive"] - 1
    handoff, overlap = plan["handoff_frame"], plan["overlap_frames"]
    hold = (handoff - overlap, handoff + overlap)
    current = scene.frame_current
    actions = {}

    def reach(participant, target):
        rig, roles = rigs[participant["instance_id"]], controls[participant["instance_id"]]
        previous = rig.animation_data.action if rig.animation_data else None
        previous_slot = rig.animation_data.action_slot if rig.animation_data else None
        name = f"{interaction_id}.{participant['instance_id']}"
        action, _slot, bag = slotted.ensure_action(rig, f"{rig.name}.{name}")
        # The new Action is only a container here: evaluate the scene as it is, not this clip alone.
        rig.animation_data.action = previous
        if previous_slot is not None:
            rig.animation_data.action_slot = previous_slot
        info = author_hand_reach(rig, roles, bag, participant["hand"], target, start, hold[0], hold[1], last)
        refuse_overlap(rig, action)
        action.use_fake_user = True
        action["fluidblend_interaction_id"] = interaction_id
        add_strip(rig, action, "hands", name, start, {"start": start, "end_exclusive": last})
        actions[participant["instance_id"]] = {
            "action": action.name,
            "channels": sorted(channels(action)),
            **info,
        }

    try:
        set_frame(hold[0])
        if plan.get("meeting_point"):
            meeting = Vector(plan["meeting_point"])
        else:
            shoulders = [
                rigs[p["instance_id"]].matrix_world
                @ controls[p["instance_id"]][f"{p['hand']}_upper_arm_fk"].head
                for p in (giver, receiver)
            ]
            meeting = (shoulders[0] + shoulders[1]) / 2 - Vector((0, 0, LOWER_MEETING_M))
        reach(giver, meeting)
        # Attach with a known offset: the primary grip sits in the giver's palm from the first frame.
        set_frame(start)
        giver_rig = rigs[giver["instance_id"]]
        palm = measures.bone_point(giver_rig, hand_point(controls[giver["instance_id"]], giver["hand"]))
        attached = Matrix.Translation(palm - grip_world(prop, "primary")) @ prop.matrix_world
        giver_bone = controls[giver["instance_id"]][f"{giver['hand']}_hand_deform"].name
        held_by_giver = child_of(prop, f"fluidblend.{interaction_id}.giver", giver_rig, giver_bone, attached)
        # The receiver aims at where the secondary grip really is once the giver holds still.
        set_frame(handoff)
        reach(receiver, grip_world(prop, "secondary"))
        set_frame(handoff)
        receiver_rig = rigs[receiver["instance_id"]]
        receiver_bone = controls[receiver["instance_id"]][f"{receiver['hand']}_hand_deform"].name
        # Same world matrix through either parent at the hand-off frame: no pop when ownership moves.
        held_by_receiver = child_of(
            prop,
            f"fluidblend.{interaction_id}.receiver",
            receiver_rig,
            receiver_bone,
            prop.matrix_world.copy(),
        )
        held_by_receiver.influence = 0.0
        prop_action, _slot, bag = slotted.ensure_action(prop, f"{prop.name}.{interaction_id}")
        prop_action.use_fake_user = True
        prop_action["fluidblend_interaction_id"] = interaction_id
        for constraint, before, after in ((held_by_giver, 1, 0), (held_by_receiver, 0, 1)):
            curve = slotted.fcurve(bag, f'constraints["{constraint.name}"].influence')
            slotted.set_keys(curve, [(start, before), (handoff, after)], interpolation="CONSTANT")
        record = {
            "plan": plan,
            "meeting_point": list(meeting),
            "prop_action": prop_action.name,
            "constraints": {"giver": held_by_giver.name, "receiver": held_by_receiver.name},
            "control_points": {
                p["instance_id"]: hand_point(controls[p["instance_id"]], p["hand"]) for p in (giver, receiver)
            },
            "actions": actions,
        }
        report = measure(ctx, record)
    finally:
        set_frame(current)
    if not report["technical_pass"]:
        raise OpError(
            "VALIDATION_FAILED",
            "hand-off does not meet its own measurements; nothing was published",
            details={"failed": measures.failures(report["measurements"]), "checks": report["checks"]},
        )
    known[interaction_id] = record
    scene[REGISTRY] = json.dumps(known)
    save_version(ctx, request, builder)
    builder.write_report(
        "interaction-apply.json", {**report, "meeting_point": list(meeting), "actions": actions}
    )
    builder.changed("interaction", interaction_id, "created")
    builder.metrics.update(summary(report))


def validate(ctx, request, builder):
    interaction_id = request["parameters"]["interaction_id"]
    record = registry(bpy.context.scene).get(interaction_id)
    if record is None:
        raise OpError("VALIDATION_FAILED", f"no applied interaction in this scene: {interaction_id}")
    report = measure(ctx, record)
    builder.write_report("interaction-validation.json", report)
    builder.metrics.update(summary(report))
    if not report["technical_pass"]:
        builder.warn("interaction measurements failed; see interaction-validation.json")


def summary(report):
    worst = {}
    for item in report["measurements"]:
        worst[item["kind"]] = max(worst.get(item["kind"], 0.0), item["value"])
    return {
        "technical_pass": report["technical_pass"],
        "contact_error_max_m": worst.get("contact_error"),
        "handoff_jump_m": worst.get("handoff_jump"),
        "handoff_rotation_jump_rad": worst.get("handoff_rotation_jump"),
        "failed_checks": [name for name, check in report["checks"].items() if not check["passed"]],
    }


def measure(ctx, record):
    """Contacts in the prop's space, jump at the transfer, single authority, no constraint cycle."""
    plan = record["plan"]
    prop = prop_object(plan["prop_instance_id"])
    rigs = {p["instance_id"]: participant_rig(p["instance_id"]) for p in (plan["giver"], plan["receiver"])}
    records = []
    for window in plan["windows"]:
        contact = {
            "effector": f"{window['name']}:{window['participant']}",
            "control_point": record["control_points"][window["participant"]],
            "support_instance_id": plan["prop_instance_id"],
            "frame_range": window["frame_range"],
            "anchor": list(grip_local(prop, window["grip"])),
        }
        records += measures.contact_records(
            rigs[window["participant"]],
            [contact],
            quality=ctx.quality,
            supports={plan["prop_instance_id"]: prop},
        )
    handoff = plan["handoff_frame"]
    records += measures.object_jump_records(
        prop,
        [handoff - 1, handoff, handoff + 1],
        effector=plan["prop_instance_id"],
        position_tolerance=ctx.quality.get("handoff_jump_max_m", 0.005),
        rotation_tolerance=ctx.quality.get("handoff_rotation_jump_max_rad", 0.01),
    )
    checks = {"single_authority": authority(prop, record, plan), "no_constraint_cycle": cycles(prop, rigs)}
    passed = not measures.failures(records) and all(check["passed"] for check in checks.values())
    return {
        "interaction_id": plan["interaction_id"],
        "technical_pass": passed,
        "measurements": records,
        "checks": checks,
        "visual_review": "pending",
        "limits": [
            "palm control points against the prop's grip points, in the prop's space, every frame",
            "stationary characters, rigid prop, no finger pose, no body or prop intersection test",
            "technical measurement, not an artistic approval of the gesture",
        ],
    }


def authority(prop, record, plan):
    """At every frame exactly one of the two hand constraints owns the prop, as the plan orders."""
    names = record["constraints"]
    violations = []
    extra = [c.name for c in prop.constraints if c.name not in names.values()]
    if prop.parent is not None or extra:
        violations.append({"parent": prop.parent.name if prop.parent else None, "other_constraints": extra})
    if any(name not in prop.constraints for name in names.values()):
        return {"passed": False, "violations": [{"missing_constraints": sorted(names.values())}]}
    expected = {"giver": plan["ownership"][0], "receiver": plan["ownership"][1]}
    scene = bpy.context.scene
    current = scene.frame_current
    try:
        for frame in measures.window_frames(plan["frame_range"]):
            set_frame(frame)
            for role, owner in expected.items():
                inside = owner["frame_range"]["start"] <= frame < owner["frame_range"]["end_exclusive"]
                influence = prop.constraints[names[role]].influence
                if abs(influence - (1.0 if inside else 0.0)) > 1e-6 and len(violations) < 20:
                    violations.append({"frame": frame, "role": role, "influence": influence})
    finally:
        set_frame(current)
    transform_curves = (
        [
            fc.data_path
            for fc in slotted.iter_fcurves(prop.animation_data.action)
            if fc.data_path in ("location", "rotation_euler", "rotation_quaternion", "scale")
        ]
        if prop.animation_data and prop.animation_data.action
        else []
    )
    if transform_curves:
        violations.append({"animated_transform": sorted(set(transform_curves))})
    return {"passed": not violations, "violations": violations}


def cycles(prop, rigs):
    """No participant may depend on the prop or on the other participant: the prop follows, only."""
    forbidden = {prop, *rigs.values()}
    found = []
    for instance_id, rig in rigs.items():
        constraints = [(None, c) for c in rig.constraints]
        constraints += [(bone.name, c) for bone in rig.pose.bones for c in bone.constraints]
        for bone_name, constraint in constraints:
            target = getattr(constraint, "target", None)
            if target in forbidden and target != rig:
                found.append({"instance_id": instance_id, "bone": bone_name, "constraint": constraint.name})
    return {"passed": not found, "violations": found}
