"""MCP configuration of the clients (Claude Code `.mcp.json`, Codex `config.toml`, VS Code `mcp.json`).

Generates an entry for `mcp-for-blender` (uvx) with safe mode on and telemetry off, merges without
overwriting the other servers, and reads the existing configurations for the diagnostic.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

MCP_PACKAGE = "mcp-for-blender"
MCP_PYTHON = "3.11"


def mcp_server_entry(
    *,
    port: int = 9876,
    host: str = "localhost",
    safe_mode: bool = True,
    telemetry: bool = False,
    python: str = MCP_PYTHON,
) -> dict[str, Any]:
    """`mcp-for-blender` server entry: `uvx --python 3.11 mcp-for-blender --host H --port P`.

    The project README recommends a uv-managed Python (3.11) rather than a conda/pyenv interpreter.
    """
    env = {"BLENDER_HOST": host, "BLENDER_PORT": str(port), "UV_PYTHON_PREFERENCE": "only-managed"}
    if safe_mode:
        env["BLENDER_MCP_SAFE_MODE"] = "1"
    if not telemetry:
        env["DISABLE_TELEMETRY"] = "true"
    args = ["--python", python, MCP_PACKAGE, "--host", host, "--port", str(port)]
    return {"command": "uvx", "args": args, "env": env}


def claude_mcp_json(existing: dict[str, Any] | None, name: str, entry: dict[str, Any]) -> dict[str, Any]:
    data = dict(existing or {})
    servers = dict(data.get("mcpServers") or {})
    servers[name] = {"type": "stdio", **entry}
    data["mcpServers"] = servers
    return data


def vscode_mcp_json(existing: dict[str, Any] | None, name: str, entry: dict[str, Any]) -> dict[str, Any]:
    data = dict(existing or {})
    servers = dict(data.get("servers") or {})
    servers[name] = {"type": "stdio", **entry}
    data["servers"] = servers
    return data


def _toml_str(value: str) -> str:
    # json.dumps produces a valid TOML basic string (escaping of \ and ").
    return json.dumps(value, ensure_ascii=False)


def codex_toml_section(name: str, entry: dict[str, Any]) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("invalid TOML server name")
    lines = [f"[mcp_servers.{name}]", f"command = {_toml_str(entry['command'])}"]
    args = ", ".join(_toml_str(a) for a in entry.get("args", []))
    lines.append(f"args = [{args}]")
    lines.append("startup_timeout_sec = 20")
    env = entry.get("env") or {}
    if env:
        lines.append("")
        lines.append(f"[mcp_servers.{name}.env]")
        for key, value in env.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise ValueError(f"invalid TOML environment key: {key}")
            lines.append(f"{key} = {_toml_str(str(value))}")
    return "\n".join(lines) + "\n"


def merge_codex_toml(existing_text: str, name: str, entry: dict[str, Any]) -> str:
    """Replace or add the `[mcp_servers.<name>]` and `[mcp_servers.<name>.env]` tables."""
    section = codex_toml_section(name, entry)
    pattern = re.compile(
        rf"(?ms)^\[mcp_servers\.{re.escape(name)}(?:\.env)?\]\s*$.*?(?=^\[|\Z)",
    )
    text = existing_text or ""
    if pattern.search(text):
        text = pattern.sub("", text)
        text = text.rstrip("\n") + "\n\n" + section
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + section
    tomllib.loads(text)  # must stay valid TOML, otherwise it raises
    return text


def parse_codex_servers(text: str) -> dict[str, dict[str, Any]]:
    data = tomllib.loads(text)
    return dict(data.get("mcp_servers") or {})


def configured_servers(*, project_root: Path | None, home: Path | None = None) -> list[dict[str, Any]]:
    """Inventory of the MCP servers configured on the client side (names and commands, never env values)."""
    home = home or Path.home()
    found: list[dict[str, Any]] = []

    def add(client: str, path: Path, servers: dict[str, Any]) -> None:
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            found.append(
                {
                    "client": client,
                    "config_path": str(path),
                    "name": name,
                    "type": cfg.get("type") or ("http" if cfg.get("url") else "stdio"),
                    "command": cfg.get("command") or cfg.get("url"),
                    "args": cfg.get("args", []),
                    "env_keys": sorted((cfg.get("env") or {}).keys()),
                }
            )

    json_sources: list[tuple[str, Path, str]] = []
    if project_root is not None:
        json_sources.append(("claude-code:project", project_root / ".mcp.json", "mcpServers"))
        json_sources.append(("vscode:project", project_root / ".vscode" / "mcp.json", "servers"))
    json_sources.append(("claude-code:user", home / ".claude.json", "mcpServers"))
    appdata = os.environ.get("APPDATA")
    if appdata:
        json_sources.append(("vscode:user", Path(appdata) / "Code" / "User" / "mcp.json", "servers"))
    for client, path, key in json_sources:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        add(client, path, data.get(key) or {})
    codex_home = Path(os.environ.get("CODEX_HOME") or (home / ".codex"))
    codex_cfg = codex_home / "config.toml"
    if codex_cfg.exists():
        try:
            add("codex", codex_cfg, parse_codex_servers(codex_cfg.read_text(encoding="utf-8")))
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return found


def blender_mcp_addon_installed(blender_version_dir: Path | None = None) -> dict[str, Any]:
    """Look for the MCP for Blender add-on/extension in the Blender user profile."""
    appdata = os.environ.get("APPDATA")
    candidates: list[Path] = []
    if blender_version_dir is not None:
        candidates.append(blender_version_dir)
    elif appdata:
        candidates.extend(sorted((Path(appdata) / "Blender Foundation" / "Blender").glob("*")))
    hits: list[str] = []
    for base in candidates:
        for sub in ("scripts/addons", "extensions/user_default", "extensions"):
            folder = base / sub
            if not folder.exists():
                continue
            for item in folder.rglob("*"):
                lowered = item.name.lower()
                if (
                    "blender_mcp" in lowered or "mcp_for_blender" in lowered or lowered == "addon.py"
                ) and item.is_file():
                    hits.append(str(item))
    return {"installed": bool(hits), "paths": hits[:10]}
