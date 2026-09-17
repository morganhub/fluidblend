import hashlib
import json

import bpy
from mathutils import Vector

from fluidblend_runtime import blendio, render
from fluidblend_runtime.errors import OpError
from fluidblend_runtime.production import save_version


def run(ctx, request, builder):
    previous_revision = int(bpy.context.scene.get("fluidblend_revision", 0))
    if ctx.work_blend is None:
        blendio.new_empty()
    scene = bpy.context.scene
    scene["fluidblend_revision"] = previous_revision
    instances = []
    for asset in ctx.inputs["assets"]:
        if blendio.find_instance_object(asset["instance_id"]) is not None:
            raise OpError(
                "SCENE_CONFLICT", "asset instance already exists; no implicit shot reset or replacement"
            )
        with open(asset["blend_path"], "rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != asset["sha256"]:
                raise OpError("SCENE_CONFLICT", "asset changed after admission")
        with bpy.data.libraries.load(asset["blend_path"], link=False) as (src, dst):
            if set(asset["objects"]) - set(src.objects):
                raise OpError("VALIDATION_FAILED", "manifest names missing objects")
            dst.objects = list(asset["objects"])
        imported = dict(zip(asset["objects"], dst.objects, strict=True))
        kind = asset.get("kind", "character")
        root = imported.get(asset["armature"] if kind == "character" else asset["root_object"])
        if kind == "character" and (root is None or root.type != "ARMATURE"):
            raise OpError("VALIDATION_FAILED", "manifest armature is invalid")
        if kind == "prop" and (root is None or root.type == "ARMATURE" or root.parent is not None):
            raise OpError("VALIDATION_FAILED", "manifest prop root must be an unparented non-armature object")
        for obj in imported.values():
            scene.collection.objects.link(obj)
            if obj != root:
                obj["fluidblend_part_of"] = asset["instance_id"]
        root["fluidblend_instance_id"] = asset["instance_id"]
        root["fluidblend_asset_id"] = asset["asset_id"]
        root["fluidblend_kind"] = kind
        if kind == "character":
            root["fluidblend_rig_profile"] = asset["rig_profile"]
            # The admitted manifest is the authority, not a tag carried by the imported file.
            if asset.get("face_profile"):
                root["fluidblend_face_profile"] = asset["face_profile"]
            elif "fluidblend_face_profile" in root:
                del root["fluidblend_face_profile"]
        else:
            root["fluidblend_grips"] = json.dumps(asset["grips"])
        # Placement of the instance root at import, not a transform applied to skinned data.
        root.location += Vector(asset.get("location", [0, 0, 0]))
        root.rotation_euler.z += asset.get("rotation_z", 0.0)
        instances.append(
            {
                "instance_id": asset["instance_id"],
                "asset_id": asset["asset_id"],
                "version": asset["version"],
                "sha256": asset["sha256"],
            }
        )
    missing = blendio.missing_external_files()
    if missing:
        raise OpError(
            "VALIDATION_FAILED", "asset has missing external references", details={"missing": missing}
        )
    libraries = [
        {"id": block.name, "path": block.library.filepath}
        for block in bpy.data.user_map()
        if block.library is not None
    ]
    if libraries:
        raise OpError(
            "UNSUPPORTED_CAPABILITY",
            "linked external libraries require a separately qualified import",
            details={"libraries": libraries},
        )
    if scene.camera is None:
        camera_data = bpy.data.cameras.new("Camera")
        camera = bpy.data.objects.new("Camera", camera_data)
        scene.collection.objects.link(camera)
        spec = (ctx.shot or {}).get("camera", {})
        camera.location = spec.get("location", [4, -6, 2.5])
        camera.rotation_euler = (
            (Vector(spec.get("look_at", [0, 0, 1])) - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
        camera_data.lens = spec.get("focal_length_mm", 35)
        scene.camera = camera
    if ctx.work_blend is None:
        scene.frame_start = ctx.shot["frame_range"]["start"]
        scene.frame_end = ctx.shot["frame_range"]["end_exclusive"] - 1
        render.configure(
            scene,
            engine=ctx.preview_engine,
            width=ctx.preview_width,
            height=ctx.preview_height,
            fps_numerator=ctx.fps_numerator,
            fps_denominator=ctx.fps_denominator,
        )
    save_version(ctx, request, builder)
    builder.write_report(
        "shot-build.json", {"instances": instances, "import_mode": "append", "scripts_enabled": False}
    )
    builder.metrics["instances"] = len(instances)
