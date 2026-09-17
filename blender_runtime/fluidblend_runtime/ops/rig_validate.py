import math
import os

import bpy
from mathutils import Matrix, Vector

from fluidblend_runtime import render
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.production import character, controls_for, meshes_for, skin_report


def positions(meshes):
    graph = bpy.context.evaluated_depsgraph_get()
    return [mesh.matrix_world @ v.co for mesh in meshes for v in mesh.evaluated_get(graph).data.vertices]


def run(ctx, request, builder):
    rig = character(request)
    controls = controls_for(ctx, rig)
    skin = skin_report(rig)
    if not skin["skinned"] or skin["uninfluenced_vertices"] or skin["problematic_scales"]:
        raise OpError("VALIDATION_FAILED", "rig skin or scale checks failed", details=skin)
    scene = bpy.context.scene
    camera_matrix = scene.camera.matrix_world.copy() if scene.camera else None
    original = {b.name: (b.matrix_basis.copy(), b.rotation_mode) for b in rig.pose.bones}
    switches = [
        (controls[f"{side}_{limb}_switch"], controls[f"{side}_{limb}_switch"].get("IK_FK"))
        for side in ("left", "right")
        for limb in ("arm", "leg")
    ]
    if any(value is None for _, value in switches):
        raise OpError("RIG_MAPPING_REQUIRED", "missing IK/FK switch property")
    meshes = meshes_for(rig)
    report = []
    poses = {
        "arms_up": {"left_upper_arm_fk": (0, 0, 1), "right_upper_arm_fk": (0, 0, 1)},
        "bent_elbow": {"left_forearm_fk": (0, -1, 0)},
        "bent_knee": {"left_shin_fk": (0, 0.7, -0.7)},
        "squat": {
            "left_thigh_fk": (0, -0.7, -0.7),
            "right_thigh_fk": (0, -0.7, -0.7),
            "left_shin_fk": (0, 0.7, -0.7),
            "right_shin_fk": (0, 0.7, -0.7),
        },
        "torso_twist": {},
    }
    preview = request["parameters"].get("preview", True)
    if preview:
        render.configure(
            scene,
            engine="WORKBENCH",
            width=ctx.preview_width,
            height=ctx.preview_height,
            fps_numerator=ctx.fps_numerator,
            fps_denominator=ctx.fps_denominator,
        )
    try:
        for bone, _ in switches:
            bone["IK_FK"] = 1.0
        for bone in rig.pose.bones:
            bone.matrix_basis.identity()
        bpy.context.view_layer.update()
        rest = positions(meshes)
        for name, changes in poses.items():
            for bone in rig.pose.bones:
                bone.matrix_basis.identity()
            bpy.context.view_layer.update()
            for role, direction in changes.items():
                bone = controls[role]
                matrix = bone.matrix.copy()
                rotation = (
                    matrix.to_3x3().col[1].normalized().rotation_difference(Vector(direction).normalized())
                )
                bone.matrix = (
                    Matrix.Translation(matrix.translation)
                    @ rotation.to_matrix().to_4x4()
                    @ Matrix.Translation(-matrix.translation)
                    @ matrix
                )
                bpy.context.view_layer.update()
            if name == "torso_twist":
                bone = controls["chest"]
                matrix = bone.matrix.copy()
                bone.matrix = (
                    Matrix.Translation(matrix.translation)
                    @ Matrix.Rotation(0.4, 4, "Z")
                    @ Matrix.Translation(-matrix.translation)
                    @ matrix
                )
            if name == "squat":
                controls["torso"].location.z -= 0.18
            bpy.context.view_layer.update()
            evaluated = positions(meshes)
            finite = all(math.isfinite(c) for p in evaluated for c in p)
            displacement = max((a - b).length for a, b in zip(rest, evaluated, strict=True))
            report.append(
                {
                    "pose": name,
                    "finite": finite,
                    "max_displacement_m": displacement,
                    "passed": finite and displacement > 1e-5,
                }
            )
            if preview:
                if scene.camera:
                    # Frame the evaluated deformation, including raised hands.
                    center = Vector(
                        tuple(
                            (min(v[i] for v in evaluated) + max(v[i] for v in evaluated)) / 2
                            for i in range(3)
                        )
                    )
                    orientation = scene.camera.matrix_world.to_quaternion()
                    local = [orientation.inverted() @ (v - center) for v in evaluated]
                    tan_x = math.tan(scene.camera.data.angle_x / 2)
                    tan_y = tan_x * scene.render.resolution_y / scene.render.resolution_x
                    distance = max(max(abs(v.x) / tan_x, abs(v.y) / tan_y) * 1.15 + v.z for v in local)
                    scene.camera.location = center + orientation @ Vector((0, 0, distance))
                scene.render.filepath = ctx.out("poses", name + ".png")
                bpy.ops.render.render(write_still=True)
    finally:
        if camera_matrix is not None:
            scene.camera.matrix_world = camera_matrix
        for bone in rig.pose.bones:
            matrix, mode = original[bone.name]
            bone.rotation_mode = mode
            bone.matrix_basis = matrix
        for bone, value in switches:
            bone["IK_FK"] = value
        bpy.context.view_layer.update()
    passed = all(p["passed"] for p in report)
    builder.write_report(
        "rig-validation.json",
        {
            **skin,
            "poses": report,
            "technical_pass": passed,
            "visual_review": "pending",
            "limits": ["finite deformation and response, not anatomical or artistic approval"],
        },
    )
    if preview:
        builder.add_dir("frames", os.path.join(ctx.out_dir, "poses"))
    builder.metrics.update({"technical_pass": passed, "tested_poses": len(report)})
    if not passed:
        raise OpError("VALIDATION_FAILED", "a test pose did not produce finite deformation")
