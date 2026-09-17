"""Director panel (§12.4): Preview / Apply / Revert of an adjustment from inside Blender.

The panel owns no logic. Each button writes a typed request and runs the kit's own CLI in a separate
process, exactly as a terminal would; a timer reads the outcome. Nothing is keyed or changed in the
open session, so it stays clean and a slider drag can never pile up keyframes. After Apply or Revert
the session is pointed at the published version through the identity-guarded `open_file`.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from fluidblend_runtime import director_overlay

UNSAVED = (
    "unsaved changes in this scene (even a selection counts). Do not save over a published version: "
    "reload the file to drop them, then retry"
)
DEBOUNCE_S = 0.6
POLL_S = 0.25
_run: dict | None = None
_pending_at: float | None = None


def project_root() -> str | None:
    folder = os.path.dirname(bpy.data.filepath)
    while folder and os.path.dirname(folder) != folder:
        if os.path.isfile(os.path.join(folder, "project.json")):
            return folder
        folder = os.path.dirname(folder)
    return None


def cli_command() -> list[str] | None:
    manifest = os.path.join(os.path.dirname(__file__), "RUNTIME_MANIFEST.json")
    try:
        with open(manifest, encoding="utf-8") as handle:
            return list(json.load(handle)["cli"])
    except (OSError, ValueError, KeyError):
        return None


def latest_version() -> str | None:
    """Newest published work version of the open shot. The engine always works on that one, so a
    session left on an older file would show one scene while the buttons act on another."""
    root, shot = project_root(), bpy.context.scene.get("fluidblend_shot_id")
    if not root or not shot:
        return None
    work = os.path.join(root, "shots", shot, "work")
    try:
        versions = sorted(v for v in os.listdir(work) if v[:1] == "v" and v[1:].isdigit())
    except OSError:
        return None
    for version in reversed(versions):
        path = os.path.join(work, version, f"{shot}.blend")
        if os.path.isfile(path):
            return path
    return None


def is_stale() -> bool:
    latest = latest_version()
    return bool(latest) and os.path.normcase(os.path.realpath(latest)) != os.path.normcase(
        os.path.realpath(bpy.data.filepath)
    )


def applied_fixes() -> list[str]:
    try:
        return sorted(json.loads(bpy.context.scene.get("fluidblend_adjustments", "{}")))
    except ValueError:
        return []


def redraw() -> None:
    """A timer changes the state outside any UI event: without this the sidebar keeps showing the
    previous status until the mouse happens to pass over it."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def state(context=None):
    return (context or bpy.context).window_manager.fluidblend_director


def _changed(self, context):  # noqa: ANN001 - bpy update callback
    """A bounded slider moved: one preview once the hand rests, never one per drag event."""
    global _pending_at
    if not self.auto_preview:
        return
    _pending_at = time.monotonic() + DEBOUNCE_S
    if not bpy.app.timers.is_registered(_debounce):
        bpy.app.timers.register(_debounce, first_interval=DEBOUNCE_S)


def _debounce():
    global _pending_at
    if _pending_at is None:
        return None
    remaining = _pending_at - time.monotonic()
    if remaining > 0:
        return remaining
    if _run is not None:
        return POLL_S
    _pending_at = None
    launch("preview")
    return None


# Rig profiles contact_lock can drive: they have IK controls and a semantic mapping.
SUPPORTED_RIGS = ("rigify/0.6.10",)


def _instances() -> list:
    return [o for o in bpy.data.objects if o.type == "ARMATURE" and o.get("fluidblend_instance_id")]


def characters() -> list[str]:
    """Characters the tool can drive; a baked export skeleton has no IK control left."""
    return sorted(
        obj["fluidblend_instance_id"]
        for obj in _instances()
        if obj.get("fluidblend_rig_profile") in SUPPORTED_RIGS and not obj.get("fluidblend_baked")
    )


def unsupported_characters() -> list[str]:
    """Characters of the scene that are listed nowhere: the panel says why instead of hiding them."""
    usable = set(characters())
    return sorted(
        o["fluidblend_instance_id"] for o in _instances() if o["fluidblend_instance_id"] not in usable
    )


def wrapped(layout, text: str, width: int = 34, icon: str = "NONE") -> None:
    """Sidebar labels do not wrap: a refusal cut in the middle is worse than no message."""
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            layout.label(text=line, icon=icon)
            line, icon = word, "BLANK1" if icon != "NONE" else "NONE"
        else:
            line = f"{line} {word}".strip()
    if line:
        layout.label(text=line, icon=icon)


# Blender keeps pointers to dynamic enum strings: the list must outlive the callback.
_character_items: list[tuple[str, str, str]] = []


def _character_enum(self, context):  # noqa: ANN001 - bpy items callback
    global _character_items
    _character_items = [(name, name, "Character whose hand or foot slides") for name in characters()]
    return _character_items or [("", "no character", "")]


class FluidblendDirectorState(bpy.types.PropertyGroup):
    """Window-manager state: never saved in the .blend, never dirties the scene."""

    instance_id: EnumProperty(  # type: ignore[valid-type]
        name="Character", description="Character whose hand or foot slides", items=_character_enum
    )
    adjustment_id: StringProperty(  # type: ignore[valid-type]
        name="Fix name",
        default="director-lock",
        description="Name of this fix (lowercase, digits, dashes). Revert removes the fix with this name",
    )
    effector: EnumProperty(  # type: ignore[valid-type]
        name="Limb",
        description="The hand or foot that should stay still",
        items=[(e, e.replace("_", " "), "") for e in ("left_foot", "right_foot", "left_hand", "right_hand")],
    )
    frame_start: IntProperty(  # type: ignore[valid-type]
        name="From", default=1, description="First frame where the limb must stay still"
    )
    frame_end_exclusive: IntProperty(  # type: ignore[valid-type]
        name="Until (excluded)", default=26, description="First frame where the limb is free again"
    )
    max_correction_m: FloatProperty(  # type: ignore[valid-type]
        name="Max correction (m)",
        description="Largest slide the tool may correct. A larger drift means the limb is really "
        "travelling (a step): the tool refuses instead of pinning it",
        default=0.15,
        min=0.01,
        max=0.5,
        update=_changed,
    )
    blend_frames: IntProperty(  # type: ignore[valid-type]
        name="Blend frames",
        description="Frames used to ease the correction in before the window and out after it",
        default=3,
        min=1,
        max=24,
        update=_changed,
    )
    auto_preview: BoolProperty(  # type: ignore[valid-type]
        name="Preview when sliders rest",
        default=False,
        description="Measure again 0.6 s after the last slider move (one preview, however long the drag)",
    )
    busy: BoolProperty(default=False)  # type: ignore[valid-type]
    status: StringProperty(default="idle")  # type: ignore[valid-type]
    last_kind: StringProperty()  # type: ignore[valid-type]
    last_status: StringProperty()  # type: ignore[valid-type]
    last_report: StringProperty()  # type: ignore[valid-type]
    before_m: FloatProperty(default=-1.0)  # type: ignore[valid-type]
    after_m: FloatProperty(default=-1.0)  # type: ignore[valid-type]
    launched: IntProperty(default=0)  # type: ignore[valid-type]


def request_for(kind: str, props, scene, operation_id: str) -> dict:
    parameters = {"adjustment_id": props.adjustment_id}
    if kind != "revert":
        parameters.update(
            tool="contact_lock",
            effector=props.effector,
            frame_range={"start": props.frame_start, "end_exclusive": props.frame_end_exclusive},
            max_correction_m=round(props.max_correction_m, 4),
            blend_frames=props.blend_frames,
        )
    return {
        "schema_version": "1.0",
        "operation": f"adjustment.{kind}",
        "operation_id": operation_id,
        "project_id": scene.get("fluidblend_project_id", ""),
        "target": {"shot_id": scene.get("fluidblend_shot_id", ""), "instance_id": props.instance_id},
        "parameters": parameters,
        "dry_run": False,
    }


def launch(kind: str) -> str | None:
    """Start the CLI for `kind`; returns a refusal message, or None when the process is running."""
    global _run
    props = state()
    root, command = project_root(), cli_command()
    if _run is not None:
        return "an operation is already running"
    if root is None:
        return "the open file is not inside a fluidblend project"
    if command is None:
        return "runtime manifest has no CLI; run `fluidblend runtime install --enable` again"
    if is_stale():
        return "this file is not the latest work version of the shot; open the latest one first"
    if kind != "revert" and props.adjustment_id in applied_fixes():
        return f"'{props.adjustment_id}' is already applied here: Revert it, or choose another fix name"
    if kind == "revert" and props.adjustment_id not in applied_fixes():
        return f"no fix named '{props.adjustment_id}' in this scene"
    if not props.instance_id:
        return "choose a character first"
    if props.frame_end_exclusive - props.frame_start < 2:
        return "the frame window needs at least 2 frames"
    if bpy.data.is_dirty and kind != "preview":
        # The engine works on the published version: unsaved edits would silently be left out.
        # Saving is the wrong advice: it would overwrite a published version (revision conflict).
        return UNSAVED
    from fluidblend_runtime import identity

    operation_id = f"director-{kind}-{props.adjustment_id}-{int(time.time() * 1000)}"
    folder = os.path.join(root, "requests", "director")
    os.makedirs(folder, exist_ok=True)
    request_path = os.path.join(folder, operation_id + ".json")
    with open(request_path, "w", encoding="utf-8") as handle:
        json.dump(request_for(kind, props, bpy.context.scene, operation_id), handle, indent=2)
    output_path = os.path.join(folder, operation_id + ".result.json")
    # Blender's own Python settings must not leak into the engine's interpreter.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    with open(output_path, "w", encoding="utf-8") as output:
        process = subprocess.Popen(  # noqa: S603 - fixed argument list from the install manifest, no shell
            [*command, "run", "--project", root, "--operation", request_path, "--json"],
            stdout=output,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=root,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    _run = {"kind": kind, "process": process, "output": output_path, "root": root, "identity": identity()}
    props.busy, props.status, props.launched = True, f"{kind} running…", props.launched + 1
    bpy.app.timers.register(_poll, first_interval=POLL_S)
    redraw()
    return None


def _poll():
    if _run is None:
        return None
    if _run["process"].poll() is None:
        return POLL_S
    try:
        _collect()
    finally:
        redraw()
    return None


def _collect() -> None:
    """Read the finished engine process and show its outcome."""
    global _run
    run, _run = _run, None
    props = state()
    props.busy, props.last_kind = False, run["kind"]
    try:
        with open(run["output"], encoding="utf-8") as handle:
            result = json.load(handle)
    except (OSError, ValueError):
        props.last_status, props.status = "failed", f"{run['kind']}: no readable result from the engine"
        return
    props.last_status = result.get("status", "failed")
    metrics = result.get("metrics", {})
    props.before_m = metrics.get("contact_before_m", metrics.get("contact_restored_m", -1.0))
    props.after_m = metrics.get("contact_after_m", -1.0)
    reports = [a["path"] for a in result.get("artifacts", []) if a["path"].endswith(".json")]
    props.last_report = reports[0] if reports else ""
    # Whatever happened, the lines of an earlier preview no longer describe these parameters.
    director_overlay.clear()
    if result.get("errors"):
        props.status = f"{run['kind']} refused: {result['errors'][0]['message']}"[:300]
        return
    props.status = f"{run['kind']} done"
    if run["kind"] == "preview" and props.last_report:
        try:
            with open(os.path.join(run["root"], props.last_report), encoding="utf-8") as handle:
                director_overlay.load(json.load(handle).get("viewport"), bpy.data.filepath)
        except (OSError, ValueError):
            pass
    blend = next((a["path"] for a in result.get("artifacts", []) if a.get("kind") == "blend"), None)
    if blend:
        # Identity-guarded: a human edit made meanwhile cancels the reload and is kept.
        outcome = bpy.ops.fluidblend.open_file(
            filepath=os.path.join(run["root"], blend), expected_identity=json.dumps(run["identity"])
        )
        if "FINISHED" in outcome:
            state().status = f"{run['kind']} done, revision {result.get('new_revision')} opened"
        else:
            props.status = f"{run['kind']} published {blend}; session edited meanwhile, reopen it yourself"


def snapshot() -> dict:
    props = state()
    return {
        "busy": props.busy,
        "status": props.status,
        "last_kind": props.last_kind,
        "last_status": props.last_status,
        "last_report": props.last_report,
        "before_m": props.before_m,
        "after_m": props.after_m,
        "launched": props.launched,
        "pending_preview": _pending_at is not None,
        "overlay": director_overlay.summary(),
    }


BUTTON_HELP = {
    "preview": "Measure the slide before and after the fix and draw both paths in the viewport. "
    "Nothing is saved, the open scene is not touched",
    "apply": "Publish a new version of the shot with the fix, then open it. Needs a saved, unmodified scene",
    "revert": "Publish a new version without the fix named above, then open it",
}


def _operator(kind: str):
    class Operator(bpy.types.Operator):
        bl_idname = f"fluidblend.director_{kind}"
        bl_label = kind.capitalize()
        bl_description = BUTTON_HELP[kind]

        def execute(self, context):  # noqa: ANN001
            refusal = launch(kind)
            if refusal:
                state(context).status = refusal
                self.report({"WARNING"}, refusal)
                redraw()
                return {"CANCELLED"}
            return {"FINISHED"}

    Operator.__name__ = f"FLUIDBLEND_OT_director_{kind}"
    return Operator


class FLUIDBLEND_OT_director_status(bpy.types.Operator):
    """Print the panel state (agents and tests read it; the panel shows the same fields)."""

    bl_idname = "fluidblend.director_status"
    bl_label = "fluidblend: Director status"
    bl_options = {"INTERNAL"}

    def execute(self, context):  # noqa: ANN001
        print("FLUIDBLEND_DIRECTOR=" + json.dumps(snapshot()), flush=True)
        return {"FINISHED"}


class FLUIDBLEND_PT_director(bpy.types.Panel):
    bl_label = "Director"
    bl_idname = "FLUIDBLEND_PT_director"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "fluidblend"

    def draw(self, context):  # noqa: ANN001
        props, layout = state(context), self.layout
        layout.label(text="Fix a sliding hand or foot", icon="CON_LOCKTRACK")
        # Say why the panel is useless here instead of showing controls that cannot work.
        if project_root() is None:
            wrapped(layout, "Open a work version of a fluidblend project to use this.", icon="INFO")
            return
        skipped = unsupported_characters()
        if skipped:
            wrapped(
                layout,
                f"Not usable here: {', '.join(skipped)}. This tool drives IK controls of a Rigify "
                "character placed by shot.build; the demo bipeds have none.",
                icon="INFO",
            )
        if not characters():
            return
        if is_stale():
            latest = latest_version()
            version = os.path.basename(os.path.dirname(latest))
            wrapped(
                layout,
                f"This file is not the latest version of the shot ({version}). The engine works on "
                "the latest one: open it to see and adjust the real state.",
                icon="ERROR",
            )
            layout.operator("fluidblend.director_open_latest", icon="FILE_FOLDER")
            return
        if bpy.data.is_dirty:
            # Shown before any click: Apply and Revert would be refused, and saving is a trap.
            wrapped(
                layout,
                "This scene has unsaved changes (a selection is enough). Apply and Revert need a clean "
                "scene. Do not save over this published version.",
                icon="ERROR",
            )
            layout.operator("fluidblend.director_reload", icon="FILE_REFRESH")
        fixes = applied_fixes()
        if fixes:
            wrapped(layout, "Fixes in this scene: " + ", ".join(fixes), icon="CHECKMARK")
        box = layout.box()
        box.label(text="What should stay still")
        # Labels above narrow fields: the sidebar truncates a label sharing the row with its value.
        box.prop(props, "instance_id", text="")
        box.prop(props, "effector", text="")
        box = layout.box()
        box.label(text="During which frames")
        row = box.row(align=True)
        row.prop(props, "frame_start", text="From")
        row.prop(props, "frame_end_exclusive", text="Until")
        box = layout.box()
        box.label(text="Limits")
        box.prop(props, "max_correction_m", slider=True)
        box.prop(props, "blend_frames", slider=True)
        box.prop(props, "auto_preview")
        layout.prop(props, "adjustment_id")
        row = layout.row(align=True)
        # A fix name is either free (Preview, Apply) or already in the scene (Revert): never both.
        exists = props.adjustment_id in fixes
        for kind in ("preview", "apply", "revert"):
            column = row.row(align=True)
            column.enabled = not props.busy and (exists if kind == "revert" else not exists)
            column.operator(f"fluidblend.director_{kind}")
        if exists:
            wrapped(
                layout, f"'{props.adjustment_id}' is applied: Revert removes it, another name adds a new fix."
            )
        wrapped(layout, props.status, icon="ERROR" if "refused" in props.status else "NONE")
        if props.last_status != "succeeded":
            return
        box = layout.box()
        limb = props.effector.replace("_", " ")
        if props.last_kind == "revert":
            wrapped(box, f"Fix removed: the {limb} slides {props.before_m * 1000:.1f} mm again.")
        elif props.before_m >= 0 and props.after_m >= 0:
            wrapped(
                box,
                f"The {limb} slides {props.before_m * 1000:.1f} mm. "
                f"With the fix: {props.after_m * 1000:.1f} mm.",
            )
        if props.last_kind == "preview":
            shown = director_overlay.summary()
            if shown:
                # Drawn over the scene, stored nowhere in it: the character itself does not move.
                wrapped(
                    box,
                    f"In the viewport, frames {shown['first_frame']} to {shown['last_frame']}: red = the {limb} "
                    "today, green = with the fix, white cross = where it should stay. Scrub the timeline: "
                    "the two dots follow.",
                    icon="HIDE_OFF",
                )
                row = box.row(align=True)
                row.operator("fluidblend.director_focus_overlay", icon="VIEWZOOM")
                row.operator("fluidblend.director_hide_overlay", icon="HIDE_ON")
            wrapped(
                box,
                "Nothing changed in this scene yet. Apply publishes a new version with the fix and opens it.",
            )
        if review_folder():
            box.operator("fluidblend.director_open_review", icon="IMAGE_DATA")


def review_folder() -> str | None:
    """Folder of the last report; a preview also puts its before/after frames there."""
    root, report = project_root(), state().last_report
    if not root or not report:
        return None
    folder = os.path.dirname(os.path.join(root, report))
    return folder if os.path.isdir(folder) else None


class FLUIDBLEND_OT_director_open_latest(bpy.types.Operator):
    """Open the latest published work version of this shot. Refused while this scene has unsaved changes"""

    bl_idname = "fluidblend.director_open_latest"
    bl_label = "Open latest version"

    def execute(self, context):  # noqa: ANN001
        latest = latest_version()
        if latest is None:
            return {"CANCELLED"}
        if bpy.data.is_dirty:
            # Never discard work: the artist decides what happens to unsaved edits.
            self.report({"WARNING"}, UNSAVED)
            state(context).status = UNSAVED
            return {"CANCELLED"}
        return bpy.ops.fluidblend.open_file(filepath=latest)


class FLUIDBLEND_OT_director_reload(bpy.types.Operator):
    """Reload this file from disk and DISCARD the unsaved changes of this scene. Asks for confirmation"""

    bl_idname = "fluidblend.director_reload"
    bl_label = "Reload file (discard my changes)"

    def invoke(self, context, event):  # noqa: ANN001
        # Discarding work is the artist's decision, never a side effect of another button.
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):  # noqa: ANN001
        if not bpy.data.filepath:
            return {"CANCELLED"}
        return bpy.ops.fluidblend.open_file(filepath=bpy.data.filepath)


class FLUIDBLEND_OT_director_focus_overlay(bpy.types.Operator):
    """Centre the 3D views on the previewed contact and zoom in. Only the view moves, not the scene"""

    bl_idname = "fluidblend.director_focus_overlay"
    bl_label = "Zoom on the fix"

    def execute(self, context):  # noqa: ANN001
        shown = director_overlay.summary()
        if shown is None:
            return {"CANCELLED"}
        # A 10 cm slide is a few pixels on a whole-shot view: found by a human looking at it.
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    view = area.spaces.active.region_3d
                    if view.view_perspective == "CAMERA":
                        view.view_perspective = "PERSP"
                    view.view_location, view.view_distance = shown["center"], 1.2
                    area.tag_redraw()
        return {"FINISHED"}


class FLUIDBLEND_OT_director_hide_overlay(bpy.types.Operator):
    """Hide the red and green preview paths of the viewport. They never changed the scene"""

    bl_idname = "fluidblend.director_hide_overlay"
    bl_label = "Hide preview paths"

    def execute(self, context):  # noqa: ANN001
        director_overlay.clear()
        redraw()
        return {"FINISHED"}


class FLUIDBLEND_OT_director_open_review(bpy.types.Operator):
    """Open the folder with the report and the before/after images of the last operation"""

    bl_idname = "fluidblend.director_open_review"
    bl_label = "Open report and images"

    def execute(self, context):  # noqa: ANN001
        folder = review_folder()
        if folder is None:
            self.report({"WARNING"}, "no report folder yet")
            return {"CANCELLED"}
        images = os.path.join(folder, "review")
        return bpy.ops.wm.path_open(filepath=images if os.path.isdir(images) else folder)


CLASSES = (
    FluidblendDirectorState,
    _operator("preview"),
    _operator("apply"),
    _operator("revert"),
    FLUIDBLEND_OT_director_status,
    FLUIDBLEND_OT_director_open_latest,
    FLUIDBLEND_OT_director_reload,
    FLUIDBLEND_OT_director_focus_overlay,
    FLUIDBLEND_OT_director_hide_overlay,
    FLUIDBLEND_OT_director_open_review,
    FLUIDBLEND_PT_director,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.fluidblend_director = PointerProperty(type=FluidblendDirectorState)


def unregister() -> None:
    director_overlay.unregister()
    del bpy.types.WindowManager.fluidblend_director
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
