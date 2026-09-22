# Game export

Status: `game.export` (P0), `game.import_test` and `game.smoke_test` (P1, Godot 4.7) are implemented.
The kit imports and launches **its own template**; it does not build the user's game.

## `game.export`

Exports the scene instances to GLB, then reimports them into a fresh scene as a check.

```json
{
  "schema_version": "1.0",
  "operation": "game.export",
  "operation_id": "export-shot010-characters-001",
  "project_id": "demo-studio",
  "target": {"shot_id": "shot010"},
  "parameters": {
    "output_name": "shot010-characters",
    "instance_ids": ["hero-01", "sidekick-01"],
    "reimport_check": true,
    "export_def_bones": false,
    "export_influence_nb": 4,
    "animation_mode": "ACTIONS",
    "slide_to_zero": true,
    "include_cameras": false,
    "include_lights": false
  },
  "dry_run": false
}
```

| Parameter | Default | Notes |
| --- | --- | --- |
| `output_name` | mandatory | name of the `.glb`, `[A-Za-z0-9._-]`, 80 characters maximum |
| `instance_ids` | every instance | a requested instance that is missing fails the export |
| `reimport_check` | `true` | control reimport into an empty scene |
| `export_def_bones` | `false` | export only the deform bones (`DEF-*`, useful with Rigify in P1) |
| `export_influence_nb` | 4 | 1 to 8 influences per vertex |
| `animation_mode` | `ACTIONS` | `ACTIONS`, `ACTIVE_ACTIONS`, `NLA_TRACKS`, `SCENE` |
| `slide_to_zero` | `true` | shifts the start of the animations to 0 |
| `include_cameras` | `false` | cameras excluded by default |
| `include_lights` | `false` | lights excluded by default |

Settings applied systematically by the runtime, not configurable: `export_format="GLB"`,
`use_selection=True`, `export_yup=True`, `export_apply=False`, `export_animations=True`,
`export_force_sampling=True`, `export_optimize_animation_size=True`, `export_reset_pose_bones=True`,
`export_skins=True`, `export_extras=True`, `export_frame_range=True`.

`export_force_sampling` is indispensable here: the walk cycles rely on `CYCLES` F-modifiers that
glTF cannot represent. Without sampling, the looped motion would be lost.

`export_extras` carries the `fluidblend_*` properties along, in particular
`fluidblend_instance_id`: that is what makes it possible to find an instance again engine-side.

## Axes

| Target | Up | Forward |
| --- | --- | --- |
| Blender | +Z | -Y |
| glTF | +Y | +Z |

The conversion is done by `export_yup=True` and the convention is written as such in
`export-report.json` (`axis_convention`). Godot uses Y-up / -Z: the difference in forward direction
between glTF and Godot is handled engine-side, not by bending the export.

## Control reimport

With `reimport_check: true`, the runtime opens an empty scene and reimports the GLB
(`bone_heuristic="BLENDER"`), then compares:

| Check | Passes when |
| --- | --- |
| `armature_count` | same number of armatures |
| `bone_counts` | same bone counts (sorted) |
| `mesh_count` | same number of meshes |
| `animations_present` | at least as many animations as exported Actions |

A failing check fails the operation, after the report has been written for diagnosis. A Blender
reimport alone **is not enough** to declare the export acceptance test passed.

## Khronos validation

If `gltf_validator` is found (`config/local.json`, `PATH`, the user tools directory or a known
installer — see `docs/installation.md` §3 bis), the engine runs
`gltf_validator -r -a -o <file>.glb`, records the JSON report and fails if blocking errors remain.
`ACCESSOR_JOINTS_USED_ZERO_WEIGHT` is ignored by default.

**Validator 2.0.0-dev.3.10 is present on the reference workstation**: acceptance scenario A10 passes,
0 error and 0 warning on `shot010-characters.glb`, with a consistent Blender reimport. On a
workstation without the validator, the `khronos_validation` metric is `not_run`, a warning is emitted
and A10 becomes partial again. Never present an export as glTF-compliant without that report.

## Published artifacts

In `exports/<shot>/<operation_id>/`: `<output_name>.glb`, `export-report.json` (full settings, axis
convention, exported content, per-instance facts and reference pose, reimport report),
`gltf-validator.json` if the validator ran, `handoff-bundle.json` and the `licenses/` it carries.
Metrics: `glb_bytes`, `armatures`, `actions`, `reimport_passed`, `khronos_validation`, `bundle`
(false when no licence could be established, with the reason in `warnings`), `bundle_instances`,
`bundle_clips`.

## Limits to state with every export

- P0 characters **are not skinned**: the boxes are parented to the bones. The GLB therefore contains
  animated nodes, not a mesh deformed by a skeleton. `export_skins` is enabled, but there is no
  weight to export.
- The GLB carries **neither constraints nor drivers**. The runtime emits that warning
  systematically.
- A GLB that exports and reimports is not a game, nor even an asset validated in an engine.

## Godot: `game.import_test` then `game.smoke_test`

Examples: [request-game-import-test.json](../assets/request-game-import-test.json),
[request-game-smoke-test.json](../assets/request-game-smoke-test.json). Both need Godot
(`fluidblend doctor`, capability `game.godot`); without it they answer `MISSING_DEPENDENCY` and the
game target is **not_tested** — say exactly that, never "probably fine".

1. `game.export` with `instance_ids: ["<one character>"]`: one character per GLB for the template.
2. `game.import_test` (`export_path` = the published `.glb`, target `shot_id`): copies
   `templates/game-godot/` and the GLB (`assets/character.glb`), runs
   `godot --headless --path <game> --import`, and checks **what the engine wrote**, not only its
   exit code: `character.glb.import` says `importer="scene"` and an imported scene exists. It
   publishes the `game/` folder without the machine-local `.godot` cache, and `game-import.json`.
3. `game.smoke_test` (`game_dir` = that published `game` folder): re-imports a private copy and runs
   `res://test/smoke.gd` headless. The prototype plays the real main scene through the same input
   path as the keyboard: 13 checks — scene loads, character instantiated, `AnimationPlayer` and a
   walk clip found, stands on the floor, `idle` plays nothing, `walk` plays the looping clip, the
   character moves, the wall stops it, back to `idle`, reaches the pickup, holds the prop, the pickup
   is empty. Exit 0 **and** a report with every check passed, or the operation fails
   (`VALIDATION_FAILED`, `failed_checks`). No report = the run proves nothing.

Template facts: `CharacterBody3D`, two states (`idle`, `walk`), first animation whose name contains
"walk", made to loop in Godot because glTF carries no loop flag; one wall, one `Area3D` pickup;
original GDScript, no add-on. The smoke test is plain GDScript: **GUT is not used** (it was the
preparatory choice, dropped to avoid a new dependency).

Limits to state: it is the kit's test bed, not the user's game; headless, so no rendering, frame-rate
or GPU figure is claimed (`wall_time_ms` and the machine are recorded, nothing more); one character,
one clip; Godot 4.7 only (the browser target is below). Both a P0 biped and a skinned Rigify character
have been exercised. The Rigify path is `animation.bake` with `rigid_limbs` (see animation.md), then
`game.export` with `export_def_bones` (188 deform bones instead of 1063). On a baked skeleton the
export carries that one clip and the re-import is replayed: `reimport.skeleton_fidelity` compares
every deform bone head by name at five frames and must stay within 1 mm (measured: 0.003 mm over
940 comparisons). It measures the skeleton in Blender's importer, not the skinned surface in Godot.
Asked for a real playable game: say the kit proves the character arrives and animates in the engine,
and stop there.

## Browser: the same two operations with `"template": "web"`

"Show me the character in the browser", "a web preview", "does it work in Three.js". Example:
[request-game-import-test-web.json](../assets/request-game-import-test-web.json); the smoke request
is the same as for Godot: `game.smoke_test` recognises the folder. Needs Edge or Chrome
(`fluidblend doctor`, capability `game.browser`; Edge ships with Windows); without one:
`MISSING_DEPENDENCY`, web target **not_tested**. Nothing is downloaded: Three.js r186 (MIT) is
vendored in the template and pinned by hash.

**Use it as your eyes, whatever the target engine.** The Godot run is headless: it proves the logic
and draws nothing, so you cannot see the character there. The browser run draws. When the target is
Godot, run the web template on the **same GLB** as well, open `web-frame.png`, and report what you
saw next to the Godot checks. It shows what the GLB contains (skin, pose, orientation, scale), not
how Godot shades it: say so.

1. `game.export` as above (Rigify: `animation.bake` with `rigid_limbs`, then `export_def_bones`).
2. `game.import_test` with `template: "web"` (or no `template` in a project whose
   `targets.game_engine` is `web`): copies `templates/game-web/` and the GLB, serves the
   folder on `127.0.0.1` (ephemeral port, for the run only — a browser refuses a GLB over `file://`),
   opens it in a **headless, offline** browser and reads what Three.js loaded: `engine`, `clips`,
   `walk_clip`, `skinned_meshes`. Publishes the `game/` folder and `game-import.json`.
3. `game.smoke_test` (`game_dir` = that folder): 14 checks through real keyboard events and fixed
   1/60 s steps — the 13 of Godot plus `walk_clip_moves_bones` (a clip can "run" and move nothing).
   Then the browser **renders**: `web-frame.png` (one deterministic mid-stride frame) and
   `rendered_share`, the share of the frame the character covers, read back from the GPU (must be
   ≥ 1 %). This is the only evidence the kit has of the skin drawn by a game engine: **open
   `web-frame.png` and say you looked at it** before saying the character looks right.
4. For the user to play it: `fluidblend preview web --project . --game-dir <published game folder>`
   (serves on 127.0.0.1, opens the default browser, Ctrl+C stops). Arrows move, Space picks up.

Reported, never hidden: `root_motion_removed_m` (the baked clip's horizontal travel is removed so
the loop does not snap back — the body moves instead; 0.6 m on the walk fixture), `recentered_m`
(a character exported from its place in a shot is put back under the body), and the model is turned
so that the clip's travel direction is its forward. `webgl: false` means nothing was rendered: the
checks still ran, the skin is **not** verified, and the report says so.

Refusals: engine files that differ from the pinned hashes (`VALIDATION_FAILED` "pinned hashes"), a
page that writes no report, a prototype that fails a check (`failed_checks`). Limits to state: the
kit's test bed, not the user's game; one frame, no frame-rate or GPU figure; one character, one
clip; Chromium browsers only; artistic review pending.
## Unreal: hand over to fluidunreal

This kit does **not** import into Unreal Engine, does not read its skeleton, does not play its
prototype and never says a character works in Unreal. It exports a bundle and hands it over. The
sibling kit `fluidunreal` imports it, audits what the engine really wrote, runs its own test bed and
publishes its own evidence.

Export with the preset: [request-game-export-unreal.json](../assets/request-game-export-unreal.json).
`export_preset: "unreal"` **validates, it never repairs**: `animation_mode` other than `ACTIONS` or
`slide_to_zero: false` is refused at the request (exit 4); a Rigify character without
`export_def_bones: true` is refused by the runtime before anything is written; an unbaked character
is a warning, not a refusal, and the bundle reports `baked: false`. An instance whose asset manifest
has no readable `license_path` stops the task (`PERMISSION_REQUIRED`, exit 2): a bundle is a
redistribution format and never travels without the licence of what it carries.

`handoff-bundle.json` is published beside the GLB on **every** successful `game.export`, not only
with the preset. It contains: the producer (kit, version, operation_id, project, shot, source
revision), `fps`, the axis convention, every file with its sha256 (model, export report, Khronos
report when it ran, the licences, copied in), `validation` (`khronos: passed | failed | not_run`,
`reimport_passed`, `skeleton_fidelity_max_error_m`), the instances (asset id and version, licence,
rig profile, skinned, baked, bone count, glTF node name, grips, and a **reference pose**: two to five
deform bone heads at rest in metres) and the clips (glTF animation name, `frame_range` as the GLB
has it, from 0, `source_frame_range` as Blender has it, loop, root motion, stride, repetitions). A
request sent back to this kit about a clip, an `animation.bake` for instance, names the
`source_frame_range`.

`schema_version` is `1.1`. A minor version only adds optional fields: a reader reads any 1.x,
strictly up to its own minor, and drops the fields of a newer one with a note in `warnings`. A
new major is refused.

The reference pose is the point of the bundle: it lets the engine-side kit **measure** the scale and
the up axis it really got instead of assuming a conversion factor. Unmatched animations, an
unconfirmed node name or a skipped re-import become `warnings[]` and `limits[]` rather than silence.

Next step, to say to the user and to the agent: hand the published `handoff-bundle.json` to the
`fluidunreal` skill. Over there it is a typed request, not a CLI flag: `bundle.accept` with
`parameters.source_path` set to the **absolute** path of the published export folder (the result's
`next_safe_actions` prints it), run as `fluidunreal run --project <the fluidunreal project>
--operation <that request>`; then `asset.import`, `asset.audit`, `game.smoke_test`,
`game.screenshot`. The two kits keep separate project roots, each with its own `project.json`.

On a project whose `targets.game_engine` is `unreal`, `game.import_test` without an explicit
`template` is refused (`VALIDATION_FAILED`) and points at the fluidunreal kit. With
`template: "web"` the browser eyes stay available on the same GLB, and they remain the only visual
evidence this kit can produce.
