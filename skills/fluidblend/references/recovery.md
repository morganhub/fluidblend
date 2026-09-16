# Recovery, conflicts and reconciliation

Status: **implemented (lot P0)**. Operations covered: `task.status`, `task.cancel`,
`task.reconcile`, `project.resume`, plus the `fluidblend revision` commands.

The rule that overrides everything else: **never repeat a write whose state is uncertain.**

## First command on an unknown project

```powershell
fluidblend resume --project . --json
```

Rebuilds the state from `state/journal.jsonl`, writes `state/resume-report.json`, lists the
unfinished tasks and the exact command to run for each of them. Exits **5 (`UNKNOWN_STATE`)** when
tasks remain to be reconciled, 0 otherwise. As long as the code is 5, run no write operation.

## Task states

| State | Meaning | Allowed follow-up |
| --- | --- | --- |
| `planned` | operation computed with no mutation (dry run) | re-run without `dry_run` |
| `queued` | authorized, waiting for resources | wait |
| `running` | real execution, worker and progress recorded | follow with `task status` |
| `validating` | outputs produced, not published yet | re-run nothing |
| `succeeded` | evidence and revision published | continue |
| `failed` | known failure, partial effects listed | fix and re-run |
| `blocked` | missing permission, dependency or choice | user decision |
| `unknown` | uncertain write state | `task reconcile` is **mandatory** before any new attempt |
| `cancelled` | confirmed stop, sources and partial outputs identified | re-run if relevant |

Each task record also carries `mode`, `batch` or `live`: read it before concluding where an
operation ran. A `live` task acted inside the Blender session the user had open.

## Follow, stop, reconcile

```powershell
fluidblend task list      --project . --json
fluidblend task status    --project . --id <task_id> --json
fluidblend task cancel    --project . --id <task_id>
fluidblend task reconcile --project . --id <task_id>
```

`task status` adds the last 1500 characters of `blender.stderr.log` and checks whether the worker is
still alive, by comparing the recorded PID against the process's actual command line.

`task cancel` **only stops the identified worker**: the process must carry both the task marker and
`blender` in its command line, otherwise nothing is stopped. Never kill every `blender.exe` on a
machine.

`task reconcile` inspects the task folder before drawing any conclusion, and re-runs nothing:

| Situation observed | Conclusion |
| --- | --- |
| state already terminal | `action: none` |
| worker still active | `action: wait` |
| publication started, all files present | task moved to `succeeded` |
| publication started, files missing | `failed`, list of missing paths |
| `result.json` present but never validated | `failed`, sources intact, re-run the operation |
| no `result.json` at all | `failed`, partial effects listed, error `TIMEOUT_UNKNOWN_STATE` |

After reconciliation, re-run **the same `operation_id` with the same parameters**: the engine will
produce a single version, with no duplicate (acceptance scenario A06).

## Uncertain state in live mode

A live operation is a single call to the open Blender session. Past `mcp.call_timeout_s`
(`config/local.json`, 60 s by default) the engine stops waiting and cannot know what the session
did: the task is left `unknown` (exit 5) and any retry of the same `operation_id` is refused until
it is reconciled. The **open scene may have been modified** — that is the difference with a batch
timeout, where only the task folder is in doubt.

Procedure, in this order (acceptance scenario L05):

1. Do not press retry, and do not save the Blender session.
2. `fluidblend task reconcile --project . --id <task_id>` — it inspects the task folder, settles a
   terminal state and re-runs nothing. A result written but never committed is reported as `failed`,
   sources intact.
3. `fluidblend live status --project .` — read what the session actually holds: open file,
   revision, dirty flag.
4. Have the user reopen the shot's latest work version in Blender (`fluidblend inspect --project .`
   gives it) and save or revert anything in progress. The identity check will refuse otherwise.
5. Re-run the same request. In live mode, a retry on a clean session publishes a single version.

If the failure happened **after** publication, the result warns that the session could not be
reloaded on the published file. Tell the user to reopen that file before saving anything: saving the
old session would overwrite the version that was just published. Nothing in the kit saves or reverts
their Blender for them.

Two journal events document what happened: `live_identity_checked` (the identity that was accepted)
and `live_session_reloaded` (the file the session was pointed at, and whether it worked).

## Idempotency

The key is `operation_id`, chosen by the caller: 3 to 100 characters `[A-Za-z0-9._-]`, stable over
time. The fingerprint compared is the canonical sha256 of `(operation, target, parameters,
expected_revision)`.

| Case | Behavior |
| --- | --- |
| same `operation_id`, same fingerprint, task `succeeded` | the published result is read back, no new version, `replayed: true`, exit 0 |
| same `operation_id`, different fingerprint | `SCENE_CONFLICT` (exit 3): use a new `operation_id` |
| same `operation_id`, task `running`, `validating`, `queued` or `unknown` | `TIMEOUT_UNKNOWN_STATE` (exit 5): reconcile first |
| published result not found | `TIMEOUT_UNKNOWN_STATE`: reconcile |

Practical consequence: to retry an operation with different parameters, change `operation_id`. To
resume exactly the same operation after an interruption, **keep** the same `operation_id`.

## Revisions and manual modifications

`state/revisions.json` records, for each target `shot:<shot_id>`, an integer revision number, the
file path, its sha256, its size and its origin (`kit`, `external_accepted`, `init`).

Before any write, the engine recomputes the hash of the source:

| Cause | Code | What to do |
| --- | --- | --- |
| `external_change`: hash differs from the recorded one | `SCENE_CONFLICT` | a manual modification was detected **and kept**; accept it, then re-run |
| `revision_mismatch`: `expected_revision` != current revision | `SCENE_CONFLICT` | re-read `fluidblend inspect`, fix `target.expected_revision` |
| `source_missing`: the recorded file has disappeared | `SCENE_CONFLICT` | restore from `checkpoints/` |
| `revision_unknown`: no revision for this target | `SCENE_CONFLICT` | omit `expected_revision` |

Accepting a modification made by hand in Blender:

```powershell
fluidblend revision list   --project . --json
fluidblend revision accept --project . --target shot010
```

`accept` increments the revision and records it with `origin: external_accepted`. The user's file is
**never** overwritten or recomputed. `expected_revision` must then be updated in the request,
otherwise the conflict comes back as `revision_mismatch` (acceptance scenario A07).

## Locks

One writer per project. The `state/locks/project.lock` lock is taken for every operation that
creates a task, with a 5-second wait; beyond that, the operation fails with `SCENE_CONFLICT`
(exit 3) and reports the lock owner (PID, time, subject) read from
`state/locks/project.owner.json`. Do not delete a lock file by hand: first check whether the owning
process is still running.

A live operation additionally takes `state/locks/blender-instance.lock`, so two of them can never
drive the same open session at once. A busy `blender-instance` lock produces the same
`SCENE_CONFLICT` (exit 3), with its own owner file.

## Journal and state

`state/journal.jsonl` is append-only, written line by line with `fsync`. It is the source of truth.
`state/state.json` is a reconstruction of it and can be regenerated at any time by `resume`.
Sensitive keys (`secret`, `token`, `password`, `api_key`, `authorization`) are replaced by `***`
before writing. The journal contains neither secrets nor model reasoning.

Events useful for diagnosis: `project_initialized`, `plan_created`, `task_updated`,
`checkpoint_created`, `artifact_published`, `revision_updated`, `external_change_accepted`,
`replayed`, `reconciled`, `task_cancelled`, `request_blocked`, `request_rejected`, and for live mode
`live_identity_checked` and `live_session_reloaded`. Unreadable lines
are counted (`journal_corrupt_lines` in `inspect`) without interrupting the reconstruction.

## Contents of a task folder

`state/tasks/<task_id>/` contains `request.json` (the envelope sent to Blender), `result.json`
(written by the runtime), `result.published.json` (the result kept by the engine), `out/` (outputs
before publication), `blender.stdout.log` and `blender.stderr.log`. After publication, `out/` is
empty: its contents were moved to `shots/`, `reviews/`, `renders/` or `exports/`.

It is the first place to look after an exit 1 or 5.

## Checkpoints

Every `write`-class operation copies the source into `checkpoints/<ckpt-id>/` before acting, with a
manifest (source, copy, sha256, size, label, task, timestamp). The copy is re-verified by hash. The
checkpoint identifier is returned in the result (`checkpoint_id`) and journaled.

Restoring is done by hand, knowingly: copy the checkpoint file to its destination, then run
`fluidblend revision accept` to realign the revision. There is no automatic restore command in this
lot.

In live mode, `scene.checkpoint` snapshots the **open** scene, unsaved changes included
(`save_as_mainfile(copy=True)`, `was_dirty` metric): it is the right first move when a session holds
work in progress that a refused operation would otherwise leave unprotected.

## Budgets exceeded

Exit 6 (`BUDGET_EXCEEDED`) happens **before** any execution, based on an estimate. The message states
which measure was exceeded and which `project.json` field is involved. Widening a budget is a user
decision: propose it, never modify `project.json` on your own initiative.

If the time budget is exceeded **during** execution, the worker is stopped, the task moves to
`unknown` and the operation exits 5: reconcile before any new attempt.
