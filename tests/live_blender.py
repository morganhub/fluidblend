"""Ephemeral Blender GUI session with the MCP for Blender add-on started (acceptance A03).

The process is created by the test, identified by its PID and stopped by the test: no other
`blender.exe` is touched. The add-on refuses `--background`, hence the temporary GUI window.
"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass

START_SERVER_EXPR = """
import bpy

def _fluidblend_start_mcp():
    # The add-on starts its server on load (blendermcp_auto_start_server); we only force a
    # start when it is not running yet, on the requested port.
    scene = bpy.context.scene
    try:
        if not scene.blendermcp_server_running:
            scene.blendermcp_port = {port}
            bpy.ops.blendermcp.start_server()
        print("FLUIDBLEND_MCP_STARTED", scene.blendermcp_port, scene.blendermcp_server_running, flush=True)
    except Exception as exc:  # noqa: BLE001
        print("FLUIDBLEND_MCP_START_ERROR", repr(exc), flush=True)
    return None

bpy.app.timers.register(_fluidblend_start_mcp, first_interval=1.5)
"""


@dataclass
class LiveBlender:
    process: subprocess.Popen
    port: int
    executable: str

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def launch_live_blender(executable: str, *, port: int = 9876, wait_s: float = 90.0) -> LiveBlender | None:
    if port_open(port):
        raise RuntimeError(f"port {port} is already in use: another Blender/MCP session is running")
    cmd = [executable, "--python-expr", START_SERVER_EXPR.format(port=port)]
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    live = LiveBlender(process=process, port=port, executable=executable)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return None
        if port_open(port):
            return live
        time.sleep(0.5)
    live.stop()
    return None
