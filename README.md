# fluidblend

**AI-driven Blender production, with proof.** A lightweight skill for Claude Code / Codex, a Python
engine (`fluidblend`) and a runtime executed inside Blender 5.2 LTS: create, animate, inspect, fix
and deliver scenes for music videos, short films and game prototypes — reproducibly, idempotently
and resumably. Every operation is validated, journaled, versioned and verified (ffprobe, Khronos
glTF validator, re-import). Windows 11 only for now.

Status: **0.2.0 + unreleased partial P1**. The batch scenarios (A01–A13) and the live ones (L01–L05) pass
on the reference machine, see
[docs/acceptance-reports/implementation.md](docs/acceptance-reports/implementation.md). What the kit does not
do yet is listed below and in [docs/roadmap.md](docs/roadmap.md) — nothing is simulated.

## What the kit does today

- **Structured production project** (`fluidblend init`): JSON manifests, permissions, budgets, shot
  plans, append-only journal, checkpoints, work versions. Re-runnable without overwriting anything.
- **Demo scene** (`scene.build`): two original articulated characters, a prop, a camera, a set and a
  240-frame walk cycle at 24 fps — Blender 5.x slotted Actions.
- **Inspection and audit** (`scene.inspect`, `scene.audit`): readable JSON, technical checks.
- **Versioned characters**: local `shot.build`, `character.inspect`, `rig.map`, `rig.validate`,
  with a licensed, skinned Vitruvian/Rigify fixture and five measured pose tests.
- **Bounded animation library**: create, apply in NLA, loop and bake; five initial recipes,
  channel collision checks, deterministic seeds and measured bake deformation error.
- **Audio preparation and analysis**: real two-pass FFmpeg normalization to 48 kHz and Rhubarb
  mouth cues. Facial animation is not yet implemented.
- **Retime on a variant** (`animation.retime`): the source stays untouched, before/after images,
  contact markers preserved, measured duration.
- **Video preview** (`shot.preview`): idempotent PNG sequence then an H.264 MP4 assembled by FFmpeg,
  with `ffprobe` proof (frame count, frame rate).
- **GLB export** (`game.export`): explicit settings (Y-up, sampled animations), control re-import
  into Blender, Khronos validation when the validator is installed.
- **Live mode** (`fluidblend run --mode live`): four operations — `scene.inspect`, `scene.audit`,
  `animation.retime`, `scene.checkpoint` — run inside the Blender session you have open, through the
  MCP add-on and an approved runtime add-on. Each one starts with an identity check (project, open
  file, revision, runtime version, no unsaved change) and refuses rather than overwrite. A live
  write is saved as a copy, published as the next work version, then the session is reloaded on that
  file: the version already on disk is never touched. Every other operation stays in batch.
- **Reliability**: same `operation_id` → same result (never a duplicate); a source edited by hand →
  conflict detected and preserved; interrupted worker → `unknown` state then reconciliation;
  permissions, budgets and out-of-scope paths → controlled stop with a documented exit code.
- **Graftable skill**, into any project, for Claude Code (`.claude/skills/`) and Codex
  (`.agents/skills/`), with no global installation.

## What the kit does not do yet

Retargeting, multi-character interactions, facial cue application, adjustment tools, Blender panel,
Godot / Three.js prototype, Rigify walk and prop recipes. The corresponding operations
exist in the catalogue with `available: false` and answer `UNSUPPORTED_CAPABILITY`: the skill
refuses, it does not improvise. Live mode covers four operations only — any other request runs in
batch, on the published work version.

See [the implementation status](docs/production-p1.md) for tested scope and outstanding work.

## Prerequisites

| Component | Version | Role |
| --- | --- | --- |
| Windows 11, PowerShell 7 | — | the supported platform (paths with spaces and accents are accepted) |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.9 | the kit's isolated Python 3.13 environment |
| [Blender](https://www.blender.org/download/lts/) | **5.2.x LTS** | locked; any other series is refused |
| [FFmpeg](https://ffmpeg.org/) (`winget install Gyan.FFmpeg`) | ≥ 7 | video assembly and `ffprobe` proofs |
| [glTF-Validator](https://github.com/KhronosGroup/glTF-Validator/releases) | 2.0.0-dev.3.10 | recommended: without it Khronos validation is `not_run` |
| [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) | 2.0.0 (add-on 1.7) | optional: live mode (open GUI session) |
| Rhubarb Lip Sync | 1.14 | optional phonetic mouth-cue analysis |
| Godot | 4.7 | detected; game import and prototype not yet implemented |

Optional binaries can be dropped into `%LOCALAPPDATA%\fluidblend\tools\<tool>\`: they are found
without touching the PATH ([docs/installation.md](docs/installation.md)).

## Installation

```powershell
git clone https://github.com/morganhub/fluidblend.git
cd fluidblend
uv sync --python 3.13
uv run fluidblend doctor          # real probes: Blender, FFmpeg, validator, MCP…
```

Or, in one go, `.\scripts\bootstrap.ps1` (sync, diagnostic, unit tests; it offers the missing
installations without running them).

## Try it in two minutes

```powershell
.\scripts\demo.ps1 -Path "D:\Projects\fluidblend demo"
```

The script initialises a project, builds the scene, slows down the hero's walk on a variant, renders
a 240-frame preview, exports a GLB and runs the technical validation. Result: versioned `.blend`
files in `shots\shot010\work\`, a `preview.mp4` proved by `ffprobe.json`, and a resumable journal in
`state\`.

## Using the skill with an agent

Graft the skill into your project (local copy, never global):

```powershell
.\scripts\install-skill.ps1 -Target "D:\Projects\My Film" -Client both        # Claude Code + Codex
.\scripts\install-skill.ps1 -Target "D:\Projects\My Film" -Client both -WithMcp   # + .mcp.json (live mode)
```

Then, in Claude Code or Codex opened on that folder, state a production request:

> "Initialise a short film, build shot010, slow the hero's walk down by 20% and give me a video
> preview."

The skill ([skills/fluidblend/SKILL.md](skills/fluidblend/SKILL.md)) has the matching `fluidblend`
commands executed, reads the proofs and stops on blockers (permission, budget, revision conflict)
instead of working around them. The per-domain references live in
[skills/fluidblend/references/](skills/fluidblend/references/).

## Using the CLI directly

```powershell
uv run fluidblend init --path "D:\Projects\My Film" --profile film --project-id my-film
uv run fluidblend plan --project "D:\Projects\My Film" --request requests\scene-build.json
uv run fluidblend run  --project "D:\Projects\My Film" --operation requests\scene-build.json
uv run fluidblend validate --project "D:\Projects\My Film" --target shot010
uv run fluidblend resume --project "D:\Projects\My Film"
```

A request is a typed JSON file (copy-ready examples in
[skills/fluidblend/assets/](skills/fluidblend/assets/), schemas in [schemas/](schemas/)):

```json
{
  "schema_version": "1.0",
  "operation": "animation.retime",
  "operation_id": "retime-shot010-hero-001",
  "project_id": "my-film",
  "target": {"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk", "expected_revision": 1},
  "parameters": {"duration_scale": 1.2, "output_variant": "walk-slower-v001", "preview_samples": 8}
}
```

Exit codes: `0` success, `1` known failure, `2` blocked (permission, dependency), `3` conflict,
`4` invalid request, `5` uncertain state (`task reconcile`), `6` budget exceeded. Details in
[docs/cli.md](docs/cli.md).

## Live mode (MCP)

The engine can drive the Blender session you already have open, for four operations:
`scene.inspect`, `scene.audit`, `animation.retime` and `scene.checkpoint`.

```powershell
uv run fluidblend runtime install --enable                      # approved runtime as a Blender add-on
uv run fluidblend live status --project "D:\Projects\My Film"    # identity of the open session
uv run fluidblend run --mode live --project . --operation requests/animation-retime.json
```

The transport is the community server
[MCP for Blender](https://github.com/ahujasid/mcp-for-blender), whose configuration the kit
generates (`fluidblend client-config --client claude|codex|vscode`) with safe mode on and telemetry
off. Because that safe mode only allows `import bpy`, the kit's runtime is installed as an **enabled
Blender add-on** (hash-checked, `fluidblend doctor` reports it as `blender.runtime_addon`): the
engine transmits nothing but `bpy.ops.fluidblend.identity()`, `run_request(...)` and
`open_file(...)`, never a generated script.

Before every live operation the engine checks the session's identity — runtime version, project,
open file equal to the shot's latest work version, no unsaved change — and answers `SCENE_CONFLICT`
(exit 3) without executing anything otherwise, so work in progress is preserved. `scene.checkpoint`
is the exception: it snapshots an unsaved scene on purpose. Blender must be open in its graphical
interface, and the add-on socket is not authenticated: see [docs/security.md](docs/security.md).

## Repository layout

```
skills/fluidblend/      skill (SKILL.md, references/, assets/, PowerShell wrapper)
src/fluidblend/         engine: CLI, pydantic contracts, core (tasks, journal, revisions), adapters
blender_runtime/        code executed inside Blender (stdlib + bpy): scene, retime, render, export
schemas/                JSON Schema exported from the contracts
templates/film/         project skeleton created by `init`
scripts/                install-skill.ps1, bootstrap.ps1, demo.ps1
tests/                  unit tests (no Blender), acceptance A01–A13 (batch) and L01–L05 (live)
docs/                   installation, CLI, architecture, security, compatibility, roadmap, sources
```

## Tests

```powershell
uv run pytest tests/unit -q                                   # without Blender, ~5 s
uv run pytest tests -q --acceptance-report docs/acceptance-reports/latest-p0   # with Blender, ~90 s
```

Scenarios that depend on a missing tool are marked `not_run`, never counted as passed. The live
scenarios (L01–L05) each open and close their own Blender GUI session and need port 9876 free; they
declare themselves `not_run` otherwise. The GitHub CI runs lint, schema consistency and the unit
tests on Windows.

## Documentation

[Installation](docs/installation.md) · [CLI](docs/cli.md) · [Architecture](docs/architecture.md) ·
[Security](docs/security.md) · [Proven compatibility](docs/compatibility-matrix.md) ·
[Roadmap](docs/roadmap.md) · [Sources and projects studied](docs/sources.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## License

The kit's code is under the [MIT](LICENSE) license. External tools keep their own licenses (Blender
GPL, FFmpeg GPL/LGPL depending on the build, glTF-Validator Apache-2.0, MCP for Blender MIT, Rhubarb
MIT, Godot MIT) and are not redistributed here. The demo assets are generated by the kit and free of
rights.
