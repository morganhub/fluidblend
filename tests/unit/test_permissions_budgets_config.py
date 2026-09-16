from __future__ import annotations

import json
import tomllib

from fluidblend.adapters import client_config
from fluidblend.contracts.operations import OPERATIONS
from fluidblend.contracts.project import Budgets, Permissions
from fluidblend.core.budgets import check_budget
from fluidblend.core.permissions import operation_allowed


def test_inspect_profile_is_read_only():
    perms = Permissions(profile="inspect")
    assert operation_allowed(perms, OPERATIONS["scene.inspect"])[0]
    allowed, reason = operation_allowed(perms, OPERATIONS["scene.build"])
    assert not allowed and "read-only" in reason


def test_allowed_operations_patterns():
    perms = Permissions(profile="assisted", allowed_operations=["scene.*", "shot.preview"])
    assert operation_allowed(perms, OPERATIONS["scene.build"])[0]
    assert operation_allowed(perms, OPERATIONS["shot.preview"])[0]
    assert not operation_allowed(perms, OPERATIONS["game.export"])[0]


def test_budget_checks():
    budgets = Budgets(max_task_minutes=1, max_preview_frames=10, max_new_disk_gib=0.01)
    errors = check_budget(budgets, {"frames": 240, "seconds": 500, "disk_mib": 100})
    codes = {e.details.get("frames") is not None for e in errors}
    assert len(errors) == 3 and all(e.code == "BUDGET_EXCEEDED" for e in errors) and codes
    assert check_budget(budgets, {"frames": 5, "seconds": 10, "disk_mib": 1}) == []


def test_claude_mcp_json_merge_keeps_other_servers():
    existing = {"mcpServers": {"other": {"type": "http", "url": "http://localhost:1"}}}
    entry = client_config.mcp_server_entry(port=9877)
    merged = client_config.claude_mcp_json(existing, "blender", entry)
    assert set(merged["mcpServers"]) == {"other", "blender"}
    blender = merged["mcpServers"]["blender"]
    assert (
        blender["type"] == "stdio"
        and blender["command"] == "uvx"
        and "--port" in blender["args"]
        and "9877" in blender["args"]
    )
    assert blender["env"]["BLENDER_MCP_SAFE_MODE"] == "1" and blender["env"]["DISABLE_TELEMETRY"] == "true"
    json.loads(json.dumps(merged))


def test_codex_toml_merge_is_valid_and_replaces_existing():
    existing = 'model = "gpt-x"\n\n[mcp_servers.other]\ncommand = "C:\\\\tools\\\\other.exe"\nargs = []\n\n[mcp_servers.blender]\ncommand = "old"\nargs = []\n\n[mcp_servers.blender.env]\nX = "1"\n\n[desktop]\nfoo = true\n'
    entry = client_config.mcp_server_entry(port=9876)
    text = client_config.merge_codex_toml(existing, "blender", entry)
    data = tomllib.loads(text)
    assert data["model"] == "gpt-x" and data["desktop"]["foo"] is True
    assert data["mcp_servers"]["other"]["command"] == "C:\\tools\\other.exe"
    assert data["mcp_servers"]["blender"]["command"] == "uvx"
    assert data["mcp_servers"]["blender"]["env"]["BLENDER_MCP_SAFE_MODE"] == "1"
    assert "X" not in data["mcp_servers"]["blender"]["env"]
    assert text.count("[mcp_servers.blender]") == 1


def test_vscode_mcp_json_uses_servers_key():
    merged = client_config.vscode_mcp_json(
        {"servers": {"a": {"type": "stdio", "command": "x"}}}, "blender", client_config.mcp_server_entry()
    )
    assert set(merged["servers"]) == {"a", "blender"} and "mcpServers" not in merged


def test_windows_path_survives_toml_roundtrip():
    entry = {"command": "C:\\Users\\Éric\\.local\\bin\\uvx.exe", "args": ["mcp-for-blender"], "env": {}}
    data = tomllib.loads(client_config.codex_toml_section("blender", entry))
    assert data["mcp_servers"]["blender"]["command"] == "C:\\Users\\Éric\\.local\\bin\\uvx.exe"
