# `fluidblend` CLI

The single entry point of the engine. Every subcommand validates its arguments, writes
human-readable output by default or JSON with `--json`, and returns a documented exit code.

```powershell
uv run --project <kit> fluidblend <subcommand> [options]
.\skills\fluidblend\scripts\fluidblend.ps1 <subcommand> [options]
fluidblend --version
fluidblend --help          # the help text recalls the exit codes
```

The PowerShell wrapper resolves the kit root in this order: `$env:FLUIDBLEND_HOME`, the
`kit-path.txt` written by `scripts/install-skill.ps1`, then walking up to a `pyproject.toml`
accompanied by `blender_runtime/`. It exits with 2 if the kit or `uv` cannot be found.

## Exit codes

| Code | Name | Meaning |
| --- | --- | --- |
| 0 | `OK` | success, dry run, or idempotent re-read |
| 1 | `FAILED` | known failure, partial effects listed in `state/tasks/<task_id>/` |
| 2 | `BLOCKED` | missing permission, dependency or capability, a user decision is expected |
| 3 | `CONFLICT` | revision conflict, lock held, `operation_id` reused with different parameters |
| 4 | `INVALID` | invalid request or arguments, nothing was executed |
| 5 | `UNKNOWN_STATE` | uncertain write state, `fluidblend task reconcile` is mandatory |
| 6 | `BUDGET_EXCEEDED` | time, frame or disk budget exceeded, stopped before execution |

A keyboard interrupt (Ctrl+C) returns 5: the write state is uncertain by principle.

## `doctor`

Diagnostic of the machine and its capabilities. Read-only with respect to the sources.

| Option | Effect |
| --- | --- |
| `--project PATH` | optional; writes `<project>/state/diagnostics/capabilities.json` and updates the project's `dependencies.lock.json` |
| `--no-probe` | does not launch Blender; capabilities become `unverified` |
| `--live` | probes the configured MCP server (`list_tools` then `get_scene_info`); without `--project`, the `.mcp.json` of the current folder is read |
| `--write-lock PATH` | writes a `dependencies.lock.json` from the observed capabilities |
| `--json` | structured output |

```powershell
fluidblend doctor --project "D:\Projects\My Film" --json
fluidblend doctor --write-lock dependencies.lock.json
```

Exit: 0 in every case. A project whose `project.json` cannot be read gives 4.

## `init`

Creates or completes a project. Idempotent, never replaces an existing file.

| Option | Default | Effect |
| --- | --- | --- |
| `--path PATH` | required | project root |
| `--profile` | `film` | `film`, `game`, `hybrid` |
| `--project-id` | derived from the folder | lowercase letters, digits, `.`, `_`, `-` |
| `--name` | `project_id` | display name |
| `--game-engine` | `none` | `godot`, `web`, `none` (forced to `none` in the `film` profile) |
| `--dry-run` | — | writes nothing |
| `--strict` | — | exits with 3 if conflicts are detected |
| `--json` | — | structured output |

```powershell
fluidblend init --path "D:\Projects\My Film" --profile film --project-id my-film --dry-run
```

Exit: 0, or 3 with `--strict` and at least one conflict, or 4 if `project_id` or the path is
invalid. The report lists `created_dirs`, `created_files`, `identical`, `conflicts` (with both
sha256 values and `action: kept_existing`) and `first_init`.

## `inspect`

Manifests, shot plans, work versions, revisions, tasks, checkpoints, journal counters.

```powershell
fluidblend inspect --project . --json
```

Exit: 0, or 4 if the project cannot be found or is invalid.

## `plan`

Plans a request without mutation. Writes `state/plans/<operation_id>.json` and journals the event.

```powershell
fluidblend plan --project . --request requests/shot010-preview.json --json
```

`--request` accepts a path relative to the project or an absolute one. Exit: 0, 2 if the plan
contains blocking errors (unavailable operation, missing permission, budget exceeded), 4 if the
request is invalid.

## `run`

Executes a typed operation.

| Option | Effect |
| --- | --- |
| `--operation PATH` | JSON request file, relative to the project or absolute |
| `--mode batch\|live` | `batch` (default): a dedicated headless Blender process. `live`: the open Blender session, through MCP |
| `--dry-run` | forces `dry_run: true`: plan recorded, task left `planned`, no write |
| `--json` | structured output |

```powershell
fluidblend run --project . --operation requests/scene-build.json
fluidblend run --project . --operation requests/scene-build.json --dry-run
fluidblend run --mode live --project . --operation requests/animation-retime.json
```

Exit: the code matches the result of the operation (0 to 6). The human-readable output lists the
status, the task identifier, the published artifacts, the warnings, the errors with their code and
recovery guidance, and the new revision where applicable.

Operations executable through `run` in this lot — 10 of the 19 available: `scene.build`,
`scene.inspect`, `scene.audit`, `animation.retime`, `shot.preview`, `game.export` (Blender backend);
`scene.checkpoint`, `shot.validate`, `film.assemble`, `providers.check` (host backend).

The other available operations are invoked through a dedicated subcommand, not through `run`:

| Operation | Subcommand |
| --- | --- |
| `environment.doctor` | `doctor` |
| `capabilities.list` | `capabilities` |
| `project.init` | `init` |
| `project.inspect` | `inspect` |
| `project.plan` | `plan` |
| `project.resume` | `resume` |
| `task.status`, `task.cancel`, `task.reconcile` | `task status`, `task cancel`, `task reconcile` |
| `providers.check` | no subcommand: runs through `fluidblend run` (request `{"operation": "providers.check", ...}`); reads `config/providers.json`, makes no network call, report in `reviews/project/<operation_id>/providers-check.json` |

A `run` request targeting an operation that has a dedicated subcommand (`environment.doctor`,
`project.*`, `task.*`, `capabilities.list`) is refused with `VALIDATION_FAILED` (exit 4), the
subcommand to use being given in `recovery`.

### `--mode live`

Four operations run inside the Blender session the user has open: `scene.inspect`, `scene.audit`,
`animation.retime` and `scene.checkpoint`. Any other operation passed with `--mode live` runs in
batch as usual, on the published work version; the runtime refuses `scene.build`, `shot.preview` and
`game.export` inside a live envelope with `UNSUPPORTED_CAPABILITY`.

Prerequisites: Blender 5.2 open **in its graphical interface** with the MCP add-on server listening,
and the kit's runtime installed and enabled (`fluidblend runtime install --enable`). Check both with
`fluidblend live status --project .`.

Before executing anything, the engine reads the session's identity and compares it with the request:

| Checked | Failure |
| --- | --- |
| runtime version equal to the kit version | `SCENE_CONFLICT` (exit 3) |
| `project_id` of the open scene equal to the project | `SCENE_CONFLICT` (exit 3) |
| open file equal to the shot's latest work version (real path) | `SCENE_CONFLICT` (exit 3) |
| no unsaved change in the session | `SCENE_CONFLICT` (exit 3) — except `scene.checkpoint`, which snapshots them on purpose |
| runtime add-on reachable through MCP | `UNSUPPORTED_CAPABILITY` (exit 2) |
| MCP server reachable | `MISSING_DEPENDENCY` (exit 2) |

Nothing is executed when a check fails, so an edit in progress is never lost. A live task holds the
`blender-instance` lock in addition to the project lock, and its task record carries `mode: live`.

A live write is never saved over the open file: `animation.retime` saves a copy, the engine
publishes it as the next work version, records the revision and then reloads the session on that
published file. If the reload fails, the result carries a warning: reopen the file in Blender before
saving anything, otherwise the previous version would be overwritten.

If the call exceeds `mcp.call_timeout_s` (`config/local.json`, 60 s by default), the task is left
`unknown` (exit 5) because the open scene may have been modified: run `fluidblend task reconcile`,
then reopen the latest work version in Blender before retrying.

## `task`

```powershell
fluidblend task list      --project . --json
fluidblend task status    --project . --id task-xxxx --json
fluidblend task cancel    --project . --id task-xxxx
fluidblend task reconcile --project . --id task-xxxx
```

`status` adds the tail of `blender.stderr.log` and checks whether the worker is alive. `cancel`
stops only the process carrying the task marker and `blender` in its command line. `reconcile`
inspects the task folder and settles a terminal state without re-running anything.

Exit: 0, or 4 if the project or the task cannot be found. The verdict is read from the JSON, not
from the exit code.

## `validate`

Technical validation of a shot (`shot.validate`). Modifies nothing.

| Option | Effect |
| --- | --- |
| `--target SHOT_ID` | required |
| `--no-preview` | does not require a published preview |

```powershell
fluidblend validate --project . --target shot010
```

Exit: 0 if `technical_pass` is true, 1 if it is false, or the operation's code if it failed before
the checks. `technical_pass` is not an artistic approval.

## `resume`

Rebuilds the state from the journal, writes `state/resume-report.json` and lists what can be
resumed.

```powershell
fluidblend resume --project . --json
```

Exit: **5 if unfinished tasks remain**, 0 otherwise. The report contains the exact
`fluidblend task reconcile` commands to run.

## `revision`

```powershell
fluidblend revision list   --project . --json
fluidblend revision accept --project . --target shot010
```

`accept` records a detected manual modification: the revision is incremented with
`origin: external_accepted` and the user's file is kept as is. Exit: 0, or 4 if the target has no
recorded revision.

## `ops`

```powershell
fluidblend ops              # available operations
fluidblend ops --all --json # full catalogue, including P1/P2
```

Each line gives the name, the backend (`host` or `blender`), the class (`read`, `write`, `render`,
`export`), the lot (`P0`, `P1`, `P2`), the availability and the description. Exit: 0.

## `schema`

```powershell
fluidblend schema export --out schemas
fluidblend schema check  --out schemas
```

Exports or verifies the JSON Schema files generated from the pydantic models. `check` exits with 1
if any schema is out of date, 0 otherwise.

## `client-config`

Generates or merges a client's MCP configuration. Installs nothing.

| Option | Default | Effect |
| --- | --- | --- |
| `--client` | required | `claude` (`mcpServers`), `codex` (`[mcp_servers.<name>]`), `vscode` (`servers`) |
| `--name` | `blender` | server name |
| `--host` | `localhost` | host of the add-on socket |
| `--port` | 9876 | socket port |
| `--no-safe-mode` | — | removes `BLENDER_MCP_SAFE_MODE=1` (not recommended) |
| `--write PATH` | — | creates or merges the file; otherwise prints to standard output |

```powershell
fluidblend client-config --client claude --write .mcp.json
fluidblend client-config --client codex  --write "$env:USERPROFILE\.codex\config.toml"
```

The generated entry launches `uvx mcp-for-blender --host <host> --port <port>` with
`BLENDER_MCP_SAFE_MODE=1` and `DISABLE_TELEMETRY=true`. Merging preserves the other servers. The
TOML produced is re-validated after the merge. Exit: 0.

Generating the configuration does not make live mode operational: the MCP add-on must be installed,
a **GUI** Blender session must be open, and the kit's runtime must be installed and enabled
(`fluidblend runtime install --enable`). The `--name` given here must match `mcp.server_name` in
`config/local.json`, which is how the engine finds the server entry in the project's `.mcp.json`.

## `runtime`

Installs or checks the kit's runtime as a Blender add-on. Live mode needs it; batch mode does not
(the batch worker imports the runtime straight from the kit).

```powershell
fluidblend runtime install --enable          # copy into the Blender add-ons dir, then enable it
fluidblend runtime install --force --json    # reinstall even when the hash already matches
fluidblend runtime status --json
```

| Option | Effect |
| --- | --- |
| `install --enable` | also enables the add-on in the Blender user preferences, headlessly (`addon_enable` then `save_userpref`) |
| `install --force` | copies again even if the installed tree is already up to date |
| `--json` | structured output |

The package is copied to
`%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\fluidblend_runtime\` (override the
add-ons directory with `FLUIDBLEND_BLENDER_ADDONS_DIR`) with a `RUNTIME_MANIFEST.json` holding the
version, the hash of the runtime's Python tree, its source and the installation time. The install is
idempotent: an identical tree reports `action: up_to_date`.

Exit codes: `install` returns 0, 2 when no Blender 5.2 was found to enable the add-on, 1 when the
enable step itself failed. `status` returns 0 when the add-on is installed and up to date, **2**
when it is missing or when its hash differs from the kit's (reinstall after any kit update).

## `live`

```powershell
fluidblend live status --project . --json
```

Reads the identity of the open Blender session through the runtime add-on: open file, `project_id`,
`shot_id`, revision, dirty flag, runtime and Blender versions, the server entry that was used, and
the list of operations available in live mode. It modifies nothing.

Exit: 0 when the session answers, **2** when it is unreachable — no GUI session, MCP server down,
add-on not enabled — with the failure kind (`unreachable`, `timeout`, `tool_missing`,
`not_configured`) in the output. 4 if the project is invalid.

## `capabilities`

Displays the project's latest `state/diagnostics/capabilities.json`, without re-running the probes.

```powershell
fluidblend capabilities --project . --json
```

Exit: 0, 2 if no diagnostic has been produced yet, 4 if the project is invalid.

## Request format

```json
{
  "schema_version": "1.0",
  "operation": "animation.retime",
  "operation_id": "retime-shot010-hero-001",
  "project_id": "demo-studio",
  "target": {"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk", "expected_revision": 1},
  "parameters": {"duration_scale": 1.2, "preserve_contact_markers": true, "output_variant": "walk-slower-v001", "preview_samples": 8},
  "dry_run": false
}
```

- `schema_version` must be `"1.0"`; any other value requires an explicit migration.
- `operation` follows the `domain.operation` pattern.
- `operation_id`: 3 to 100 characters from `[A-Za-z0-9._-]`, chosen by the caller, used as the
  idempotency key.
- `project_id` must match the `project.json` of the target project.
- `target`: `shot_id`, `instance_id`, `clip_id`, `asset_id`, `expected_revision`, all optional
  depending on the operation. Scene operations require `shot_id`.
- `parameters` is validated by the operation's model; **any unknown field is refused**.
- `dry_run` can also be forced with `--dry-run`.

Five copy-ready examples are shipped in `skills/fluidblend/assets/`. The full JSON schemas are in
`schemas/` (`operation-request.json`, `operation-result.json`, `operations/`).
