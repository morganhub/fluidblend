# Production project

Status: **implemented (lot P0)**. Operations covered: `project.init`, `project.inspect`,
`project.plan`, `project.resume`, `scene.checkpoint`.

The four `project.*` operations are invoked through CLI subcommands (`init`, `inspect`, `plan`,
`resume`), not through `fluidblend run`.

## Create or complete a project

```powershell
fluidblend init --path "D:\Projects\My Film" --profile film --project-id my-film --name "My Film" --dry-run
fluidblend init --path "D:\Projects\My Film" --profile film --project-id my-film --name "My Film"
```

- `--profile`: `film` (default), `game`, `hybrid`. `game` and `hybrid` add `game/` and
  `exports/game`. `--game-engine`: `godot`, `web`, `none` (forced to `none` in the `film` profile).
- `--project-id`: lowercase letters, digits, `.`, `_`, `-`, 64 characters maximum. Derived from the
  folder name if omitted.
- `--dry-run`: writes nothing, lists what would be created.
- `--strict`: exits 3 (`CONFLICT`) if an existing file differs from the template.

The operation is **idempotent and non-destructive**. An existing file is never overwritten: it is
classified as `identical` (JSON comparison that ignores `created_at`) or as `conflicts`, with both
sha256 values and `action: kept_existing`. Re-running it on an already initialized project
duplicates nothing (acceptance scenario A02). Paths containing spaces and accented characters are
supported (acceptance scenario A01).

## Tree produced

```
project.json                     main manifest
config/local.json                absolute machine paths, not versioned, no secret
config/permissions.json          approved scope (read, never written by the kit)
config/quality.json              technical thresholds
config/providers.json            external providers (empty in P0)
requests/                        operation requests (`run --operation`), created empty
assets/{characters,props,environments}/
animation/{clips,rig-maps,recipes}/
shots/<shot_id>/shot.json        declarative timeline of the shot
shots/<shot_id>/work/vNNN/       published work versions
audio/                           audio sources (audio/source/** is protected)
tools/custom/                    generated tools (P1)
reviews/<shot>/<operation_id>/   inspection, audit, retime and validation reports
renders/<shot>/<operation_id>/   frames/, render-report.json, preview.mp4, ffprobe.json
exports/<shot>/<operation_id>/   .glb, export-report.json, gltf-validator.json
checkpoints/<ckpt-id>/           copy of the source before writing + checkpoint.json
state/                           journal, state, revisions, tasks, plans, locks, diagnostics
licenses/                        licenses of the components used
AGENTS.md, CLAUDE.md             project instructions for AI clients
```

The scaffold creates a demo shot, `shots/shot010/shot.json`: `hero-01` (stylized biped,
`[-0.7, 2.0, 0]`), `sidekick-01` (scale 0.85, phase offset of 12 frames), prop `lantern-01`, a 35 mm
camera at `[5.5, 0, 1.4]` aiming at `[0, 0, 1]`, range `[1, 241)`, i.e. 240 frames.

## Manifests

`project.json` — `schema_version`, `project_id`, `name`, `profile`, `style`, `units` (`meters`),
`fps` (`{numerator, denominator}`, 24/1 by default), `targets`, `autonomy`, `budgets`, `preview`,
`dependency_lock`, `created_at`, `fluidblend_version`. A `schema_version` different from the kit's
blocks loading: migration is explicit, never silent.

`shots/<shot_id>/shot.json` — `shot_id`, `frame_range` `{start, end_exclusive}`, `instances`,
`props`, `camera`, `audio`, `validation_state`, `notes`. Each instance declares `instance_id`,
`asset_id`, `rig_profile`, `initial_location`, `clip_id`, `phase_offset_frames`, `scale`.
`instance_id` values are unique within a shot.

`validation_state`: `draft` → `technical_pass` → `visual_review_pending` → `art_approved`. The kit
only ever moves a shot to `technical_pass`, and only as a suggestion in the validation report. The
last two states are human decisions.

`config/local.json` — absolute machine paths (`blender_executable`, `ffmpeg_executable`,
`ffprobe_executable`, `gltf_validator_executable`, `godot_executable`, `rhubarb_executable`), the
`mcp` block (`server_name`, `host`, `port`, `startup_timeout_s`, `call_timeout_s` — used by live
mode) and `blender_startup_timeout_s`. This file never contains a secret and is not meant to be versioned.

`config/quality.json` — `foot_slide_max_m` 0.02; `contact_error_max_m` 0.02;
`audio_drift_max_frames` 1.0; `loop_pose_error_max` 0.001; `preview_missing_frames_max` 0. These are
adjustable initial values, not standards.

## Permissions

`config/permissions.json` is read on every operation and **never written** by the kit.

| Profile | Allowed without a new request | Expected stop |
| --- | --- | --- |
| `inspect` | reads and diagnostics | any `write`, `render` or `export` operation → `PERMISSION_REQUIRED` |
| `assisted` (scaffold default) | plan, variants and tests for the authorized task | artistic milestones defined by the user |
| `local_autonomous` | reversible local operations, previews, planned repairs | overrun, protected source, new dependency, external effect |
| `batch_approved` | execution of an approved plan within a defined budget | deviation from the plan, blocking validation |

- `allowed_operations`: exact names or `domain.*` patterns; `*` allows every local operation.
- `protected_paths`: glob patterns relative to the project, by default `shots/*/approved/**`,
  `audio/source/**`, `assets/*/*/source/**`. A path parameter that falls inside them is refused.
- `allow_new_dependencies` and `allow_network` are `false`; setting them to `true` is a user
  decision.

A permissions file that the agent can edit is not a security boundary: see `docs/security.md`.

## Budgets

In `project.json`: `max_task_minutes` 20, `max_preview_frames` 240, `max_new_disk_gib` 5,
`max_external_spend` 0. The time budget becomes the **timeout of the Blender worker**. An overrun is
detected *before* execution from an estimate, and exits 6 (`BUDGET_EXCEEDED`).

The estimate is calibrated on the real measurements recorded in `state/metrics.json` (rolling
average over the last eight renders). Deliberately pessimistic fallback values: Workbench 0.2 s per
frame, EEVEE 2.5 s per frame, 0.25 MiB per frame, 4 s of Blender startup, 6 s for a GLB export. On
the reference workstation at 640x360, the demo scene renders faster than this estimate in Workbench
and markedly slower in EEVEE: read `state/metrics.json` and the latest `render-report.json` instead
of announcing a duration from memory.

## Planning

```powershell
fluidblend plan --project . --request requests/shot010-preview.json --json
```

The plan is written to `state/plans/<operation_id>.json` and journaled. It contains: `backend`
(`host` or `blender`), `op_class` (`read`, `write`, `render`, `export`), `lot`, `available`,
`permission_ok`, `estimated_seconds`, `estimated_new_disk_mib`, `resources` (required executables),
`budget`, `stop_conditions`, `steps`, `warnings`, `blocking_errors`. Exit 2 (`BLOCKED`) when there
are blocking errors, 0 otherwise. `plan` never mutates the scene.

`fluidblend run --dry-run` produces the same plan and records a task in the `planned` state, with no
checkpoint and no write into the project.

## Inspect and resume

```powershell
fluidblend inspect --project . --json     # manifests, plans, versions, revisions, tasks
fluidblend resume  --project . --json     # rebuilds the state, lists what to resume
fluidblend ops --all                      # full catalogue with availability
fluidblend revision list --project . --json
```

`inspect` lists, for each shot, its work versions, its `validation_state` and its latest version, as
well as the recorded revisions, the unfinished tasks, the number of checkpoints and the number of
journal events.

`resume` rebuilds the state from `state/journal.jsonl`, writes `state/resume-report.json` and
returns **5 (`UNKNOWN_STATE`) when tasks remain to be reconciled**, 0 otherwise. The report contains
the exact `task reconcile` commands to run. It is the first command to run at the start of a session
on an unknown project.

## Checkpoints

```powershell
fluidblend run --project . --operation requests/checkpoint.json   # scene.checkpoint, free-form label
```

`scene.checkpoint` copies the shot's latest work version into `checkpoints/<ckpt-id>/` together with
a manifest (source, sha256, size, label, task, timestamp). The copy is verified by hash: if the file
changes during the copy, the operation fails rather than recording a false checkpoint. The engine
additionally creates an automatic checkpoint before any `write`-class operation.

### Checkpoint of the open session (live mode)

```powershell
fluidblend run --mode live --project . --operation requests/checkpoint.json
```

In live mode the same operation snapshots the Blender session the user has open, **unsaved changes
included**, with `save_as_mainfile(copy=True)`: the active file is not touched, not saved and not
renamed. The copy is published, then recorded under `checkpoints/<ckpt-id>/` like any other
checkpoint, and the result carries a `was_dirty` metric plus a `checkpoint-live.json` report (label,
source file, identity read from the scene, size).

It is the only live operation that accepts a dirty session — every other one answers
`SCENE_CONFLICT` (exit 3) as long as changes are unsaved. Practical consequence: when a live
operation is refused because the user has work in progress, offering a live `scene.checkpoint` is
the right move; it protects that work without asking them to save over anything. Prerequisites and
identity rules: `references/environment.md`.

## Publication

An operation never writes directly into the project. It produces its files in
`state/tasks/<task_id>/out/`, the engine verifies each announced artifact (presence and sha256),
then moves the whole set to its destination:

| Operation class | Destination |
| --- | --- |
| versioning (`scene.build`, `animation.retime`) | `shots/<shot>/work/vNNN/<shot>.blend` for the `.blend`, `reviews/<shot>/<operation_id>/` for the reports |
| `render` | `renders/<shot>/<operation_id>/` |
| `export` | `exports/<shot>/<operation_id>/` |
| `read` and others | `reviews/<shot>/<operation_id>/` |

A destination that is already occupied triggers `SCENE_CONFLICT` rather than an overwrite. Every
published artifact is journaled (`artifact_published`) with its relative path and its sha256.
