"""MCP sidecar: fastapi_db_slow_queries — thin wrapper over operate_db.find_slow_queries."""
from __future__ import annotations

from modules.database.tools.operate_db import find_slow_queries


MCP_TOOL = {
    "name": "fastapi_db_slow_queries",
    "description": "Find slow queries from pg_stat_statements. Requires pg_stat_statements extension.",
    "tags": ["database", "operate"],
    "entry": "entry",
    "annotations": {"readOnlyHint": True},
}


def entry(db_url: str, min_duration_ms: float = 100) -> list[dict]:
    """Find slow queries from pg_stat_statements. Requires pg_stat_statements extension."""
    return find_slow_queries(db_url, min_duration_ms=min_duration_ms)
