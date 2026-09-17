# Roadmap

Lots 1 and 2 are released. Lots 3 and 4 are partially implemented in the working tree;
[production-p1.md](production-p1.md) records exact scope and evidence. Planned features are not
claims of completion.

No unimplemented operation is simulated: it answers `UNSUPPORTED_CAPABILITY` (exit 2) and points
here. Check what is actually available at any time:

```powershell
fluidblend ops --all --json
```

## Lot 0 — Diagnostic and decisions — done

Inventory of the machine, observed capabilities, versions chosen, risks, licenses and a minimal
installation plan: the public synthesis is in `docs/sources.md` (projects studied, licenses); the
diagnostic of the reference machine is summarised in `docs/compatibility-matrix.md`.

## Lot 1 — P0 headless foundation — **done (version 0.1.0)**

Contracts, scaffold, CLI, batch runner, Blender runtime, journal, checkpoints, revisions, locks,
path protection, budgets, and the 19 P0 operations. Acceptance A01 to A13 run and **passed** on this
machine, with external tools installed on approval (Khronos validator, MCP add-on). Details in
`docs/compatibility-matrix.md` and in `docs/acceptance-reports/latest-p0.md`.

## Lot 2 — Live writing into an open session — **done (version 0.2.0)**

`fluidblend run --mode live` runs four operations in the Blender session the user has open:
`scene.inspect`, `scene.audit`, `animation.retime`, `scene.checkpoint`. Anything else keeps the
batch path, on the published work version. Acceptance L01 to L05 passed on the reference machine;
details in `docs/compatibility-matrix.md` and `docs/acceptance-reports/latest-p0.md`.

| Item | Status | What was built |
| --- | --- | --- |
| MCP add-on installed and approved | **done** | add-on 1.7 (protocol 7, package `mcp-for-blender` 2.0.0, MIT), installed on explicit approval |
| Live write adapter | **done** | `adapters/blender_live.py`: one `uvx mcp-for-blender` stdio server per phase; the call is limited to `import bpy` plus one approved operator, never a generated script |
| Approved runtime in the session | **done** | installed as a Blender **add-on** rather than an extension (`fluidblend runtime install --enable`, hash + `RUNTIME_MANIFEST.json`, capability `blender.runtime_addon`); the MCP safe mode forbids `register_class`, so operators registered by an enabled add-on are the only way in — safe mode stays on |
| Scene identity check | **done** | `project_id`, open file against the shot's latest work version, revision, runtime version and `is_dirty` verified before anything runs; mismatch → `SCENE_CONFLICT` (exit 3), journal event `live_identity_checked` (L01, L03, L04) |
| Isolated writing | **done** | live `animation.retime` saves with `copy=True`, the engine publishes the next version, records the revision, then reloads the session on the published file (`live_session_reloaded`); the version on disk is untouched (L02) |
| Blender instance lock | **done** | live tasks hold `blender-instance` on top of the project lock; task records carry `mode: batch\|live` |
| Uncertain live state | **done** | a call past `mcp.call_timeout_s` leaves the task `unknown` (exit 5), retries refused until `task reconcile` (L05) |

Remaining live items, **not implemented**:

| Item | Status | Note |
| --- | --- | --- |
| Writes through the client's own MCP connection | not implemented | the AI client's direct connection stays read-only guidance (`get_scene_info`, `get_viewport_screenshot`, `get_object_info`); every write goes through `fluidblend run --mode live`, never an improvised `execute_blender_code` |
| Undo / edit signal from the session | implemented | process-local monotonic generation, depsgraph/undo/redo/load signals; guarded admission, publication and reload |
| Live mode for the other operations | not implemented | `scene.build`, `shot.preview` and `game.export` need a dedicated process and are refused in a live envelope with `UNSUPPORTED_CAPABILITY` |
| Progress feedback and cancellation during a live call | implemented (L09) | cooperative timer steps, `progress.json`, `task cancel` believed only on `cancel.ack.json`; the four live operations are single-step today, so a stop lands before or after them, not inside |

## Lot 3 — P1 characters and adjustments — **partial**

| Item | Status | Preparatory decision |
| --- | --- | --- |
| Rigify rig profile | implemented | Rigify 0.6.10 (core add-on of Blender 5.2); semantic mapping to `root`, `torso`, `hips`, `chest`, `head`, `hand_ik.L/R`, `foot_ik.L/R`, `DEF-*` deformers; IK/FK switches on `upper_arm_parent.L` and `thigh_parent.L` |
| Vitruvian fixture | implemented | reference skinned character (CC0 asset) for test poses and counting uninfluenced vertices |
| Action library | implemented: eight bounded recipes | `idle_neutral`, `walk`, `turn`, `look_at`, `reach`, `take_prop`, `give_prop`, `react`; one `clip.json` per clip (rig, duration, loop, root motion, contacts); `walk` and `take_prop` carry measured contacts |
| Contact and loop measurements | implemented | shared module; each figure states space, window, sampling, control point and tolerance; world-space feet, loop seams, palm/grip contact in the prop's space, hand-off jump |
| NLA layers | partial: disjoint REPLACE | `body`, `upper`, `hands`, `gaze`, `face`, `mouth` tracks; documented `COMBINE` or `REPLACE` blending; double-transform test |
| Interactions | bounded prop hand-off implemented (B03); other kinds not implemented | `interaction.plan/apply/validate`; ownership transfer through `CHILD_OF` preserving the world transform; measurement of the jump and of the contact distance |
| Adjustment tools | `contact_lock` implemented with preview/apply/revert (B05); the others not implemented | `retime_segment`, `look_at_target`, `contact_lock` at the very least, each with bounded parameters, a preview, an undo path and tests |
| Custom tools | declarative registry implemented (B08) | `tools/custom/<id>/tool.json` narrows a built-in tool and carries its tests; `tool.inspect/test/register`; no code is loaded |
| `Director` Blender panel | implemented for `contact_lock` (B06); clicked by a human on 17 September 2026, which exposed and fixed an empty character field, truncated messages, a sidebar that did not refresh, a stale-version trap and an unsaved-scene trap; the preview shows figures and frames, not motion in the viewport | operators calling the same operations as the CLI; bounded sliders, debounce through `bpy.app.timers` (hence GUI only) |
| Bounded retargeting | not implemented | name-to-name preset in the Expy-Kit format, constraints then `nla.bake(visual_keying=True, clear_constraints=True)`; Retarget and Rokoko stay external (GPL-3 / LGPL-3) |

Target acceptance scenarios: B01, B03, B05, B06 and B08 — all passed.

## Lot 4 — P1 voice and game target — **partial**

| Item | Status | Preparatory decision |
| --- | --- | --- |
| Rhubarb lip-sync | analysis and application on shape keys (B04) | Rhubarb 1.14.0 (MIT), `-f json -r phonetic`; mapping of cues A–H and X to Actions then to NLA strips |
| Audio preparation | implemented | FFmpeg, 48 kHz mono WAV, two-pass `loudnorm`, `aresample=48000` systematically; drift tolerated up to one frame at most |
| Godot template | not implemented | Godot 4.7.2 (MIT), `CharacterBody3D`, `AnimationTree` with an `idle` ↔ `walk` state machine, based on the Jeh3no controller (MIT) |
| GUT tests | not implemented | GUT 9.7.1 in headless mode; check that the `.import` files exist, not only the return code |
| `game.import_test`, `game.smoke_test` | not implemented | a real import then a prototype actually launched, not merely file generation |
| Web variant | not implemented | Three.js r186, `GLTFLoader`, `AnimationMixer.crossFadeTo`, `let` only, no jQuery |

Target acceptance scenarios: B02, B04, B07. Godot 4.7.2 and Rhubarb 1.14.0 are present on the
machine and detected by `doctor`, but no kit operation calls them: nothing is tested.

## Lot 5 — P2 extensions — **not implemented, on demand**

Nothing is planned until a real production asks for it. Identified candidates: a multi-shot render
queue, simulation caches versioned by input hash, background characters, OTIO export, a
domain-level MCP facade, additional retargeters, local mocap, a web interface.

Deliberate exclusions: no distributed framework, no Kubernetes, no multi-agent orchestration imposed
on an individual project.

## Operations not available in this lot

| Domain | Operations | Lot |
| --- | --- | --- |
| Animation | `animation.retarget` | P1 |
| Game | `game.import_test`, `game.smoke_test` | P1 |

What to do when faced with one of these requests: stop, explain that the lot does not implement it,
offer the closest P0 operation if one exists, and simulate nothing.

## Debts and open points of lots 1 and 2

- Live mode covers four operations only, on Windows with Blender 5.2 and the MCP add-on 1.7. It has
  been exercised on the reference machine only, always on a session created by the test.
- The kit's runtime add-on persists in the user's Blender profile once installed; there is no
  `runtime uninstall` subcommand, removal is done by deleting the folder.
- A live call reports nothing until it returns, and the session is left to the user if the reload
  after a live write fails (a warning says so explicitly).
- `game` profile not tested: Godot 4.7.2 is detected by `doctor`, but the kit provides neither a
  template nor an engine import (lot 4).
- Rhubarb analysis is exercised; face application remains unavailable.
- Acceptance A03 and L01 to L05 depend on a GUI Blender session: if port 9876 is already in use,
  they declare themselves `not_run` instead of running.
- No automatic restore from a checkpoint: resumption is manual and documented.
- `state/metrics.json` is calibrated on renders only; the other estimates use constants.
