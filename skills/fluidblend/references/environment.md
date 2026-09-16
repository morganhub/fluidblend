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

## Live MCP mode

**Reading proven, writing not implemented.** Acceptance scenario A03 passes: tools listed and
`get_scene_info` read without mutation on a GUI Blender session. Modifying an open session belongs
to lot 2: never announce it and never improvise it; everything goes through batch mode.

Component installed here on approval: MCP for Blender add-on 1.7 (protocol 7, PyPI package
`mcp-for-blender` 2.0.0, MIT), which exposes a TCP socket on `localhost:9876`. Points to know:

- the socket is **not authenticated**: never expose it outside the workstation;
- the add-on refuses to start under `blender --background`: live mode assumes an open GUI session;
- it **starts its server by itself** when a GUI session loads: any Blender opened with the add-on
  enabled is already listening on 9876;
- without a GUI session, `doctor --live` leaves `blender.mcp_live` as `unverified`: that is the
  expected result, not a failure;
- safe mode through `BLENDER_MCP_SAFE_MODE=1` (script filtering, not a sandbox);
- telemetry disabled through `DISABLE_TELEMETRY=true`;
- installing the add-on (`uvx --python 3.11 mcp-for-blender install-addon`) is a user decision; the
  one on the reference workstation was explicitly approved.

Generating the client configuration, without installing anything:

```powershell
fluidblend client-config --client claude --write .mcp.json      # mcpServers, stdio type
fluidblend client-config --client codex  --write config.toml    # [mcp_servers.blender] merged in
fluidblend client-config --client vscode --write .vscode/mcp.json
fluidblend client-config --client claude                        # prints without writing
```

Options: `--name` (default `blender`), `--host`, `--port` (default 9876), `--no-safe-mode`. The
merge preserves the other servers already declared. `scripts/install-skill.ps1 -WithMcp` calls this
command for `.mcp.json`.

The programmatic MCP client (`adapters/mcp_client.py`, `mcp` SDK 1.30) is **read-only**: paginated
`list_tools`, then `get_scene_info` if it is advertised. It reads each tool's `inputSchema` and fills
in the required string arguments — the real server requires `user_prompt` on almost every tool,
filled with an explicit diagnostic text. Tested against a fake server
(`tests/unit/test_mcp_client.py`) and against the real server in A03.

## External providers

`config/providers.json` is empty in the scaffold and no provider is enabled in P0
(`max_external_spend = 0`). A provider never references a secret, only the **name** of an
environment variable (`secret_ref`). Enabling a provider, allowing the network (`allow_network`) or
committing to a spend are user decisions, outside the skill's scope.

## Tools on the reference workstation

All `available` as of 2026-09-16: Blender 5.2.2, FFmpeg and ffprobe 8.0.1, glTF-Validator
2.0.0-dev.3.10, Godot 4.7.2 stable, Rhubarb 1.14.0, MCP for Blender add-on 1.7. What this does
**not** mean: Godot and Rhubarb are only detected, no kit operation calls them (the `game` profile is
untested, `lipsync.*` is not implemented).

On a workstation where a tool is missing, say so instead of working around it: without
`gltf_validator` the `khronos_validation` metric is `not_run` and A10 becomes partial again; without
the MCP add-on or without a GUI session, A03 is `not_run`.

Installation proposals (to be approved, never run unprompted): see `scripts/bootstrap.ps1`, which
lists every missing capability with its install command.
