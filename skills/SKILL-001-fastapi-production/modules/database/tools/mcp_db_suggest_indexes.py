"""MCP sidecar: fastapi_db_suggest_indexes — thin wrapper over operate_db.suggest_indexes."""
from __future__ import annotations

from modules.database.tools.operate_db import suggest_indexes


MCP_TOOL = {
    "name": "fastapi_db_suggest_indexes",
    "description": "Suggest missing indexes based on sequential scan patterns.",
    "tags": ["database", "operate"],
    "entry": "entry",
    "annotations": {"readOnlyHint": True},
}


def entry(db_url: str) -> list[dict]:
    """Suggest missing indexes based on sequential scan patterns."""
    return suggest_indexes(db_url)
