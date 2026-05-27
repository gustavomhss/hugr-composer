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

import os  # noqa: E402

from mcp_tools.server import mcp  # noqa: E402
from mcp_tools.discovery import discover_and_register  # noqa: E402
from mcp_tools.auth_gate import gate_enabled  # noqa: E402

discover_and_register(mcp)

# Entry point for `python mcp_server.py` or `fastmcp run mcp_server.py:mcp`
if __name__ == "__main__":
    if gate_enabled():
        # Hosted mode: serve over HTTP so clients send their HuGR license as a
        # bearer token; the HugrTokenVerifier (wired in mcp_tools/server.py)
        # rejects anyone without an active subscription. Tool code stays on the
        # HuGR host, never on the client's disk.
        mcp.run(
            transport="http",
            host=os.getenv("HUGR_MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("HUGR_MCP_PORT", "8080")),
        )
    else:
        # Local/dev/OSS: stdio, no auth.
        mcp.run()
