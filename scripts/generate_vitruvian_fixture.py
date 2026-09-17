"""Run with locked Blender --background --factory-startup --disable-autoexec --python ...

Inputs are pinned CC0 data in FLUIDBLEND_FIXTURE_CACHE. No CharMorph code is copied or installed.
NumPy is used only by this offline preparation script, never by the production runtime.
"""

import hashlib
import json
import os
from pathlib import Path

import bpy
import numpy as np

REVISION = "c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44"
INPUTS = {
    "char.blend": "7e9581c30b48f1409dfeec4a5ec0736014318fc8825ca6d4728f2b543bb02126",
    "rigs.blend": "7d4cb80660f2ad1a3319fd7a0783f1069e79094fc466cec15e78f5769cf1ee79",
    "weights-rigify.npz": "23ffe61513dcefe568b75218d4859a927540e5f34b4175b2f90479c884be8257",
}


def generate():
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("fixture generation requires Blender 5.2.2")
    cache = Path(os.environ["FLUIDBLEND_FIXTURE_CACHE"])
    output = Path(__file__).resolve().parents[1] / "fixtures" / "vitruvian"
    if (output / "character.blend").exists():
        raise RuntimeError("fixture exists; use an explicit migration rather than overwrite")
    for name, digest in INPUTS.items():
        if hashlib.sha256((cache / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"unverified input: {name}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.preferences.addon_enable(module="rigify")
    for file, name in (("char.blend", "cm_vitruvian"), ("rigs.blend", "metarig")):
        with bpy.data.libraries.load(str(cache / file), link=False) as (_src, dst):
            dst.objects = [name]
        bpy.context.scene.collection.objects.link(dst.objects[0])
    mesh = bpy.data.objects["cm_vitruvian"]
    meta = bpy.data.objects["metarig"]
    mesh.modifiers.clear()
    mesh.data.materials.clear()
    mesh.vertex_groups.clear()
    bpy.context.view_layer.objects.active = meta
    meta.select_set(True)
    bpy.ops.pose.rigify_generate()
    rig = bpy.context.object
    with np.load(cache / "weights-rigify.npz", allow_pickle=False) as weights:
        offset = 0
        names = weights["names"].item().decode().split("\0")
        for name, count in zip(names, weights["cnt"], strict=True):
            count = int(count)
            group = mesh.vertex_groups.new(name=name)
            for index, value in zip(
                weights["idx"][offset : offset + count],
                weights["weights"][offset : offset + count],
                strict=True,
            ):
                group.add([int(index)], float(value), "REPLACE")
            offset += int(count)
        assert offset == len(weights["idx"])
    modifier = mesh.modifiers.new("Skin", "ARMATURE")
    modifier.object = rig
    modifier.use_deform_preserve_volume = True
    mesh.parent = rig
    mesh["fluidblend_part_of"] = "hero-01"
    rig["fluidblend_instance_id"] = "hero-01"
    rig["fluidblend_asset_id"] = "vitruvian"
    rig["fluidblend_rig_profile"] = "rigify/0.6.10"
    rig["fluidblend_kind"] = "character"
    bpy.data.objects.remove(meta, do_unlink=True)
    material = bpy.data.materials.new("Reference neutral")
    material.diffuse_color = (0.32, 0.42, 0.5, 1)
    mesh.data.materials.append(material)
    # Strip upstream embedded text and unused materials/images; generated control
    # geometry and evaluated rig constraints stay in the asset.
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    for material in list(bpy.data.materials):
        if not material.users:
            bpy.data.materials.remove(material)
    for image in list(bpy.data.images):
        if not image.users:
            bpy.data.images.remove(image)
    deform = {b.name for b in rig.data.bones if b.use_deform}
    groups = {g.index for g in mesh.vertex_groups if g.name in deform}
    unweighted = [
        v.index for v in mesh.data.vertices if not any(g.group in groups and g.weight > 0 for g in v.groups)
    ]
    missing = [g.name for g in mesh.vertex_groups if g.name.startswith("DEF-") and g.name not in deform]
    if unweighted or missing:
        raise RuntimeError(
            f"invalid skin: {len(unweighted)} uninfluenced vertices; missing deformers {missing}"
        )
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "character.blend"), compress=True)
    import rigify

    manifest = {
        "asset_id": "vitruvian",
        "version": 1,
        "license": "CC0-1.0",
        "source": "https://github.com/Upliner/CharMorph-Vitruvian",
        "source_revision": REVISION,
        "inputs": INPUTS,
        "blender": bpy.app.version_string,
        "rigify_version": list(rigify.bl_info["version"]),
        "rig_profile": "rigify/0.6.10",
        "sha256": hashlib.sha256((output / "character.blend").read_bytes()).hexdigest(),
        "objects": [rig.name, mesh.name],
        "armature": rig.name,
        "vertices": len(mesh.data.vertices),
        "bones": len(rig.data.bones),
        "uninfluenced_vertices": len(unweighted),
        "missing_deformers": missing,
        "limits": [
            "neutral body fixture; facial shape keys not yet supplied",
            "no external textures or particle hair",
        ],
    }
    (output / "asset.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("FIXTURE=" + json.dumps(manifest))


generate()
