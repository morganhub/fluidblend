"""Live mode without Blender: runtime install/status, MCP reply parsing, identity checks, server config."""

from __future__ import annotations

import json
from pathlib import Path

from fluidblend import __version__
from fluidblend.adapters import blender_live
from fluidblend.core import runtime_install
from fluidblend.core.project import load_project


def test_runtime_install_is_idempotent_and_hash_checked(tmp_path: Path):
    addons = tmp_path / "addons"
    first = runtime_install.install_runtime(addons)
    assert first["action"] == "installed" and first["installed"] and first["up_to_date"]
    manifest = json.loads(
        (addons / "fluidblend_runtime" / "RUNTIME_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == __version__ and manifest["hash"] == first["kit_hash"]
    assert (addons / "fluidblend_runtime" / "addon.py").exists()
    assert not list((addons / "fluidblend_runtime").rglob("__pycache__"))
    second = runtime_install.install_runtime(addons)
    assert second["action"] == "up_to_date"
    (addons / "fluidblend_runtime" / "addon.py").write_text("# tampered\n", encoding="utf-8")
    status = runtime_install.runtime_status(addons)
    assert status["installed"] and not status["up_to_date"]
    third = runtime_install.install_runtime(addons)
    assert third["action"] == "replaced" and third["up_to_date"]
    assert (
        runtime_install.uninstall_runtime(addons) and not runtime_install.runtime_status(addons)["installed"]
    )


def test_tree_hash_ignores_line_endings(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    for folder, eol in ((a, "\n"), (b, "\r\n")):
        (folder / "pkg").mkdir(parents=True)
        (folder / "pkg" / "x.py").write_bytes(f"print(1){eol}print(2){eol}".encode())
    assert runtime_install.runtime_tree_hash(a) == runtime_install.runtime_tree_hash(b)


def test_parse_tool_text_and_markers():
    ok, payload = blender_live.parse_tool_text(
        'Code executed successfully: FLUIDBLEND_IDENTITY={"project_id": "demo"}\n'
    )
    assert ok and blender_live.extract_marker(payload, "FLUIDBLEND_IDENTITY=") == {"project_id": "demo"}
    ok, payload = blender_live.parse_tool_text(
        'Error executing code: AttributeError: Calling operator "bpy.ops.fluidblend.identity" error'
    )
    assert not ok and "AttributeError" in payload
    assert blender_live.extract_marker("no marker here", "FLUIDBLEND_IDENTITY=") is None


def test_check_identity_reports_every_mismatch(tmp_path: Path):
    blend = tmp_path / "shots" / "shot010" / "work" / "v001" / "shot010.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"x")
    good = {
        "runtime_version": __version__,
        "project_id": "demo-studio",
        "blend_path": str(blend),
        "is_dirty": False,
    }
    assert (
        blender_live.check_identity(
            good, project_id="demo-studio", expected_blend=blend, runtime_version=__version__
        )
        == []
    )
    bad = {
        "runtime_version": "0.0.1",
        "project_id": "other",
        "blend_path": str(tmp_path / "elsewhere.blend"),
        "is_dirty": True,
    }
    problems = blender_live.check_identity(
        bad, project_id="demo-studio", expected_blend=blend, runtime_version=__version__
    )
    assert len(problems) == 4 and any("unsaved" in p for p in problems)
    unsaved = {"runtime_version": __version__, "project_id": None, "blend_path": "", "is_dirty": True}
    assert any(
        "no saved file" in p
        for p in blender_live.check_identity(
            unsaved, project_id="demo-studio", expected_blend=blend, runtime_version=__version__
        )
    )


def test_server_config_prefers_project_mcp_json(project_root: Path):
    project = load_project(project_root)
    generated = blender_live.server_config_for(project)
    assert generated.command == "uvx" and generated.source == "generated" and "--port" in generated.args
    (project_root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "blender": {
                        "type": "stdio",
                        "command": "C:\\tools\\uvx.exe",
                        "args": ["mcp-for-blender", "--port", "9999"],
                        "env": {"BLENDER_PORT": "9999"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = blender_live.server_config_for(project)
    assert (
        config.command == "C:\\tools\\uvx.exe"
        and config.args[-1] == "9999"
        and config.env["BLENDER_PORT"] == "9999"
    )
    assert config.call_timeout_s == project.local.mcp.call_timeout_s
