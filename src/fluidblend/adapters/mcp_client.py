"""Programmatic MCP client (`mcp` SDK 1.x) used to probe a configured server (acceptance A03).

Harmless reads only: `list_tools` (paginated) then `get_scene_info` if it is advertised.
No writes, no assumption about tool names.
"""

from __future__ import annotations

import asyncio
from typing import Any

DIAGNOSTIC_PROMPT = "fluidblend diagnostic: read-only scene inspection, no modification"


def _arguments_for(schema: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Build the required arguments of a tool from its inputSchema (strings only).

    `mcp-for-blender` for instance requires `user_prompt` on almost every tool; it is filled with an
    explicit diagnostic text. Any other required type makes the call impossible to synthesize.
    """
    properties = schema.get("properties") or {}
    arguments: dict[str, Any] = {}
    unsupported: list[str] = []
    for name in schema.get("required") or []:
        kind = (properties.get(name) or {}).get("type")
        if kind == "string" or kind is None:
            arguments[name] = DIAGNOSTIC_PROMPT
        else:
            unsupported.append(f"{name}:{kind}")
    return arguments, unsupported


async def _probe_async(
    command: str,
    args: list[str],
    env: dict[str, str] | None,
    *,
    startup_timeout_s: float,
    call_timeout_s: float,
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args, env=env)
    report: dict[str, Any] = {"command": command, "args": args, "tools": [], "scene_info": None, "errors": []}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=startup_timeout_s)
            server = getattr(init, "serverInfo", None)
            report["server"] = {
                "name": getattr(server, "name", None),
                "version": getattr(server, "version", None),
            }
            cursor = None
            schemas: dict[str, dict[str, Any]] = {}
            while True:
                page = await asyncio.wait_for(session.list_tools(cursor=cursor), timeout=call_timeout_s)
                for tool in page.tools:
                    report["tools"].append(tool.name)
                    schemas[tool.name] = getattr(tool, "inputSchema", None) or {}
                cursor = getattr(page, "nextCursor", None)
                if not cursor:
                    break
            report["tool_schemas"] = {
                name: sorted(schema.get("required") or []) for name, schema in schemas.items()
            }
            if "get_scene_info" in schemas:
                arguments, unsupported = _arguments_for(schemas["get_scene_info"])
                if unsupported:
                    report["scene_info"] = {
                        "is_error": True,
                        "text": f"required arguments cannot be synthesized: {unsupported}",
                    }
                else:
                    result = await asyncio.wait_for(
                        session.call_tool("get_scene_info", arguments), timeout=call_timeout_s
                    )
                    texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
                    report["scene_info"] = {
                        "is_error": bool(result.isError),
                        "arguments": arguments,
                        "text": "\n".join(texts)[:4000],
                    }
    return report


def probe_server(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    *,
    startup_timeout_s: float = 20.0,
    call_timeout_s: float = 60.0,
) -> dict[str, Any]:
    try:
        return asyncio.run(
            _probe_async(
                command, args, env, startup_timeout_s=startup_timeout_s, call_timeout_s=call_timeout_s
            )
        )
    except Exception as exc:  # noqa: BLE001 - the diagnostic must report any cause, not crash
        return {
            "command": command,
            "args": args,
            "tools": [],
            "scene_info": None,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
