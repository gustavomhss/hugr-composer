"""Auto-discovers generator tools from generators/ via MCP_TOOL metadata.

Replaces the prior 691-line hand-coded registration. Each generator module
now owns its MCP metadata; see CONTRACT.md §B1.5.
"""
from __future__ import annotations

from mcp_tools.discovery import register_generators_from_metadata


def register_generators(mcp_app) -> int:
    return register_generators_from_metadata(mcp_app)
