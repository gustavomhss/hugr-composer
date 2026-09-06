"""HuGR Composer CLI entry point."""

from __future__ import annotations

def main() -> None:
    """Run the HuGR Composer MCP server."""
    from mcp_tools.server import mcp
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
