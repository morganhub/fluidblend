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
convention, exported content, reimport report) and `gltf-validator.json` if the validator ran.
Metrics: `glb_bytes`, `armatures`, `actions`, `reimport_passed`, `khronos_validation`.

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
one clip; a P0 biped export has been exercised, a Rigify character must first go through
`animation.bake` and has not been tried in Godot; Godot 4.7 only; no web (Three.js) variant.
Asked for a real playable game: say the kit proves the character arrives and animates in the engine,
and stop there.