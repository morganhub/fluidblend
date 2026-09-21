# Compatibility matrix

This document distinguishes three levels, and only one counts as a guarantee:

- **proven**: used and measured on the reference machine during lots 1 and 2;
- **not tested**: plausible, never run here; no promise;
- **excluded**: known to be incompatible, or deliberately out of scope.

Reference machine, measured on 16 September 2026: Windows 11 Pro 10.0.26200, i7-9700K, 32 GiB,
GeForce GTX 1080 Ti.

## Proven foundation

| Component | Proven version | Proof |
| --- | --- | --- |
| Windows | 11 Pro 10.0.26200 | unit and acceptance tests executed |
| PowerShell | 7.6.6 | `bootstrap.ps1`, `install-skill.ps1` scripts, wrapper |
| Blender | **5.2.2 LTS** (Python 3.13.13) | `doctor` probes, acceptance A03 to A11 |
| Python (engine) | 3.13 | `uv sync --python 3.13` virtual environment |
| uv | 0.9.25 | `uv sync`, `uv run` |
| FFmpeg / ffprobe | 8.0.1 | preview assembly and proof (A09) |
| pydantic | 2.12+ | contracts and schema export |
| filelock | 3.20+ | project lock |
| mcp (Python SDK) | 1.30 | probe client: fake server in unit tests, real `mcp-for-blender` server in A03; live client (stdio) in L01–L09 |
| fluidblend runtime add-on | 0.6.2 (`bl_info` 0, 6, 2) | installed in the Blender 5.2 user add-ons directory and enabled headlessly; operators `fluidblend.identity`, `start_request`, `open_file` exercised by L01–L09, Director operators by B06 |

## Blender

| Version | Status | Reason |
| --- | --- | --- |
| 5.2.x | **proven** | locked series; the runtime refuses any other |
| 5.0, 5.1 | not tested | the slotted API is present, but not verified here |
| 5.3+ | not tested | to be re-validated before any use |
| 4.2 LTS and earlier | **excluded** | `Action.fcurves` removed in 5.0; the runtime is written for the slotted API only |

Points verified on 5.2.2: headless start-up with a script in 3.2 s; `Action.fcurves` absent
(`AttributeError`); `slots.new` / `layers.new` / `strips.new(type='KEYFRAME')` /
`strip.channelbag(slot, ensure=True)` creation working; `animation_data.action_slot` assignable;
`bpy.ops.export_scene.gltf` available with `export_animation_mode` accepting `ACTIONS`,
`ACTIVE_ACTIONS`, `BROADCAST`, `NLA_TRACKS`, `SCENE`; `bpy.app.timers` registered but **never
fired** under `--background` (they do fire in the GUI session: live jobs and the Director panel
rely on them, batch never does).

Core add-ons available without installation on 5.2: `rigify` 0.6.10, `io_scene_gltf2` 5.2.40,
`io_anim_bvh`, `io_scene_fbx`, `pose_library`, `cycles`. Only `io_scene_gltf2` is used in P0.

## Measured performance

| Measurement | Value | Conditions |
| --- | --- | --- |
| Workbench render, lot 0 probe | about 0.17 s/frame | 640×360, minimal scene |
| Workbench render, demo scene | about 0.045 s/frame (240 frames in ≈10.8 s) | 640×360, latest A09 acceptance report |
| EEVEE render, lot 0 probe | about 2 s/frame | 640×360, shader compilation included |
| Blender worker start-up | about 3 to 4 s | taken into account in the estimates |

The planner's fallback constants are deliberately pessimistic: 0.2 s/frame in Workbench,
2.5 s/frame in EEVEE, 0.25 MiB/frame, 4 s of start-up. From the very first render,
`state/metrics.json` recalibrates them with a moving average over the project's last eight renders.

Do not quote these figures as guarantees: they depend on the scene, the engine and the machine. The
current value is read from the latest published `render-report.json` and from `state/metrics.json`.
No "pixel-identical" render is promised from one machine to another.

## Operating systems

| System | Status | Detail |
| --- | --- | --- |
| Windows 11 | **proven** | the lot's only target |
| Windows 10 | not tested | discovering Blender through the registry should work |
| Linux, macOS | not tested | the discovery code, `taskkill` and the PowerShell scripts are written for Windows; reading a process command line has a POSIX branch, but it is not exercised |

## AI clients

| Client | Skill location | Status |
| --- | --- | --- |
| Claude Code | `<project>\.claude\skills\fluidblend\SKILL.md` | proven: the skill is copied, the frontmatter is valid; the project-scoped `.mcp.json` is read and probed (A03) and used as the live transport (L01–L05) |
| Codex | `<project>\.agents\skills\fluidblend\SKILL.md` | proven for the copy; this is the current official path, no longer `~/.codex/skills` |
| VS Code (MCP) | generated `.vscode/mcp.json` | configuration generated, connection not tested |

No global skill is installed, in any client.

## External tools

| Tool | Target version | Status on this machine | Consequence |
| --- | --- | --- | --- |
| FFmpeg / ffprobe | 8.0.1 | **present, proven** | previews assembled, ffprobe proof |
| glTF-Validator | 2.0.0-dev.3.10 win64 | **present, proven** | Khronos validation executed, acceptance A10 passed |
| Edge / Chrome (Chromium) | as installed, not pinned (self-updating) | **present, proven headless** | web template of `game.import_test` / `game.smoke_test` (B09): WebGL context obtained, frame read back; Firefox and Safari not supported |
| Godot | 4.7.2 stable | **present, proven headless** | `game.import_test` and `game.smoke_test` (B07) on the kit's template; no rendering or performance figure |
| Rhubarb Lip Sync | 1.14.0 | **analysis tested** | real phonetic analysis; face application remains unavailable |
| MCP for Blender add-on | add-on 1.7, protocol 7 (PyPI package 2.0.0) | **present, proven for reading and for the four live operations** | A03 (read-only probe) and L01–L05 (live mode) passed; safe mode left on, the engine only calls the runtime's operators |
| Node.js | 22.17.0 | present | not used by the kit in P0 |

## P0 acceptance

| Scenario | Status | Note |
| --- | --- | --- |
| A01 initialisation in a path with spaces and accents | passed | |
| A02 re-running the initialisation | passed | no overwrite, conflicts reported |
| A03 scene inspection through MCP | passed | ephemeral GUI Blender session created and stopped by the test; 31 tools advertised, `get_scene_info` read without mutation; port 9876 busy → explicit `not_run` |
| A04 two articulated characters and a prop | passed | 240 frames at 24 fps, file reopened |
| A05 re-run after a lost response | passed | idempotent re-read, conflict if parameters differ |
| A06 worker interrupted before commit | passed | `unknown` → `reconcile` → re-run, single version |
| A07 manual modification of a source | passed | conflict detected, modification preserved |
| A08 slowing an animation down on a variant | passed | 48 → 57.6 frames, source untouched |
| A09 render then preview assembly | passed | 240/240 frames, 24/1 `yuv420p` MP4, ffprobe proof |
| A10 GLB export | passed | Khronos 2.0.0-dev.3.10: 0 errors, 0 warnings on `shot010-characters.glb`; consistent Blender re-import |
| A11 execution without network | passed | worker launched with `--offline-mode` |
| A12 escaping path or command in a parameter | passed | documented refusal, no effect outside the scope |
| A13 exhausted budget or unavailable permission | passed | controlled stop, resumable state |

## Live mode acceptance

Lot 2, `--mode live`. Each scenario installs the runtime add-on if needed, opens its **own** Blender
GUI session on the shot's work version, drives it through MCP and stops that single process. Port
9876 must be free, otherwise the scenario declares itself `not_run`.

| Scenario | Status | Note |
| --- | --- | --- |
| L01 identity check and read-only inspection of the open scene | passed | runtime version, project, open file and clean state verified through `bpy.ops.fluidblend.identity`; `scene.inspect` executed in the GUI session, report published, task recorded with `mode: live` |
| L02 isolated write: retime publishes a new version and reloads the session | passed | new work version published, revision incremented, session reloaded on it, sha256 of the previous version unchanged |
| L03 unsaved manual changes block the write and are preserved | passed | dirty session → `SCENE_CONFLICT` (exit 3), nothing published, the manual change is still there afterwards; `scene.checkpoint` snapshots the unsaved scene (`copy=True`, `was_dirty` metric) |
| L04 an unrelated file open in the session is refused | passed | session on an unsaved default scene → identity mismatch → `SCENE_CONFLICT`, nothing executed in Blender |
| L05 lost response leaves an `unknown` state that reconciliation resolves | passed | call timeout → task `unknown` (exit 5), retry refused, `task reconcile` → `failed`, then the same request succeeds on the clean session |

The batch scenarios A01–A13 and the live scenarios L01–L05 pass on this machine, with the external
tools installed. On a machine without the Khronos validator, without the MCP add-on, without `uvx`
or without a free port 9876, A10, A03 and L01–L05 fall back to `not_run`: a `not_run` scenario is
never counted as passed. The timestamped report is authoritative. Regenerate it with:

```powershell
uv run pytest tests --acceptance-report docs/acceptance-reports/latest-p0
```

Later live scenarios, same conditions: L06–L08 (concurrent human edits preserved at admission,
publication and reload) and L09 (cooperative execution, cancellation acknowledged by the session).

Production scenarios on the actual skinned Vitruvian/Rigify fixture, Blender 5.2.2 LTS:

| Scenario | Status | Note |
| --- | --- | --- |
| B01 versioned skinned character, semantic mapping, five poses | passed | |
| B02 bounded retargeting | passed (after 0.3.0) | one preset, P0 biped walk → Rigify FK controls; limb direction error ≈ 0° on the deform chain, source Action unchanged, feet not re-planted |
| B03 prop hand-off between two characters | passed | contacts in the prop's space, jump, single authority |
| B04 lip-sync applied to a face | passed (after 0.3.0) | offline Windows voice → `audio.prepare` → Rhubarb → shape keys of the `vitruvian-face` fixture; held cues only are checked |
| B05 sliding stance fixed with `contact_lock` | passed | preview, apply, revert |
| B06 Director panel | passed | driven through its operators in a real GUI session; layout not reviewed by a human |
| B09 web import and smoke test | passed (0.5.0) | Three.js r186 in headless Chrome and Edge, offline on 127.0.0.1: GLB loaded, 14 checks through keyboard events, one frame rendered and read back; P0 biped and skinned Rigify character |
| B07 Godot import and smoke test | passed (after 0.3.0) | Godot 4.7.2 headless: `.import` and imported scene checked, prototype launched, 13 checks; GDScript smoke test, GUT not used |
| B08 custom tool: bounded and tested, or stated limitation | passed | declarative tools, no code loaded |

The authoritative, timestamped list is
[acceptance-reports/implementation.md](acceptance-reports/implementation.md); scope and measured
figures are in [production-p1.md](production-p1.md). None of these is an artistic validation.

## Additional live regression

L06 (edit after admission), L07 (edit before publication), L08 (guarded reload and monotonic
undo generation) pass on the same Windows / Blender 5.2.2 machine. See
[the combined report](acceptance-reports/implementation.md). No additional live operation is
qualified by these concurrency checks.

## Component licenses

| Component | License | Integration mode |
| --- | --- | --- |
| fluidblend (this kit) | MIT | code in this repository |
| Blender, Rigify | GPL | external executable, never linked |
| FFmpeg (the build used) | GPL | external executable |
| mcp-for-blender | MIT | external dependency launched by `uvx` |
| glTF-Validator | Apache-2.0 | external executable |
| Godot | MIT | external executable (lot 4) |
| Three.js r186 | MIT | six files vendored in `templates/game-web/vendor/three`, pinned by hash (`licenses/three.md`) |
| Rhubarb Lip Sync | MIT | external executable (lot 4) |
| Retarget, Expy-Kit | GPL-3 | external add-ons, never integrated (lot 3) |
| CharMorph | GPL-3 | external tool; Vitruvian asset CC0 |
| Quaternius, Poly Haven | CC0 | assets |
| Mixamo | — | **forbidden in the repository** |

Sources and verification dates: `docs/sources.md`.
