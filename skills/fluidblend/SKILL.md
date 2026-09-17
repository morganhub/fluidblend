---
name: fluidblend
description: >-
  Create, resume and modify Blender projects for films, clips and games: initialize a production
  project, build a demo scene, inspect and audit a shot, retime an animation clip into a variant,
  render a preview and assemble it into video, export a verified GLB, diagnose the capabilities of
  the workstation and resume an interrupted task. Use for Blender production tasks driven by the
  `fluidblend` CLI, not for 2D video generation alone. Four of these operations can also run in the
  Blender session the user has open (live mode, `--mode live`). Also supports versioned Rigify
  characters and props, bounded animation clips with measured contacts, a bounded prop hand-off
  between two characters, audio preparation and mouth-cue analysis. Check the
  operation catalogue for unsupported production features; never simulate success.
license: MIT
metadata: {version: "0.4.1", lot: "P0+live+P1", compatibility: "Windows 11, Blender 5.2.x LTS, uv, PowerShell 7"}
---

# fluidblend — driven Blender production

The skill guides, it computes nothing. Every action goes through the kit's `fluidblend` CLI, which
validates, journals, locks, versions and produces evidence. No improvised `bpy` script on sources.

**Task completion criterion**: the files exist, reopen, match the request and come with published
evidence. Exit code 0 on its own proves nothing.

## Calling the CLI

The kit is grafted into a project through `scripts/install-skill.ps1 -Target <project> -Client both
[-WithMcp]` (copies to `.claude/skills/fluidblend/` and `.agents/skills/fluidblend/`, never a global
install).

Two equivalent ways to call the engine:

```powershell
uv run --project <kit> fluidblend <subcommand> --project <project>
.\skills\fluidblend\scripts\fluidblend.ps1 <subcommand> --project <project>
```

The wrapper resolves the kit root in this order: `$env:FLUIDBLEND_HOME`, then the `kit-path.txt`
written next to the skill by the installer, then walking up to a `pyproject.toml` that sits beside a
`blender_runtime/` directory. Add `--json` for structured output.

## Decision rules

1. **Identify the request**: create, inspect, animate, adjust, render, export, diagnose or develop a
   tool. Check `fluidblend ops --json`: only available operations may execute. State the limits
   of a partially supported domain before promising its full workflow.
2. **Read before writing**: `project.json`, `config/permissions.json`, `state/state.json` and
   `fluidblend inspect --project . --json`. Never assume the state of a project.
3. **Load only the reference that is useful** for the task (table below), not all of them.
4. **Check real capabilities** with `fluidblend doctor --project . --json` before any operation that
   depends on an external tool. Never invent a tool, and never assume that an MCP server provides
   this kit's production operations.
5. **Diagnostics are read-only.** `doctor`, `inspect`, `capabilities`, `task status`, `ops` and
   `revision list` modify no source. `doctor` and `resume` write reports under `state/` and say so.
   `doctor --project` compares dependency observations to the lock; only explicit `--write-lock`
   replaces a lock. Updates require a migration branch and regression evidence.
6. **Plan before writing**: `fluidblend plan --project . --request <file>` produces resources, a
   time/disk estimate, stop conditions and blocking errors, without mutating the scene.
   `fluidblend run --dry-run` does the same while recording a `planned` task.
7. **Execute without per-keyframe confirmation** inside the scope allowed by
   `config/permissions.json`. The scaffold's `assisted` profile authorizes reversible local
   operations; do not ask again for an approval already given for the same scope.
8. **Variants and versions, never protected sources.** `scene.build` publishes `v001`,
   `animation.retime` publishes `v(N+1)` and keeps the source Action intact. `shots/*/approved/**`,
   `audio/source/**` and `assets/*/*/source/**` are never modified by the kit.
9. **Validate structure first, then visuals.** `scene.audit` and `fluidblend validate --target
   <shot>` yield `technical_pass`. `technical_pass` is not `art_approved`: art validation stays
   human and must cite the frames actually looked at.
10. **On failure, fix within the limits; never repeat an uncertain write.** Exit 5 means unknown
    write state: run `fluidblend task reconcile --project . --id <task>` before any new attempt.
    Three attempts with no measured improvement → stop and explain.
11. **Record a resume point at every milestone**: `fluidblend resume --project .` rebuilds the state
    from `state/journal.jsonl` and lists the tasks to reconcile.
12. **Deliver files + evidence + limits**: published paths, measured metrics, checks that were not
    run (`not_run`) and the next useful decision.
13. **Batch by default, live only when the user is working in Blender.** `--mode live` covers four
    operations and refuses a session that does not match the request. Never modify an open session
    with an improvised script through an MCP tool.

Do not turn "fix the gaze" into permission to regenerate the character, change the rig or replace
the dialogue.

## Request → mode → reference → commands

| User request | Mode | Reference to read | Commands |
| --- | --- | --- | --- |
| "does it work on my machine?", missing tool, Blender not found | diagnostics | `references/environment.md` | `fluidblend doctor --project . --json` |
| Create or resume a project, read state, plan | project | `references/project.md` | `fluidblend init`, `inspect`, `plan`, `resume` |
| Build or audit a scene, characters, rigs | scene | `references/characters.md` | `scene.build`, `shot.build`, `character.inspect`, `rig.map`, `rig.validate`, scene inspection/audit |
| Slow down, speed up, vary a clip | animation | `references/animation.md` | `animation.retime/create/apply/loop/bake` |
| Put one character's motion on another | animation | `references/animation.md` | `animation.retarget` — only P0 biped → Rigify; Mixamo, mocap or any other pair: refuse (`RIG_MAPPING_REQUIRED`) and say so |
| Pass a prop from one character to another, contacts | interactions | `references/interactions.md` | `interaction.plan` → review → `interaction.apply` → `interaction.validate` (bounded prop hand-off only) |
| Shot preview, video, film assembly, audio | film | `references/film.md` | `shot.preview`, `film.assemble`, `audio.prepare`, `lipsync.analyze`; `fluidblend validate` |
| Make a character say a line, smile, blink | film | `references/film.md` | `audio.prepare` → `lipsync.analyze` → `lipsync.apply`; `expression.apply` — needs a character with a `face_profile`, otherwise `RIG_MAPPING_REQUIRED`: say so |
| Export to a game engine, broken export | game | `references/game.md` | `run` on `game.export` |
| "Does it work in Godot?" | game | `references/game.md` | `game.export` (one character) → `game.import_test` → `game.smoke_test`; no Godot = `not_tested`, say so |
| "fix the sliding foot", "keep the hand on the handle" | tools | `references/tool-development.md` | `adjustment.preview` → look at the frames → `adjustment.apply`; `adjustment.revert` (tool `contact_lock` only) |
| "make me a tool that…" | tools | `references/tool-development.md` | declarative `tools/custom/<id>/tool.json` narrowing `contact_lock` → `tool.inspect` → `tool.test` → `tool.register`; `unsupported` = state the limitation, stop |
| "add a slider", gesture amplitude, gaze, partial retime | tools | `references/tool-development.md` | not implemented (P1) |
| "look at the scene I have open", retime while the user watches | live | `references/environment.md` | `fluidblend live status --project .`, `fluidblend run --mode live` |
| Stuck task, interrupted run, conflict, budget | recovery | `references/recovery.md` | `fluidblend task status/cancel/reconcile`, `resume`, `revision accept` |

## Trigger use cases

| Situation | Exact command |
| --- | --- |
| Initialize a short film | `fluidblend init --path "D:\Projects\My Film" --profile film --project-id my-film --dry-run` then without `--dry-run` |
| Resume a shot after a lost session | `fluidblend resume --project .` then `fluidblend inspect --project . --json` |
| Build the demo scene of a shot | `fluidblend run --project . --operation requests/scene-build.json` |
| Slow a clip down into a variant | `fluidblend run --project . --operation requests/animation-retime.json` |
| Produce a preview and validate it | `fluidblend run --project . --operation requests/shot-preview.json` then `fluidblend validate --project . --target shot010` |
| Export a GLB | `fluidblend run --project . --operation requests/game-export.json` |
| Diagnose a broken export | `fluidblend doctor --project . --json` then read `exports/<shot>/<operation_id>/export-report.json` and `gltf-validator.json` |

The five copy-ready example requests live in `assets/`:
[request-scene-build.json](assets/request-scene-build.json),
[request-animation-retime.json](assets/request-animation-retime.json),
[request-shot-preview.json](assets/request-shot-preview.json),
[request-game-export.json](assets/request-game-export.json),
[request-film-assemble.json](assets/request-film-assemble.json). Copy them into the project, adapt
`project_id`, `operation_id` and `target`, then pass them to `plan` or `run`. The path given to
`--operation` is relative to the project or absolute; the `requests/` folder used above is created
by the scaffold.

## Live mode: writing into the open Blender session

Available since 0.2.0, for **four operations only**: `scene.inspect`, `scene.audit`,
`animation.retime`, `scene.checkpoint`. Everything else runs in batch on the published work version,
even when `--mode live` is passed.

```powershell
fluidblend runtime install --enable      # once, and again after every kit update
fluidblend live status --project .       # exit 2 = no usable session
fluidblend run --mode live --project . --operation requests/animation-retime.json
```

Use `--mode live` when the user is in Blender right now and asks about the scene in front of them.
Otherwise prefer batch: it needs nothing open. Three prerequisites, all required: Blender 5.2 open
**in its graphical interface** with the MCP add-on server listening, the kit's runtime add-on
installed and enabled, and the open file being the shot's latest work version.
`fluidblend live status` reports all of it in one call, and `fluidblend doctor` reports the add-on
as capability `blender.runtime_addon`.

The engine checks the session's identity before executing anything, and refuses rather than
overwrite:

| Situation | Answer | What to do |
| --- | --- | --- |
| unsaved changes in the session | `SCENE_CONFLICT`, exit 3 | ask the user to save or revert in Blender, then retry — never do it for them |
| the open file is not the shot's latest work version | `SCENE_CONFLICT`, exit 3 | ask them to open that version; the message gives both paths |
| scene of another project, or runtime version different from the kit | `SCENE_CONFLICT`, exit 3 | wrong session, or `fluidblend runtime install --enable` after a kit update |
| runtime add-on not enabled, MCP server unreachable | exit 2 | install and enable it, or fall back to batch |
| call timed out | `unknown`, exit 5 | `fluidblend task reconcile`, then have the latest work version reopened before retrying |
| the user wants a running live operation stopped | — | `fluidblend task cancel --project . --id <task>`: `cancelled: true` only with the session's written acknowledgement (`nothing_saved`); otherwise the state is `unknown` → reconcile. Never close or kill their Blender |

Live operations run cooperatively: Blender stays responsive and `fluidblend task status` shows the
last step reported. A human edit made while a live operation runs stops it with `SCENE_CONFLICT`
and is kept.

**Director panel.** The runtime add-on also adds a `Director` panel (3D View sidebar, `fluidblend`
tab) with Preview / Apply / Revert for `contact_lock`. It runs the same `adjustment.*` operations
through the engine, in batch, on the published version; it never keys the open session. Point the
user to it when they want to try values themselves; for anything you do, keep using the CLI. It
refuses Apply and Revert while the session has unsaved changes — in Blender a mere selection counts.
Tell the user **not to save** over the open published version (that creates a revision conflict) and
to use the panel's `Reload file` button instead. A preview moves nothing in the viewport: only Apply
shows the fix, by opening the new version. If they report "already applied", they are looking at an
older version than the one the engine works on: the panel offers `Open latest version`.

A live write is never saved over the open file: the operation saves a copy, the engine publishes the
next work version and reloads the session on it. If the result warns that the reload failed, tell
the user to reopen the published file **before saving anything**, otherwise their next save would
overwrite the previous version. `scene.checkpoint` is the only live operation that accepts unsaved
changes: use it to snapshot work in progress.

**Never write through the client's own MCP connection.** If the AI client has its own Blender MCP
server, its direct tools are acceptable for read-only exploration only (`get_scene_info`,
`get_viewport_screenshot`, `get_object_info`). Every write goes through
`fluidblend run --mode live`, never through `execute_blender_code` with an improvised script: that
path has no identity check, no lock, no checkpoint, no version and no journal.

## Invariants

- `operation_id` (3 to 100 characters `[A-Za-z0-9._-]`) is chosen by the caller and **stable**: it
  is the idempotency key. Same identifier and same parameters → the already published result is read
  back, no new version. Different parameters → `SCENE_CONFLICT`.
- Unknown parameters are refused (`extra=forbid`). One extra field invalidates the whole request.
- Every write takes the project lock, creates a checkpoint of the source, writes into
  `state/tasks/<task_id>/out/`, verifies the artifacts (existence and sha256), then publishes.
- `duration_scale = 1.2` multiplies the **duration** by 1.2: the animation becomes slower.
- Frame ranges: `[start, end_exclusive)` in the contracts; Blender receives inclusive bounds.
  `end_exclusive = 241` means 240 frames.
- The Blender runtime requires the 5.2 series. Any other version answers `UNSUPPORTED_CAPABILITY`.
- The kit reads `config/permissions.json` and never writes it. Widening the scope is a user
  decision, not a skill action.

## What this lot does not do

19 operations are available in P0, of which only 10 run through `fluidblend run` (`scene.build`,
`scene.inspect`, `scene.audit`, `animation.retime`, `shot.preview`, `game.export`,
`scene.checkpoint`, `shot.validate`, `film.assemble`, `providers.check`); the others go through a
dedicated subcommand (see `docs/cli.md`). 24 bounded P1 operations are available: `shot.build`,
`character.inspect`, `rig.map`, `rig.validate`, `animation.create/apply/loop/bake`,
`interaction.plan/apply/validate`, `adjustment.preview/apply/revert` (two tools, `contact_lock` and `look_at_target`),
`tool.inspect/test/register` (declarative custom tools, no code), `audio.prepare`,
`lipsync.analyze`, `lipsync.apply`, `expression.apply` (characters with a face profile only),
`animation.retarget` (one preset: P0 biped → Rigify; any other rig pair is refused),
`game.import_test`, `game.smoke_test` (Godot 4.7, the kit's own template). Every catalogue entry is
now available, **each inside a narrow, stated scope**: most requests still end in a refusal
(`RIG_MAPPING_REQUIRED`, `VALIDATION_FAILED`, `MISSING_DEPENDENCY`) rather than in an unavailable
operation. P2 features (render queue, crowds, mocap, OTIO, web panel) are not in the catalogue at all. The catalogue is the authority: check with `fluidblend ops --all`.

Live mode covers **four operations only** (see the section above). `scene.build`, `shot.preview` and
`game.export` are refused in a live envelope and run in batch instead. Live mode also requires an
open **GUI** Blender session: the MCP add-on refuses `--background` and publishes its socket on
`localhost:9876`. Without such a session, `fluidblend doctor --live` stays `unverified` and
`fluidblend live status` exits 2: this is normal, the batch CLI does not need either.

Sentence to say to the user, without working around it:

"This operation belongs to lot P1/P2 and is not implemented in this lot. I am stopping here rather
than producing an unverifiable result. What is possible today: *<closest P0 operation>*. The roadmap
is in `docs/roadmap.md`."

Never simulate the missing operation with an ad hoc `bpy` script, never weaken a validator and never
delete a test in order to announce a success.

## Mandatory stops

Stop, describe the blocker, list the preserved artifacts and the minimal decision expected:

- protected source, system permission or elevation request;
- external cost that was not pre-authorized, unauthorized upload, missing secret;
- installation or migration beyond the approved lot: the tools already present (MCP add-on, Godot,
  Rhubarb, Khronos validator) were installed on explicit approval; any further install or update
  must be asked for again;
- concurrent modification, unsaved source or uncertain write state (exit 3 or 5);
- live session that does not match the request: report what is open and what was expected, and let
  the user save, revert or reopen — never save, revert or reload their Blender on their behalf;
- unknown license for a planned redistribution;
- time, frame or disk budget exceeded (exit 6);
- three correction attempts without demonstrated improvement.

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | success, dry run or idempotent replay | continue |
| 1 | known failure, partial effects listed | read `state/tasks/<task_id>/` |
| 2 | missing permission, dependency or capability | explain, ask for the decision |
| 3 | revision conflict, lock, reused `operation_id`, live session mismatch | `fluidblend revision accept`, a new `operation_id`, or fix the open session |
| 4 | invalid request or arguments, nothing executed | fix the request |
| 5 | uncertain write state | `fluidblend task reconcile --project . --id <task>` |
| 6 | budget exceeded, stopped before execution | reduce the request or have the budget widened |

Domain error codes: `MISSING_DEPENDENCY`, `UNSUPPORTED_CAPABILITY`, `RIG_MAPPING_REQUIRED`,
`SCENE_CONFLICT`, `PERMISSION_REQUIRED`, `BUDGET_EXCEEDED`, `TIMEOUT_UNKNOWN_STATE`,
`VALIDATION_FAILED`, `INTERNAL_ERROR`.

## References

- [references/environment.md](references/environment.md) — diagnostics, capabilities, pinned
  Blender, MCP, client configuration, live mode (runtime add-on, identity, limits).
- [references/project.md](references/project.md) — scaffold, manifests, permissions, budgets, plans,
  publication.
- [references/characters.md](references/characters.md) — P0 rig profile, demo scene, audit; P1
  characters.
- [references/animation.md](references/animation.md) — slotted Actions, retime, contact markers; P1
  clip library.
- [references/interactions.md](references/interactions.md) — bounded prop hand-off: plan, apply,
  validate, prerequisites, measurements, limits.
- [references/film.md](references/film.md) — previews, FFmpeg, ffprobe, technical validation,
  assembly.
- [references/game.md](references/game.md) — GLB export, axes, reimport, Khronos validator; P1
  Godot.
- [references/tool-development.md](references/tool-development.md) — `contact_lock` preview / apply /
  revert, tool contract, adjustments that do not exist yet.
- [references/recovery.md](references/recovery.md) — task states, idempotency, revisions,
  reconciliation, locks.
