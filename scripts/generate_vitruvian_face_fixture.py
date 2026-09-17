"""Run with locked Blender --background --factory-startup --disable-autoexec --python ...

Derives `fixtures/vitruvian-face/` from the body fixture: same mesh and rig, plus shape keys built
from pinned CC0 facial morphs of the same CharMorph-Vitruvian revision (`morphs/L3/*.npz`: vertex
indices and deltas). The body fixture is only read; its hash is checked first. Inputs are expected in
`FLUIDBLEND_FIXTURE_CACHE/morphs-L3/`. NumPy is used by this offline script only.
"""

import hashlib
import json
import os
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

REVISION = "c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44"
FACE_PROFILE = "charmorph-l3/1"
MORPHS = {
    "p_b_m_21": "440c7da31ae3adbba563b1f00bfb35d4c124b431125663f76b4b134d076b03c8",
    "s_z_15": "6a34fcacb93c7b428656ffc16eabe5018533be09704feb0b2190ce255a68d720",
    "ey_eh_uh_04": "87c9de2c8da12cd3c225dd7c3392c3d1bbcf123298e9148ec10691049d8ee1ef",
    "aa_02": "1a20f67fbc1050c8f5566124ab58348e497d9c9086fd45d503b2805bd68ab7c3",
    "ao_03": "0e60c352bc00a00332f19aff647d9d5d18b07313c28b9d13617ffec2b24357fc",
    "w_uw_07": "4bd08837132b38dcee0e0faa3091fbf8dff0dedc2705ca818b380f8e5378fde1",
    "f_v_18": "3e3a6c6eb3c0c5a6cefc368f56ed59a702f3aba73ebd2007cdd5ac362931d727",
    "l_14": "7357f79bc95fee27e3aea986175a88c65087c7e250c2afbee5ed4629f2b9e85f",
    "Happy": "5ba840aa7fb8f65157874ea18b1f64c0533aa4b38b9d5e1d7e78c412167f4871",
    "Sad": "5aa2175a1198c67b17f826d1141d1b014078086f2d2c1b4fbdf241978a82f0d6",
    "Angry": "f44673ab75cda115889c2f0ffbddaab607db20ff57c378a6291c2858df748580",
    "Scared": "13093c93aae043c46662df2e691f4186c9a20f3ba6f11938b88c0bdf9b91ce6d",
    "Eyes_Closed_Max": "f031235bf45eb5267f421b21397b1042a3a9e222105bf841db288a8fce423644",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate():
    if tuple(bpy.app.version) != (5, 2, 2):
        raise RuntimeError("fixture generation requires Blender 5.2.2")
    kit = Path(__file__).resolve().parents[1]
    body = kit / "fixtures" / "vitruvian"
    body_meta = json.loads((body / "asset.json").read_text(encoding="utf-8"))
    if sha256(body / "character.blend") != body_meta["sha256"]:
        raise RuntimeError("body fixture hash differs from its asset.json")
    output = kit / "fixtures" / "vitruvian-face"
    if (output / "character.blend").exists():
        raise RuntimeError("fixture exists; use an explicit migration rather than overwrite")
    cache = Path(os.environ["FLUIDBLEND_FIXTURE_CACHE"]) / "morphs-L3"
    for name, digest in MORPHS.items():
        if sha256(cache / f"{name}.npz") != digest:
            raise RuntimeError(f"unverified input: {name}.npz")
    bpy.ops.wm.open_mainfile(filepath=str(body / "character.blend"), load_ui=False, use_scripts=False)
    mesh = bpy.data.objects["cm_vitruvian"]
    rig = bpy.data.objects[body_meta["armature"]]
    count = len(mesh.data.vertices)
    mesh.shape_key_add(name="Basis", from_mix=False)
    ranges = {}
    for name in MORPHS:
        with np.load(cache / f"{name}.npz", allow_pickle=False) as morph:
            indices, deltas = morph["idx"].astype(np.int64), morph["delta"].astype(np.float64)
        if indices.max() >= count or len(indices) != len(deltas) or not np.isfinite(deltas).all():
            raise RuntimeError(f"morph does not fit the mesh: {name}")
        key = mesh.shape_key_add(name=name, from_mix=False)
        key.slider_min, key.slider_max = 0.0, 1.0
        for index, delta in zip(indices, deltas, strict=True):
            key.data[int(index)].co = mesh.data.vertices[int(index)].co + Vector(delta)
        ranges[name] = {"vertices": int(len(indices)), "max_delta_m": float(np.abs(deltas).max())}
    rig["fluidblend_asset_id"] = "vitruvian-face"
    rig["fluidblend_face_profile"] = FACE_PROFILE
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "character.blend"), compress=True)
    metadata = {
        **{k: body_meta[k] for k in ("license", "source", "source_revision", "blender", "rigify_version")},
        "asset_id": "vitruvian-face",
        "version": 1,
        "derived_from": {"asset_id": body_meta["asset_id"], "sha256": body_meta["sha256"]},
        "inputs": {f"morphs/L3/{name}.npz": digest for name, digest in MORPHS.items()},
        "rig_profile": body_meta["rig_profile"],
        "face_profile": FACE_PROFILE,
        "sha256": sha256(output / "character.blend"),
        "objects": body_meta["objects"],
        "armature": body_meta["armature"],
        "vertices": count,
        "shape_keys": ranges,
        "limits": [
            "facial shape keys only: the Rigify face bones still carry no skin weights",
            "visemes and expressions are upstream sculpted morphs, not reviewed against speech here",
            "no external textures or particle hair",
        ],
    }
    (output / "asset.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("FLUIDBLEND_FACE_FIXTURE=" + json.dumps({"sha256": metadata["sha256"], "shape_keys": len(ranges)}))


if __name__ == "__main__":
    generate()
