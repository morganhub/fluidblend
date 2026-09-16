# Roadmap

Every item below, apart from "Lot 1", is **not implemented**. The technical decisions already taken
are recorded to prepare the work, not to suggest that it is done.

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

## Lot 2 — Live writing into an open session — **not implemented**

Goal: **write** into an open Blender session. Live reading is proven (A03: `list_tools` then
`get_scene_info`, without mutation, on a GUI session started and stopped by the test); everything
below concerns writing and remains unimplemented.

| Item | Status | Preparatory decision |
| --- | --- | --- |
| MCP add-on installed and approved | **done** | add-on 1.7 (protocol 7, package `mcp-for-blender` 2.0.0, MIT) installed on 16/09 with `uvx --python 3.11 mcp-for-blender install-addon`, on explicit approval |
| Live write adapter | not implemented | the runtime would be installed as a Blender extension (`blender_manifest.toml`, `blender_version_min = "5.2.0"`, pinned hash); the MCP call would be limited to one import plus one call, never a generated script |
| Scene identity check | not implemented | verify `project_id`, the `.blend` path, the revision and the runtime version before any write; the `fluidblend_*` properties already exist |
| Isolated writing | not implemented | a variant or a reversible temporary state, with an explicit revision on approval |
| Acceptance A03 | **passed** | scene inspection through the configured MCP, without mutation; it does not cover writing |
| Blender instance lock | not implemented | one mode per session, with a dedicated lock on top of the project lock |

What already exists and must not be confused with live writing: client configuration generation
(`fluidblend client-config`), detection of the configured servers and of the add-on by `doctor`, and
a read-only MCP probe client, tested against a fake server in unit tests and against the real server
in A03.

**The kit cannot be announced as live-write compatible before the scene identity, instance lock and
isolated writing tests exist.** What is proven today: reading.

## Lot 3 — P1 characters and adjustments — **not implemented**

| Item | Status | Preparatory decision |
| --- | --- | --- |
| Rigify rig profile | not implemented | Rigify 0.6.10 (core add-on of Blender 5.2); semantic mapping to `root`, `torso`, `hips`, `chest`, `head`, `hand_ik.L/R`, `foot_ik.L/R`, `DEF-*` deformers; IK/FK switches on `upper_arm_parent.L` and `thigh_parent.L` |
| Vitruvian fixture | not implemented | reference skinned character (CC0 asset) for test poses and counting uninfluenced vertices |
| Action library | not implemented | `idle_neutral`, `walk`, `turn`, `look_at`, `reach`, `take_prop`, `give_prop`, `react`; one `clip.json` per clip (rig, duration, loop, root motion, contacts) |
| NLA layers | not implemented | `body`, `upper`, `hands`, `gaze`, `face`, `mouth` tracks; documented `COMBINE` or `REPLACE` blending; double-transform test |
| Interactions | not implemented | `interaction.plan/apply/validate`; ownership transfer through `CHILD_OF` preserving the world transform; measurement of the jump and of the contact distance |
| Adjustment tools | not implemented | `retime_segment`, `look_at_target`, `contact_lock` at the very least, each with bounded parameters, a preview, an undo path and tests |
| `Director` Blender panel | not implemented | operators calling the same operations as the CLI; bounded sliders, debounce through `bpy.app.timers` (hence GUI only) |
| Bounded retargeting | not implemented | name-to-name preset in the Expy-Kit format, constraints then `nla.bake(visual_keying=True, clear_constraints=True)`; Retarget and Rokoko stay external (GPL-3 / LGPL-3) |

Target acceptance scenarios: B01, B03, B05, B06, B08.

## Lot 4 — P1 voice and game target — **not implemented**

| Item | Status | Preparatory decision |
| --- | --- | --- |
| Rhubarb lip-sync | not implemented | Rhubarb 1.14.0 (MIT), `-f json -r phonetic`; mapping of cues A–H and X to Actions then to NLA strips |
| Audio preparation | not implemented | FFmpeg, 48 kHz mono WAV, two-pass `loudnorm`, `aresample=48000` systematically; drift tolerated up to one frame at most |
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
| Character | `character.inspect`, `rig.validate`, `rig.map` | P1 |
| Animation | `animation.create`, `animation.apply`, `animation.loop`, `animation.retarget`, `animation.bake` | P1 |
| Interactions | `interaction.plan`, `interaction.apply`, `interaction.validate` | P1 |
| Audio and face | `audio.prepare`, `lipsync.analyze`, `lipsync.apply`, `expression.apply` | P1 |
| Adjustment | `adjustment.preview`, `adjustment.apply`, `adjustment.revert` | P1 |
| Film | `shot.build` | P1 |
| Game | `game.import_test`, `game.smoke_test` | P1 |
| Tools | `tool.inspect`, `tool.test`, `tool.register` | P1 |

What to do when faced with one of these requests: stop, explain that the lot does not implement it,
offer the closest P0 operation if one exists, and simulate nothing.

## Debts and open points of lot 1

- Live writing never exercised: only reading is covered, by A03.
- `game` profile not tested: Godot 4.7.2 is detected by `doctor`, but the kit provides neither a
  template nor an engine import (lot 4).
- Lip-sync not implemented: Rhubarb 1.14.0 is detected, `lipsync.*` answers
  `UNSUPPORTED_CAPABILITY`.
- Acceptance A03 depends on a GUI Blender session: if port 9876 is already in use, it declares
  itself `not_run` instead of running.
- No automatic restore from a checkpoint: resumption is manual and documented.
- `state/metrics.json` is calibrated on renders only; the other estimates use constants.
