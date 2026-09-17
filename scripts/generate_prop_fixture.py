"""Run with locked Blender: --background --factory-startup --disable-autoexec --python <this> -- <out.blend>

Original geometry (a 0.35 m baton), no external input: CC0, see licenses/baton.md. The origin is the
primary grip; the secondary grip sits 0.15 m further along local Z, so two hands never coincide.
The file is generated on demand by the tests instead of being versioned as a binary.
"""

import sys

import bpy

GRIPS = {"primary": [0.0, 0.0, 0.0], "secondary": [0.0, 0.0, 0.15]}


def generate(output):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.015, depth=0.35, location=(0, 0, 0.075))
    baton = bpy.context.object
    baton.name = "baton"
    # Bake the offset into the mesh so the object origin is the primary grip, with identity transforms.
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    bpy.ops.wm.save_as_mainfile(filepath=output, compress=True)


if __name__ == "__main__":
    generate(sys.argv[sys.argv.index("--") + 1])
