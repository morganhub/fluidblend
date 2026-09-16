# Environment and capabilities

Status: **implemented (lot P0)**. Operations covered: `environment.doctor` (`doctor` subcommand),
`capabilities.list` (`capabilities` subcommand) and `providers.check` (through `fluidblend run`,
request with no parameters: it reads `config/providers.json`, empty by default, and makes no network
call; a provider is only `ready` when its entry is complete and the referenced secret exists in the
environment — its value is never read).

Any decision that depends on an external tool is taken after `fluidblend doctor`, never by
assumption.

## Diagnostics

```powershell
fluidblend doctor --json                          # workstation only, no project
fluidblend doctor --project . --json              # writes state/diagnostics/capabilities.json
fluidblend doctor --project . --no-probe          # without launching Blender (faster, status unverified)
fluidblend doctor --live --project .              # additionally probes the configured MCP server
fluidblend doctor --write-lock dependencies.lock.json
```

`doctor` is read-only on sources. It writes two reports and says so:
`<project>/state/diagnostics/capabilities.json` when `--project` is given, and the file passed to
`--write-lock` (versions, paths, sha256 of the executables observed). Exit code is always 0: the
diagnostic states facts, it does not judge. The caller decides whether to stop given the statuses.

Read the last report back without re-running the probes:

```powershell
fluidblend capabilities --project . --json
```

If no report exists, this command exits 2 (`BLOCKED`) with the instruction to run `doctor`.

## Capability statuses

| Status | Meaning | What to do |
| --- | --- | --- |
| `available` | probed, version read | use it |
| `not_installed` | executable not found at the end of the discovery order below | offer to install, install nothing yourself |
| `not_configured` | tool present but no configuration declared | generate the configuration, ask for approval |
| `unverified` | detected without proof of execution | do not count it as validated |
| `incompatible` | present but outside the pinned version | refuse, explain |
| `blocked` | probe attempted and refused | report the exact error |

A status other than `available` never authorizes simulating the tool or bypassing the check.

## Probed capabilities

| `capability_id` | Provider | Notes |
| --- | --- | --- |
| `blender.batch` | Blender | pinned series **5.2**; real probe (version, slots, glTF, core add-ons) |
| `video.ffmpeg` | ffmpeg | assembly of the PNG sequences |
| `video.ffprobe` | ffprobe | evidence for frames, frame rate, `pix_fmt` |
| `gltf.khronos_validator` | KhronosGroup/glTF-Validator | present on this workstation (2.0.0-dev.3.10); absent → Khronos validation is `not_run` |
| `game.godot` | Godot | detected (4.7.2 stable) but **not exercised**: no template, no engine import (lot 4) |
| `audio.rhubarb` | Rhubarb Lip Sync | detected (1.14.0) but **not exercised**: `lipsync.*` not implemented (lot 4) |
| `python.uv` | astral-sh/uv | reports a `uv` shipped by Langflow Desktop rather than a standalone one |
| `blender.mcp_addon` | mcp-for-blender (add-on) | presence of the add-on in the Blender profile (add-on 1.7 installed here) |
| `blender.mcp_live` | mcp-for-blender (server) | client configuration detected (the project's `.mcp.json`, or the current folder's without `--project`), connection probed with `--live` |
| `blender.runtime_addon` | fluidblend runtime (Blender add-on) | required by live mode only; `available`, `not_installed`, or `incompatible` when the installed hash differs from the kit's |

## Where executables are looked for

Order applied to every external tool: path declared in `config/local.json` → `PATH` → the user
tools directory `%LOCALAPPDATA%\fluidblend\tools` (variable `FLUIDBLEND_TOOLS_DIR`) → known Windows
installers. For Godot, the most recent version found wins, preferring the `_console` variant.
Details and expected locations: `docs/installation.md` §3 bis. Blender follows a distinct order,
described below.

## Pinned Blender

Required series: **5.2** (reference workstation: 5.2.2 LTS, Python 3.13.13). Discovery order:
`config/local.json` → `FLUIDBLEND_BLENDER` → Windows registry (Uninstall) → `Program Files` and
`LOCALAPPDATA` → `PATH`. The first candidate of the series wins; the others are listed in
`evidence.other_candidates` with the reason for rejection.

Command line used for every batch operation:

```
blender --background --factory-startup --offline-mode --python-exit-code 2 \
  --python blender_runtime/entrypoint.py -- request.json result.json --fluidblend-task <task_id>
```

Consequences to know about:

- `--background`: `bpy.app.timers` never fires (measured). Execution is synchronous; no operation
  can depend on an event loop.
- `--factory-startup`: no user add-on is loaded. Anything that is not part of Blender 5.2's core
  add-ons does not exist for the runtime.
- `--offline-mode`: Blender makes no network access (acceptance scenario A11).
- `--disable-autoexec` remains the default: drivers and scripts embedded in a third-party `.blend`
  do not run.
- `PYTHONPATH` is stripped from the worker environment: only the approved runtime is importable.
- The runtime refuses any session outside the 5.2 series with `UNSUPPORTED_CAPABILITY`.

If no Blender 5.2 is found, `blender` operations fail with `MISSING_DEPENDENCY` (exit 2). Fill in
`blender_executable` in `config/local.json`, then re-run `doctor`.

## Live mode

**Four operations run in the open Blender session**, since 0.2.0: `scene.inspect`, `scene.audit`,
`animation.retime`, `scene.checkpoint`. Everything else runs in batch, on the published work
version, even when `--mode live` is passed; the runtime refuses `scene.build`, `shot.preview` and
`game.export` in a live envelope with `UNSUPPORTED_CAPABILITY`.

### Installing what live mode needs

```powershell
fluidblend runtime install --enable      # copy into the Blender add-ons dir, then enable it
fluidblend runtime status --json         # exit 2 if missing or if the hash differs from the kit
```

The kit's runtime is installed as a **Blender add-on** in
`%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\fluidblend_runtime\`, with a
`RUNTIME_MANIFEST.json` (version, hash of the Python tree). Reason: the MCP add-on's safe mode only
allows `import bpy` and forbids `open()`, `bpy.utils.register_class`, `bpy.app.timers` and the
`script` / `text` / `preferences` operator families, so the only clean way in is a registered
operator. The engine therefore transmits nothing but `import bpy` followed by
`bpy.ops.fluidblend.identity()`, `bpy.ops.fluidblend.run_request(request_path=…, result_path=…)`
or `bpy.ops.fluidblend.open_file(filepath=…)` — no generated script, and **safe mode stays on**.

The add-on has no interface (`bl_info` category `System`). Re-run `runtime install --enable` after
every kit update: a version or hash mismatch makes `runtime status` and `doctor` report
`incompatible` (exit 2). Batch mode never needs it — the batch worker imports the runtime straight
from the kit.

### Checking the session

```powershell
fluidblend live status --project . --json
```

Prints the open file, `project_id`, `shot_id`, revision, dirty flag, runtime and Blender versions,
the MCP server entry used, and the four live operations. Exit 0 when the session answers, **2** when
it is unreachable (no GUI session, server down, add-on not enabled), with the failure kind
(`unreachable`, `timeout`, `tool_missing`, `not_configured`).

### Identity check and refusals

Before every live operation the engine compares the session with the request: runtime version equal
to the kit version, same `project_id`, open file equal to the shot's latest work version (compared
after `realpath`), and no unsaved change (`is_dirty`). Any mismatch gives `SCENE_CONFLICT` (exit 3)
and **nothing is executed**, so an edit in progress is never lost. Report what is open and what was
expected, then let the user save, revert or reopen: never do it for them.

`scene.checkpoint` is the single exception on the dirty flag — snapshotting unsaved work is exactly
its purpose (`save_as_mainfile(copy=True)`, `was_dirty` metric, copy recorded under `checkpoints/`).

A live write is isolated: the operation saves a copy, the engine publishes it as the next work
version, records the revision, then reloads the session on the published file. The version already
on disk is untouched. A failed reload produces a warning, not an error — tell the user to reopen the
published file before saving anything.

A live task holds the `blender-instance` lock on top of the project lock, its task record carries
`mode: live`, and the journal gains `live_identity_checked` and `live_session_reloaded`.

### Transport and known limits

- Transport: engine → `uvx --python 3.11 mcp-for-blender` (stdio, one server process per phase) ->
  the add-on's socket on `localhost:9876` → Blender's main thread. The server entry comes from the
  project's `.mcp.json`, under the name given by `config/local.json` → `mcp.server_name`; otherwise
  an equivalent entry is generated.
- The socket is **not authenticated**: never expose it outside the workstation.
- The MCP add-on refuses to start under `blender --background`: live mode assumes an open GUI
  session, and it **starts its server by itself** as soon as such a session loads.
- Beyond `mcp.call_timeout_s` (`config/local.json`, 60 s by default) the engine cannot know what the
  session did: the task is left `unknown` (exit 5). See `references/recovery.md`.
- Nothing is reported while an operation runs: the call is synchronous on Blender's main thread.
- The engine sees the session only when it calls it: identity is a snapshot, not a subscription.
- **Client-owned MCP connection**: if your client has its own Blender MCP server, use its tools for
  read-only exploration only (`get_scene_info`, `get_viewport_screenshot`, `get_object_info`). Every
  write goes through `fluidblend run --mode live`; never `execute_blender_code` with an improvised
  script — no identity check, no lock, no checkpoint, no version, no journal.
- Installing the MCP add-on (`uvx --python 3.11 mcp-for-blender install-addon`) and the kit's
  runtime add-on are user decisions; both were explicitly approved on the reference workstation.
  Component installed there: MCP for Blender add-on 1.7 (protocol 7, PyPI package `mcp-for-blender`
  2.0.0, MIT). Live mode is covered by acceptance scenarios L01 to L05.

### Generating the client configuration

Generating a configuration installs nothing:

```powershell
fluidblend client-config --client claude --write .mcp.json      # mcpServers, stdio type
fluidblend client-config --client codex  --write config.toml    # [mcp_servers.blender] merged in
fluidblend client-config --client vscode --write .vscode/mcp.json
fluidblend client-config --client claude                        # prints without writing
```

Options: `--name` (default `blender`, must match `mcp.server_name`), `--host`, `--port` (default
9876), `--no-safe-mode` (not recommended; the engine never needs it). The merge preserves the other
servers already declared. `scripts/install-skill.ps1 -WithMcp` calls this command for `.mcp.json`.
Safe mode stays on and telemetry off (`DISABLE_TELEMETRY=true`) in everything the kit generates.

The `doctor` MCP client (`adapters/mcp_client.py`, `mcp` SDK 1.30) stays **read-only**: paginated
`list_tools`, then `get_scene_info` if advertised, with the required string arguments filled from
each tool's `inputSchema` — the real server requires `user_prompt` on almost every tool. Tested
against a fake server (`tests/unit/test_mcp_client.py`) and against the real one in A03.

## External providers

`config/providers.json` is empty in the scaffold and no provider is enabled in P0
(`max_external_spend = 0`). A provider never references a secret, only the **name** of an
environment variable (`secret_ref`). Enabling a provider, allowing the network (`allow_network`) or
committing to a spend are user decisions, outside the skill's scope.

## Tools on the reference workstation

All `available` as of 2026-09-16: Blender 5.2.2, FFmpeg and ffprobe 8.0.1, glTF-Validator
2.0.0-dev.3.10, Godot 4.7.2 stable, Rhubarb 1.14.0, MCP for Blender add-on 1.7, fluidblend runtime
add-on 0.2.0. What this does
**not** mean: Godot and Rhubarb are only detected, no kit operation calls them (the `game` profile is
untested, `lipsync.*` is not implemented).

On a workstation where a tool is missing, say so instead of working around it: without
`gltf_validator` the `khronos_validation` metric is `not_run` and A10 becomes partial again; without
the MCP add-on, without the runtime add-on, without `uvx` or without a free port 9876, A03 and
L01–L05 are `not_run`.

Installation proposals (to be approved, never run unprompted): see `scripts/bootstrap.ps1`, which
lists every missing capability with its install command.
