"""MCP sidecar: fastapi_db_bloat — thin wrapper over operate_db.check_table_bloat."""
from __future__ import annotations

from modules.database.tools.operate_db import check_table_bloat

MCP_TOOL = {
    "name": "fastapi_meta_analyze_db_bloat",
    "description": "Check table bloat -- identifies tables that need VACUUM.",
    "tags": ["database", "operate"],
    "entry": "entry",
    "annotations": {"readOnlyHint": True},
}


def entry(db_url: str) -> list[dict]:
    """Check table bloat -- identifies tables that need VACUUM."""
    return check_table_bloat(db_url)
