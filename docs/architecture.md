# Architecture

## Layers

| Layer | Location | Responsibility | Does not do |
| --- | --- | --- | --- |
| Skill | `skills/fluidblend/` | understand the request, choose the mode, read the right reference, drive the validations | no business logic, no computation |
| Engine | `src/fluidblend/` | contracts, planning, execution, journal, versions, budgets, resumption, CLI | never depends on `bpy` nor on a model name |
| Blender runtime | `blender_runtime/fluidblend_runtime/` | scenes, rigs, Actions, cameras, renders, exports through the Blender API; in live mode, the same package installed as an add-on exposes `bpy.ops.fluidblend.*` and the Director panel | stdlib + `bpy` only, no third-party dependency; the panel holds no production logic |
| Adapters | `src/fluidblend/adapters/` | Blender batch, Blender live (`blender_live`), discovery of Blender and of external tools (`tool_paths`), FFmpeg, glTF-Validator, MCP client, client configuration | hide no error, invent no feature |
| Project | the user's project | assets, manifests, shot plans, variants, proofs, durable state | does not depend on the memory of a conversation |

The engine never imports `bpy`: the pure Python tests run without Blender. The runtime never imports
pydantic: it validates the envelope it receives with the standard library.

```
AI client (Claude Code / Codex)
  │ reads SKILL.md + references/<mode>.md, calls the CLI
  ▼
fluidblend (CLI)  →  contracts/ (pydantic → schemas/*.json)
  │                  core/ (planner, tasks, state, locks, budgets, revisions, paths, checkpoints)
  │                  hostops/ (checkpoint, validation, assembly)
  ▼ request.json (envelope) / result.json (shared contract)
  ├─ batch (default)
  │    blender.exe --background --factory-startup --offline-mode
  │      └ blender_runtime/entrypoint.py → fluidblend_runtime/ops/*
  └─ live (--mode live, 4 operations)
       uvx mcp-for-blender (stdio) → add-on socket localhost:9876 → Blender main thread
         └ bpy.ops.fluidblend.run_request(...) → fluidblend_runtime/ops/*  (enabled add-on)
```

Both paths share the same envelope, the same runtime code and the same `result.json`: only the
transport and the `context.live` flag differ.

## Flow of a `run`

1. **Validation** — the `OperationRequest` envelope, then the parameters against the operation's
   model. Failure → exit 4, nothing is executed, a `request_rejected` event is journaled.
2. **Preflight** — consistent `project_id`; path parameters (`audio_path`, `request_path`) resolved
   inside the root and checked against the protected paths; operation available; permission granted;
   estimated budget under the ceilings; existing plan if the operation requires one.
3. **Idempotency** — lookup in the registry rebuilt from the journal: result already published →
   re-read (exit 0); different fingerprint → exit 3; task running or unknown → exit 5.
4. **Source resolution** — the shot's latest work version, except for `scene.build`.
5. **Revision** — for any non-`read` operation targeting a shot, the file's actual sha256 is compared
   with the recorded revision and with `expected_revision`.
6. **Lock** — exclusive project lock, 5-second wait, owner written to
   `state/locks/project.owner.json`.
7. **Task** — creation of `state/tasks/<task_id>/` and of `out/`, recording of the fingerprint, the
   budget and the target.
8. **Checkpoint** — for any `write`-class operation, a verified copy of the source into
   `checkpoints/<ckpt-id>/`.
9. **Execution** — host backend (direct call), Blender backend (dedicated worker), or live session
   (see below). The worker receives the full envelope: request, project root, task folders, path of
   the work version, shot manifest, frame rate, preview settings, budgets, quality thresholds,
   expected runtime version. `PYTHONPATH` is removed from its environment.
10. **Post-processing** — FFmpeg assembly and ffprobe proof for `shot.preview`, Khronos validation
    for `game.export`.
11. **Artifact verification** — every announced artifact must exist and, if it is a file, carry the
    declared sha256. Otherwise the operation fails before publication.
12. **Publication** — `out/` is moved to its final destination, the new revision is recorded for
    versioning operations, and every published artifact is journaled.

A dry run stops after step 7: a plan is recorded, the task stays `planned`, no checkpoint is created
and nothing is published.

## Live mode

`fluidblend run --mode live` routes four operations — `scene.inspect`, `scene.audit`,
`animation.retime`, `scene.checkpoint` (`LIVE_OPERATIONS` in `core/tasks.py`) — to the Blender
session the user has open. Every other operation keeps the batch path even with `--mode live`, and
the runtime refuses `scene.build`, `shot.preview` and `game.export` inside a live envelope
(`BATCH_ONLY_OPERATIONS`) with `UNSUPPORTED_CAPABILITY`.

Why an add-on rather than a script: the MCP add-on's safe mode (`BLENDER_MCP_SAFE_MODE=1`) only
allows `import bpy` — plus `bmesh`, `mathutils` and a few stdlib modules — and forbids `open()`,
`bpy.utils.register_class`, `bpy.app.timers` and the `script`/`text`/`preferences` operator
families. So the runtime is installed as an **enabled Blender add-on**
(`fluidblend runtime install --enable`, `core/runtime_install.py`) that registers three operators,
and the engine transmits nothing but a call to one of them. Safe mode stays on.

Steps of a live run, inside the project **and** `blender-instance` locks:

1. **Server** — the `.mcp.json` entry named by `config/local.json` → `mcp.server_name`, else an
   entry generated from `mcp.host`/`mcp.port`. One `uvx --python 3.11 mcp-for-blender` stdio process
   is started per phase (identity, run, reload) and stopped afterwards.
2. **Identity** — `bpy.ops.fluidblend.identity()` returns the runtime and Blender versions, the open
   file, `is_dirty` and the scene's `fluidblend_*` properties (project, shot, revision). The engine
   compares them with the request: runtime version equal to the kit version, same `project_id`, open
   file equal to the shot's latest work version (compared after `realpath`), and no unsaved change.
   Any mismatch → `SCENE_CONFLICT` (exit 3), nothing is executed. `scene.checkpoint` is the one
   exception on the dirty flag: snapshotting unsaved work is its purpose. The check is journaled as
   `live_identity_checked`.
3. **Execution** — the envelope is written to the task folder, then
   `bpy.ops.fluidblend.start_request(request_path=…, result_path=…)` queues it and returns at once.
   A `bpy.app.timers` callback of the add-on (`live_jobs.py`) advances the operation one cooperative
   step per tick on the main thread, so Blender stays responsive. It publishes `progress.json` in
   the task folder; the engine polls files, not the socket, and mirrors the progress in the task
   record. The engine scope that hides the kit's own edits from the edit generation is held only
   during a step, never across ticks: a human edit between two steps stops the operation with
   `SCENE_CONFLICT` and is kept. The envelope carries `live: true` and no `work_blend`: the runtime
   works on the session as it is. The result is read back from `result.json`, with
   `metrics.mode = "live"` and the identity that was accepted.
   **Cancellation**: `task cancel` writes `cancel.request`; the timer stops between two steps,
   writes `cancel.ack.json` (step reached, `session_modified`, `nothing_saved`) and a `cancelled`
   result. Only that acknowledgement makes the task `cancelled` (journal
   `live_cancel_acknowledged`); without it the state stays `unknown`, and the GUI is never killed.
   A step that does not yield cannot be interrupted: the stop lands after it.
4. **Publication** — artifacts and input hashes verified; the live completion identity is checked
   again. A changed generation prevents publication. Then `out/` is moved and the revision recorded.
5. **Reload** — for a versioning operation, `bpy.ops.fluidblend.open_file(filepath=…, expected_identity=…)`
   checks the generation and identity atomically inside Blender, then points the
   session at the file that was just published (`live_session_reloaded` in the journal). A failure
   is a warning, not an error: the user is told to reopen the file before saving, otherwise the
   previous version would be overwritten.

Write isolation: in live mode `animation.retime` saves with `save_as_mainfile(copy=True)`, so the
open file and the version already on disk are left exactly as they were; the copy becomes the new
version through the normal publication path.

### Director panel

`fluidblend_runtime/director.py` adds a `Director` panel to the 3D View sidebar. It holds no
production logic: Preview, Apply and Revert write a typed `adjustment.*` request under
`requests/director/` and start the kit's CLI (`RUNTIME_MANIFEST.json` → `cli`, argument list, no
shell, `PYTHON*` variables removed) in **batch** mode, on the published work version. A timer reads
the JSON outcome. The open session is therefore never keyed or dirtied by a preview; its state lives
on the window manager, which is not saved in the `.blend`. Bounded sliders are debounced (0.6 s):
many drag events give one preview. Apply and Revert are refused while the session has unsaved
changes, publish a new revision through the normal journal, then reopen it with the identity-guarded
`open_file`; an edit made meanwhile cancels the reopen and is kept.

The panel states its own preconditions instead of showing controls that cannot work: outside a
project, without a character of a supported rig profile (the P0 bipeds have no IK and are named as
unusable), on a file that is **not the latest work version** (the engine always works on the latest
one; an `Open latest version` button replaces the controls), and on an unsaved scene. In Blender a
mere selection flags the scene as unsaved; the panel never advises saving, which would overwrite a
published version, and offers `Reload file (discard my changes)` behind a confirmation. Preview and
Apply are disabled when the fix name already exists in the scene, Revert when it does not. A preview
moves nothing in the viewport by design; the panel says so, reports the slide before and after in
plain words and opens the before/after frames. Timers tag the sidebar for redraw, otherwise the
status would stay stale until the mouse passes over it. `director.py` is the only
runtime module allowed to import `subprocess` (guard test).

Lost response: past `mcp.call_timeout_s` the engine cannot know what the session did, so the task is
left `unknown` (exit 5), any retry is refused until `fluidblend task reconcile`, and the user must
reopen the latest work version before trying again.

## Contracts

Single source of truth: the pydantic models in `src/fluidblend/contracts/`, exported as JSON
Schema 2020-12 into `schemas/` by `fluidblend schema export`. `fluidblend schema check` verifies
that the exported files are up to date.

Main models: `ProjectManifest`, `LocalConfig`, `Permissions`, `QualityThresholds`,
`ProvidersConfig`, `ShotManifest`, `InstanceRef`, `CameraSpec`, `RevisionsFile`, `DependencyLock`,
`OperationRequest`, `OperationResult`, `ErrorRecord`, `Artifact`, `ChangedEntity`, `TaskRecord`,
`Plan`, `Capability`, `CapabilitiesReport`.

They all inherit from a strict model: **no unknown field is accepted**. One extra parameter
invalidates the whole request rather than being silently ignored.

Cross-cutting conventions:

- time: `FrameRange {start, end_exclusive}`, with a documented conversion to Blender's inclusive
  bounds (`frame_start`, `frame_end`);
- frame rate: rational `Fps {numerator, denominator}`, converted into `scene.render.fps` and
  `fps_base`;
- units: metres and radians; seconds for audio;
- axes: Blender Z-up / −Y forward, glTF Y-up / +Z forward, with the convention recorded in the
  export reports.

`OperationResult` carries `status`, `changed_entities`, `artifacts`, `warnings`, `errors`,
`metrics`, `checkpoint_id`, `new_revision` and `next_safe_actions`.

## Task states

| State | Meaning | Allowed follow-up |
| --- | --- | --- |
| `planned` | operation computed without mutating the scene | re-run without `dry_run` |
| `queued` | authorised, waiting for resources | wait |
| `running` | real execution, owner and progress recorded | monitor |
| `validating` | outputs produced, not published yet | re-run nothing |
| `succeeded` | proofs and revision published | carry on |
| `failed` | known failure, partial effects listed | fix and re-run |
| `blocked` | missing permission, dependency or choice | user decision |
| `unknown` | uncertain write state | inspection required before another attempt |
| `cancelled` | confirmed stop, sources and partial outputs identified | re-run if relevant |

Every task record carries a `mode` field, `batch` or `live`, so a state read after the fact says
which Blender executed the operation.

Three distinct timeouts: MCP server start-up (`mcp.startup_timeout_s`), MCP call
(`mcp.call_timeout_s`, which bounds every live operation) and task budget
(`budgets.max_task_minutes`, which becomes the Blender worker's timeout in batch mode).
`blender_startup_timeout_s` bounds the `doctor` probes.

## Idempotency

Key: the `operation_id` supplied by the caller. Fingerprint: canonical sha256 of `(operation,
target, parameters, expected_revision)`. The registry is **rebuilt from the journal**; there is no
separate registry file to keep consistent.

A client that retries after a timeout never duplicates a collection or an Action: either it re-reads
a published result, or it is sent to reconciliation.

## Revisions

`state/revisions.json` maps each `shot:<shot_id>` target to a revision number, a path, a sha256, a
size, a timestamp and an origin (`kit`, `external_accepted`, `init`). A manual modification of a
file is detected through a hash mismatch, reported as `SCENE_CONFLICT` and **preserved**;
`fluidblend revision accept` records it as a new revision.

## Publication

| Class | Destination |
| --- | --- |
| versioning | `shots/<shot>/work/vNNN/<shot>.blend` + `reviews/<shot>/<operation_id>/` |
| `render` | `renders/<shot>/<operation_id>/` |
| `export` | `exports/<shot>/<operation_id>/` |
| `read` and others | `reviews/<shot>/<operation_id>/` |

An already occupied destination triggers `SCENE_CONFLICT` instead of an overwrite. Version numbers
are allocated sequentially from the `vNNN` folders actually present.

## Journal and state

`state/journal.jsonl` is append-only, each line being written then flushed to disk. Sensitive keys
are masked before writing. `state/state.json` is a regenerable projection of it: tasks, idempotency
registry, published artifacts, plans, corrupted lines.

State files are written through a temporary file in the same folder followed by an `os.replace`.
`os.replace` is atomic in practice on a single NTFS volume, without a formal guarantee: the journal
remains the source of truth.

## Path safety

`core/paths.py` is the only entry point for any path coming from outside. Explicit refusals: an
empty string or one with leading or trailing spaces, a UNC path, forbidden characters, a `..`
segment, a target outside the root after link resolution, a reparse point (symbolic link or Windows
junction) anywhere between the root and the target, or a path matching a protected pattern.

The root is normalised with `realpath` and the comparison is case-insensitive, in line with the
Windows file system. External commands are always built as argument lists, never by concatenation
inside a shell.

Full details in `docs/security.md`.

## Concurrency

One writer per project, guaranteed by `filelock`. A live task additionally takes the
`blender-instance` lock, so two live operations can never drive the same open session at once. The
Blender worker is identified by its PID **and** by a task marker present in its command line: `task cancel` kills only that precise process, never
every `blender.exe`. Some Blender computations are not immediately interruptible; the timeout kills
the worker and leaves the task in `unknown`.

In `--background` mode, `bpy.app.timers` never fires: the runtime executes strictly synchronously.
No operation may rely on an event loop.
