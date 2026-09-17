"""Shared rig and version operations, without applying character transforms."""

import json
import math

import bpy
from mathutils import Vector

from fluidblend_runtime import RUNTIME_VERSION, blendio
from fluidblend_runtime.errors import OpError


def character(request):
    instance = request["target"].get("instance_id")
    obj = blendio.find_instance_object(instance) if instance else None
    if obj is None or obj.type != "ARMATURE":
        raise OpError("VALIDATION_FAILED", "target.instance_id must identify an armature")
    return obj


def prop_object(instance_id):
    obj = blendio.find_instance_object(instance_id)
    if obj is None or obj.get("fluidblend_kind") != "prop":
        raise OpError("VALIDATION_FAILED", f"no prop instance in the scene: {instance_id}")
    return obj


def grip_local(prop, name):
    grips = json.loads(prop.get("fluidblend_grips", "{}"))
    if name not in grips:
        raise OpError("VALIDATION_FAILED", f"prop has no {name} grip", details={"grips": sorted(grips)})
    return Vector(grips[name])


def grip_world(prop, name):
    return prop.matrix_world @ grip_local(prop, name)


def meshes_for(rig):
    return [
        o
        for o in bpy.context.scene.objects
        if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)
    ]


def controls_for(ctx, rig):
    profile = ctx.inputs.get("rig_profile")
    if profile:
        mapping = profile["controls"]
    elif rig.get("fluidblend_rig_profile") == "rigify/0.6.10":
        mapping = ctx.inputs["rigify_controls"]
    else:
        raise OpError("RIG_MAPPING_REQUIRED", "supply a tested semantic rig profile")
    missing = [role for role, name in mapping.items() if not name or name not in rig.pose.bones]
    if missing:
        raise OpError("RIG_MAPPING_REQUIRED", "missing rig controls", details={"missing": missing})
    return {role: rig.pose.bones[name] for role, name in mapping.items()}


def assert_transform_safe(obj):
    if obj.type == "ARMATURE" or obj.animation_data or any(m.type == "ARMATURE" for m in obj.modifiers):
        raise OpError("UNSUPPORTED_CAPABILITY", "character transforms require an explicit migration")


def skin_report(rig):
    deform = {b.name for b in rig.data.bones if b.use_deform}
    meshes = []
    for mesh in meshes_for(rig):
        groups = {g.index for g in mesh.vertex_groups if g.name in deform}
        uninfluenced = [
            v.index
            for v in mesh.data.vertices
            if not any(g.group in groups and g.weight > 0 for g in v.groups)
        ]
        meshes.append(
            {
                "name": mesh.name,
                "vertices": len(mesh.data.vertices),
                "uninfluenced_vertices": len(uninfluenced),
                "sample_indices": uninfluenced[:20],
            }
        )
    invalid_scale = any(
        not math.isfinite(v) or abs(v - 1) > 1e-5 for obj in [rig, *meshes_for(rig)] for v in obj.scale
    )
    return {
        "meshes": meshes,
        "skinned": bool(meshes),
        "problematic_scales": invalid_scale,
        "uninfluenced_vertices": sum(m["uninfluenced_vertices"] for m in meshes),
    }


def save_version(ctx, request, builder):
    shot_id = request["target"]["shot_id"]
    scene = bpy.context.scene
    revision = request["target"].get("expected_revision")
    if revision is None:
        revision = int(scene.get("fluidblend_revision", 0))
    blendio.set_identity(
        scene,
        project_id=ctx.project_id,
        shot_id=shot_id,
        revision=revision + 1,
        runtime_version=RUNTIME_VERSION,
    )
    path = ctx.out(f"{shot_id}.blend")
    (blendio.save_copy if ctx.live else blendio.save_as)(path)
    builder.add_file("blend", path)
    builder.changed("shot", shot_id, "versioned")
