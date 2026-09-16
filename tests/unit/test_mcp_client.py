from __future__ import annotations

import sys
from pathlib import Path

from fluidblend.adapters.mcp_client import DIAGNOSTIC_PROMPT, probe_server

FAKE = Path(__file__).with_name("fake_mcp_server.py")


def test_probe_lists_tools_and_reads_scene_info_only():
    report = probe_server(sys.executable, [str(FAKE)], None, startup_timeout_s=30, call_timeout_s=30)
    assert report["errors"] == [], report
    assert "get_scene_info" in report["tools"] and "execute_blender_code" in report["tools"]
    assert report["scene_info"]["is_error"] is False and "FakeScene" in report["scene_info"]["text"]
    assert report["scene_info"]["arguments"] == {"user_prompt": DIAGNOSTIC_PROMPT}
    assert report["tool_schemas"]["get_scene_info"] == ["user_prompt"]


def test_probe_reports_launch_failure_instead_of_raising():
    report = probe_server(
        sys.executable, ["-c", "import sys; sys.exit(3)"], None, startup_timeout_s=5, call_timeout_s=5
    )
    assert report["tools"] == [] and report["errors"]
