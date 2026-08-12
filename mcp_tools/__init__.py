"""MCP server package -- auto-discovers tools from adapt/ and generators/."""

from mcp_tools.discovery import discover_and_register
from mcp_tools.server import mcp

__all__ = ["mcp", "discover_and_register"]
