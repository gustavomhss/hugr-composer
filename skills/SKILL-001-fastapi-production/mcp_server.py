"""SKILL-001: FastAPI Production -- MCP Server v5 (auto-discovery)

Run:
    fastmcp run mcp_server.py:mcp
    fastmcp dev mcp_server.py:mcp
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).parent
sys.path.insert(0, str(SKILL_ROOT))

from mcp_tools.server import mcp  # noqa: E402
from mcp_tools.discovery import discover_and_register  # noqa: E402

discover_and_register(mcp)

# Entry point for `python mcp_server.py` or `fastmcp run mcp_server.py:mcp`
if __name__ == "__main__":
    mcp.run()
