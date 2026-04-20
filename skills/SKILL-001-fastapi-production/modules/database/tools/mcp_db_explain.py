"""MCP sidecar: fastapi_db_explain — thin wrapper over operate_db.analyze_query."""
from __future__ import annotations

from modules.database.tools.operate_db import analyze_query


MCP_TOOL = {
    "name": "fastapi_db_explain",
    "description": "Run EXPLAIN ANALYZE on a query and interpret the execution plan.",
    "tags": ["database", "operate"],
    "entry": "entry",
    "annotations": {"readOnlyHint": True},
}


def entry(db_url: str, sql: str) -> dict:
    """Run EXPLAIN ANALYZE on a query and interpret the execution plan."""
    return analyze_query(db_url, sql)
