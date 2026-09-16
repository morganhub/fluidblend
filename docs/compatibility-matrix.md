# Compatibility matrix

This document distinguishes three levels, and only one counts as a guarantee:

- **proven**: used and measured on the reference machine during lot 1;
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
| mcp (Python SDK) | 1.30 | probe client: fake server in unit tests, real `mcp-for-blender` server in A03 |

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
fired** under `--background`.

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
| Claude Code | `<project>\.claude\skills\fluidblend\SKILL.md` | proven: the skill is copied, the frontmatter is valid; the project-scoped `.mcp.json` is read and probed (A03) |
| Codex | `<project>\.agents\skills\fluidblend\SKILL.md` | proven for the copy; this is the current official path, no longer `~/.codex/skills` |
| VS Code (MCP) | generated `.vscode/mcp.json` | configuration generated, connection not tested |

No global skill is installed, in any client.

## External tools

| Tool | Target version | Status on this machine | Consequence |
| --- | --- | --- | --- |
| FFmpeg / ffprobe | 8.0.1 | **present, proven** | previews assembled, ffprobe proof |
| glTF-Validator | 2.0.0-dev.3.10 win64 | **present, proven** | Khronos validation executed, acceptance A10 passed |
| Godot | 4.7.2 stable | **present, detected** | detected by `doctor` (`_console` variant), **not exercised by the kit**: no template and no engine import (lot 4) |
| Rhubarb Lip Sync | 1.14.0 | **present, detected** | detected by `doctor`, **not exercised by the kit**: `lipsync.*` not implemented (lot 4) |
| MCP for Blender add-on | add-on 1.7, protocol 7 (PyPI package 2.0.0) | **present, proven for reading** | acceptance A03 passed; live writing not implemented (lot 2) |
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

All thirteen scenarios pass on this machine, with the external tools installed. On a machine without
the Khronos validator, without the MCP add-on or without a GUI Blender session, A10 and A03 fall
back to `not_run`: a `not_run` scenario is never counted as passed. The timestamped report is
authoritative. Regenerate it with:

```powershell
uv run pytest tests --acceptance-report docs/acceptance-reports/latest-p0
```

Scenarios B01 to B08 belong to lots 3 and 4: they are not run and must not be presented as partially
passed.

## Component licenses

| Component | License | Integration mode |
| --- | --- | --- |
| fluidblend (this kit) | MIT | code in this repository |
| Blender, Rigify | GPL | external executable, never linked |
| FFmpeg (the build used) | GPL | external executable |
| mcp-for-blender | MIT | external dependency launched by `uvx` |
| glTF-Validator | Apache-2.0 | external executable |
| Godot | MIT | external executable (lot 4) |
| Rhubarb Lip Sync | MIT | external executable (lot 4) |
| Retarget, Expy-Kit | GPL-3 | external add-ons, never integrated (lot 3) |
| CharMorph | GPL-3 | external tool; Vitruvian asset CC0 |
| Quaternius, Poly Haven | CC0 | assets |
| Mixamo | — | **forbidden in the repository** |

Sources and verification dates: `docs/sources.md`.
