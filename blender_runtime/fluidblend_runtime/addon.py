"""Operators exposed to live mode (`bpy.ops.fluidblend.*`). Registered only when the runtime is an enabled add-on.

The MCP add-on safe mode allows `import bpy` and operator calls, so the engine transmits nothing but
`bpy.ops.fluidblend.run_request(request_path=..., result_path=...)` — the approved runtime does the work.
"""

from __future__ import annotations

import json
import traceback

import bpy
from bpy.props import StringProperty


class FLUIDBLEND_OT_identity(bpy.types.Operator):
    """Print the identity of the open session (project, shot, revision, runtime version, dirty flag)."""

    bl_idname = "fluidblend.identity"
    bl_label = "fluidblend: session identity"
    bl_options = {"INTERNAL"}

    def execute(self, context):  # noqa: ANN001
        from fluidblend_runtime import identity

        print("FLUIDBLEND_IDENTITY=" + json.dumps(identity()), flush=True)
        return {"FINISHED"}


class FLUIDBLEND_OT_run_request(bpy.types.Operator):
    """Run one typed operation request on the open scene and write its result file."""

    bl_idname = "fluidblend.run_request"
    bl_label = "fluidblend: run request"
    bl_options = {"INTERNAL"}

    request_path: StringProperty(name="Request", subtype="FILE_PATH")  # type: ignore[valid-type]
    result_path: StringProperty(name="Result", subtype="FILE_PATH")  # type: ignore[valid-type]

    def execute(self, context):  # noqa: ANN001
        from fluidblend_runtime import main

        try:
            main(self.request_path, self.result_path)
        except Exception as exc:  # noqa: BLE001 - reported to the engine, never swallowed
            print(
                "FLUIDBLEND_RESULT_ERROR="
                + json.dumps({"error": repr(exc), "traceback": traceback.format_exc()[-2000:]}),
                flush=True,
            )
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class FLUIDBLEND_OT_open_file(bpy.types.Operator):
    """Open a .blend in the live session (used after a version is published)."""

    bl_idname = "fluidblend.open_file"
    bl_label = "fluidblend: open file"
    bl_options = {"INTERNAL"}

    filepath: StringProperty(name="File", subtype="FILE_PATH")  # type: ignore[valid-type]
    expected_identity: StringProperty(name="Expected identity", default="")  # type: ignore[valid-type]

    def execute(self, context):  # noqa: ANN001
        from fluidblend_runtime import identity, live_state

        if self.expected_identity:
            expected = json.loads(self.expected_identity)
            current = identity()
            if not live_state.matches(expected) or any(
                current.get(key) != expected.get(key)
                for key in ("blend_path", "project_id", "shot_id", "revision", "is_dirty")
            ):
                print('FLUIDBLEND_OPENED={"ok": false, "error": "concurrent edit preserved"}', flush=True)
                return {"CANCELLED"}
        result = bpy.ops.wm.open_mainfile(filepath=self.filepath, load_ui=False, use_scripts=False)
        print(
            "FLUIDBLEND_OPENED=" + json.dumps({"ok": "FINISHED" in result, "filepath": bpy.data.filepath}),
            flush=True,
        )
        return {"FINISHED"} if "FINISHED" in result else {"CANCELLED"}


CLASSES = (FLUIDBLEND_OT_identity, FLUIDBLEND_OT_run_request, FLUIDBLEND_OT_open_file)


def register() -> None:
    from fluidblend_runtime import live_state

    for cls in CLASSES:
        bpy.utils.register_class(cls)
    live_state.register()


def unregister() -> None:
    from fluidblend_runtime import live_state

    live_state.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
