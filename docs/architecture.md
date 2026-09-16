# Architecture

## Layers

| Layer | Location | Responsibility | Does not do |
| --- | --- | --- | --- |
| Skill | `skills/fluidblend/` | understand the request, choose the mode, read the right reference, drive the validations | no business logic, no computation |
| Engine | `src/fluidblend/` | contracts, planning, execution, journal, versions, budgets, resumption, CLI | never depends on `bpy` nor on a model name |
| Blender runtime | `blender_runtime/fluidblend_runtime/` | scenes, rigs, Actions, cameras, renders, exports through the Blender API | stdlib + `bpy` only, no third-party dependency |
| Adapters | `src/fluidblend/adapters/` | Blender batch, discovery of Blender and of external tools (`tool_paths`), FFmpeg, glTF-Validator, MCP client, client configuration | hide no error, invent no feature |
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
blender.exe --background --factory-startup --offline-mode
  └ blender_runtime/entrypoint.py → fluidblend_runtime/ops/*
```

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
9. **Execution** — host backend (direct call) or Blender backend (dedicated worker). The worker
   receives the full envelope: request, project root, task folders, path of the work version, shot
   manifest, frame rate, preview settings, budgets, quality thresholds, expected runtime version.
   `PYTHONPATH` is removed from its environment.
10. **Post-processing** — FFmpeg assembly and ffprobe proof for `shot.preview`, Khronos validation
    for `game.export`.
11. **Artifact verification** — every announced artifact must exist and, if it is a file, carry the
    declared sha256. Otherwise the operation fails before publication.
12. **Publication** — `out/` is moved to its final destination, the new revision is recorded for
    versioning operations, and every published artifact is journaled.

A dry run stops after step 7: a plan is recorded, the task stays `planned`, no checkpoint is created
and nothing is published.

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

Three distinct timeouts: MCP server start-up (`mcp.startup_timeout_s`), MCP call
(`mcp.call_timeout_s`) and task budget (`budgets.max_task_minutes`, which becomes the Blender
worker's timeout). `blender_startup_timeout_s` bounds the `doctor` probes.

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

One writer per project, guaranteed by `filelock`. The Blender worker is identified by its PID **and**
by a task marker present in its command line: `task cancel` kills only that precise process, never
every `blender.exe`. Some Blender computations are not immediately interruptible; the timeout kills
the worker and leaves the task in `unknown`.

In `--background` mode, `bpy.app.timers` never fires: the runtime executes strictly synchronously.
No operation may rely on an event loop.
