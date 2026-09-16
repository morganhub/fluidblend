"""Fake stdio MCP server (`mcp` SDK 1.x) used to test the programmatic client without Blender."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-blender")


@mcp.tool()
def get_scene_info(user_prompt: str) -> str:
    """Dummy scene summary; `user_prompt` required just like on the real server."""
    if not user_prompt:
        raise ValueError("user_prompt is required")
    return '{"name": "FakeScene", "object_count": 3, "objects": ["Cube", "Camera", "Light"]}'


@mcp.tool()
def execute_blender_code(code: str) -> str:
    """Never called by the probe: the client must only read."""
    return "should not be called"


if __name__ == "__main__":
    mcp.run()
