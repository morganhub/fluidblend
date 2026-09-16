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
| `--dry-run` | forces `dry_run: true`: plan recorded, task left `planned`, no write |
| `--json` | structured output |

```powershell
fluidblend run --project . --operation requests/scene-build.json
fluidblend run --project . --operation requests/scene-build.json --dry-run
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

Generating the configuration does not make live mode operational: the add-on must be installed and a
**GUI** Blender session must be open. Only scene **reading** is exercised (acceptance A03); live
writing belongs to lot 2 (`docs/roadmap.md`).

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
