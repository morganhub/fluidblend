"""Live mode: drive the open Blender session through the community MCP server (§7.1–7.2).

Transport: engine → `uvx mcp-for-blender` (stdio, launched per phase) → add-on socket → Blender main
thread. The only scripts transmitted are calls to the approved runtime's operators
(`bpy.ops.fluidblend.*`), which the add-on safe mode accepts (`import bpy` only).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fluidblend.adapters import client_config
from fluidblend.core.atomic import read_json
from fluidblend.core.project import Project

EXECUTE_TOOL = "execute_blender_code"
SUCCESS_PREFIX = "Code executed successfully:"
ERROR_PREFIX = "Error executing code:"
ENGINE_PROMPT = "fluidblend engine: run an approved runtime operator on the open scene ({what})"


class LiveError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "unreachable"):
        super().__init__(message)
        self.kind = kind  # unreachable | timeout | tool_missing | script_error | not_configured


@dataclass
class LiveConfig:
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)
    startup_timeout_s: float = 20.0
    call_timeout_s: float = 60.0
    source: str = "generated"


def server_config_for(project: Project) -> LiveConfig:
    """Server entry from the project's `.mcp.json` (Claude Code project scope), else generated from config/local.json."""
    mcp = project.local.mcp
    path = project.root / ".mcp.json"
    if path.exists():
        try:
            data = read_json(path)
            entry = (data.get("mcpServers") or {}).get(mcp.server_name)
        except (OSError, ValueError):
            entry = None
        if entry and entry.get("command"):
            return LiveConfig(
                command=str(entry["command"]),
                args=[str(a) for a in entry.get("args", [])],
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                startup_timeout_s=mcp.startup_timeout_s,
                call_timeout_s=mcp.call_timeout_s,
                source=str(path),
            )
    entry = client_config.mcp_server_entry(port=mcp.port, host=mcp.host)
    return LiveConfig(
        command=entry["command"],
        args=entry["args"],
        env=entry["env"],
        startup_timeout_s=mcp.startup_timeout_s,
        call_timeout_s=mcp.call_timeout_s,
    )


def parse_tool_text(text: str) -> tuple[bool, str]:
    """Split the `execute_blender_code` reply into (ok, payload)."""
    stripped = text.strip()
    if stripped.startswith(SUCCESS_PREFIX):
        return True, stripped[len(SUCCESS_PREFIX) :].strip()
    if stripped.startswith(ERROR_PREFIX):
        return False, stripped[len(ERROR_PREFIX) :].strip()
    return False, stripped


def extract_marker(payload: str, marker: str) -> dict[str, Any] | None:
    for line in payload.splitlines():
        if line.startswith(marker):
            try:
                return json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return None
    return None


async def _call_execute(config: LiveConfig, code: str, *, what: str, timeout_s: float | None) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, **config.env}
    params = StdioServerParameters(command=config.command, args=config.args, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=config.startup_timeout_s)
            tools = await asyncio.wait_for(session.list_tools(), timeout=config.startup_timeout_s)
            names = {t.name for t in tools.tools}
            if EXECUTE_TOOL not in names:
                raise LiveError(f"the MCP server does not advertise {EXECUTE_TOOL}", kind="tool_missing")
            result = await asyncio.wait_for(
                session.call_tool(
                    EXECUTE_TOOL, {"code": code, "user_prompt": ENGINE_PROMPT.format(what=what)}
                ),
                timeout=timeout_s or config.call_timeout_s,
            )
            texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
            return "\n".join(texts)


def execute(config: LiveConfig, code: str, *, what: str, timeout_s: float | None = None) -> tuple[bool, str]:
    """Run one script through the live session; returns (ok, payload). Raises LiveError on transport failure."""
    try:
        text = asyncio.run(_call_execute(config, code, what=what, timeout_s=timeout_s))
    except LiveError:
        raise
    except BaseException as exc:  # noqa: BLE001 - classify: timeout (uncertain state) vs unreachable
        if _contains(exc, LiveError):
            raise _first(exc, LiveError) from exc
        if _contains(exc, TimeoutError):
            raise LiveError("live call timed out; the scene state is uncertain", kind="timeout") from exc
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            raise
        raise LiveError(f"live session unreachable: {type(exc).__name__}: {exc}", kind="unreachable") from exc
    return parse_tool_text(text)


def _contains(exc: BaseException, kind: type[BaseException]) -> bool:
    """True if `exc` is, wraps (ExceptionGroup) or was caused by an exception of `kind`.

    The MCP stdio client runs inside anyio task groups: a cancelled `wait_for` surfaces as an
    `ExceptionGroup` whose leaves carry the actual `TimeoutError`.
    """
    return _first(exc, kind) is not None


def _first(exc: BaseException, kind: type[BaseException]) -> BaseException | None:
    if isinstance(exc, kind):
        return exc
    for nested in getattr(exc, "exceptions", ()) or ():
        found = _first(nested, kind)
        if found is not None:
            return found
    cause = exc.__cause__ or exc.__context__
    return _first(cause, kind) if cause is not None and cause is not exc else None


def _py_string(value: str | Path) -> str:
    return json.dumps(str(value))


IDENTITY_CODE = "import bpy\nbpy.ops.fluidblend.identity()\n"


def identity(config: LiveConfig) -> dict[str, Any]:
    ok, payload = execute(config, IDENTITY_CODE, what="identity check")
    if not ok:
        if "fluidblend" in payload and ("AttributeError" in payload or "not found" in payload.lower()):
            raise LiveError(
                "fluidblend runtime add-on not enabled in the open Blender session", kind="tool_missing"
            )
        raise LiveError(f"identity call failed: {payload[:400]}", kind="script_error")
    data = extract_marker(payload, "FLUIDBLEND_IDENTITY=")
    if data is None:
        raise LiveError(f"identity marker missing in reply: {payload[:200]}", kind="script_error")
    return data


POLL_S = 0.2


def run_request(
    config: LiveConfig,
    request_path: Path,
    result_path: Path,
    *,
    what: str,
    timeout_s: float | None = None,
    on_progress: Any = None,
) -> dict[str, Any]:
    """Queue the request in the session, then wait on files: Blender's main thread stays free, so
    progress is visible and a cancellation can be acknowledged (`cancel.ack.json`)."""
    code = f"import bpy\nbpy.ops.fluidblend.start_request(request_path={_py_string(request_path)}, result_path={_py_string(result_path)})\n"
    budget = timeout_s or config.call_timeout_s
    deadline = time.monotonic() + budget
    ok, payload = execute(config, code, what=what, timeout_s=budget)
    started = extract_marker(payload, "FLUIDBLEND_STARTED=") or {}
    if not ok or not started.get("started"):
        raise LiveError(
            f"runtime call failed: {(started.get('error') or payload)[:600]}", kind="script_error"
        )
    progress_path = result_path.with_name("progress.json")
    last = None
    while time.monotonic() < deadline:
        if result_path.exists():
            return read_json(result_path)
        if on_progress is not None and progress_path.exists():
            try:
                progress = read_json(progress_path)
            except (OSError, ValueError):
                progress = None  # being replaced; next poll reads it
            if progress and progress != last:
                last = progress
                on_progress(progress)
        time.sleep(POLL_S)
    raise LiveError("live call timed out; the scene state is uncertain", kind="timeout")


def open_file(
    config: LiveConfig, blend_path: Path, *, expected_identity: dict[str, Any] | None = None
) -> dict[str, Any]:
    guard = _py_string(json.dumps(expected_identity)) if expected_identity else '""'
    code = f"import bpy\nbpy.ops.fluidblend.open_file(filepath={_py_string(blend_path)}, expected_identity={guard})\n"
    ok, payload = execute(config, code, what=f"reload {blend_path.name}")
    if not ok:
        raise LiveError(f"reload failed: {payload[:400]}", kind="script_error")
    data = extract_marker(payload, "FLUIDBLEND_OPENED=")
    return data or {"ok": False}


def mutate_for_test(config: LiveConfig, code: str) -> tuple[bool, str]:
    """Test helper: run an arbitrary (safe-mode compatible) script, e.g. to dirty the open scene."""
    return execute(config, code, what="test mutation")


def check_identity(
    identity_data: dict[str, Any], *, project_id: str, expected_blend: Path | None, runtime_version: str
) -> list[str]:
    """Return the list of mismatches between the live session and the requested target (empty = ok)."""
    problems: list[str] = []
    if identity_data.get("runtime_version") != runtime_version:
        problems.append(f"runtime version {identity_data.get('runtime_version')} != kit {runtime_version}")
    if identity_data.get("project_id") not in (project_id, None, ""):
        problems.append(
            f"open scene belongs to project {identity_data.get('project_id')!r}, expected {project_id!r}"
        )
    if expected_blend is not None:
        open_path = identity_data.get("blend_path") or ""
        if not open_path:
            problems.append("the open session has no saved file (unsaved new scene)")
        elif os.path.normcase(os.path.realpath(open_path)) != os.path.normcase(
            os.path.realpath(expected_blend)
        ):
            problems.append(f"open file {open_path} is not the latest work version {expected_blend}")
    if identity_data.get("is_dirty"):
        problems.append("the open scene has unsaved changes; save or revert them first")
    return problems
