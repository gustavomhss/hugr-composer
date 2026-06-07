"""Recipe retrieval over 'Compose with:' sections — CONTRACT §B2.2.

This module is now a thin **skill-side adapter** over the generic
``hugr_core.discovery`` engine: the ``Compose with:`` parser, BM25 ``RecipeIndex``
and dedupe live in the shared core. Everything below is THIS skill's binding —
the registry/venous paths, the process-level index singleton, the CONTRACT
§B2.2 ``limit`` cap, and the MCP tool descriptor (skill vocabulary, discovered by
the catalog scanner under the ``discovery`` scan root).

Pure retrieval — zero LLM, zero network. Deterministic.
"""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_meta_search_composition",
    "description": (
        "BM25 retrieval over compose-with recipes. Given a natural-language "
        "intent (e.g. 'webhook receiver with dedupe and audit'), returns a "
        "ranked list of {primitives, rationale, score, source, name} dicts. "
        "Pure retrieval, deterministic. Narrower than fastapi_meta_search "
        "(which also covers tools); kept because CONTRACT §B2.2 quality "
        "gates pin recipe-retrieval accuracy against this path."
    ),
    "tags": ["meta", "discovery", "composition", "retrieval"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
    "entry": "suggest_composition",
}

import threading
from pathlib import Path

# Recipe engine lives in the shared core; re-exported so existing imports
# (`from engine.discovery.compose import Recipe, RecipeIndex, CompositionHit`)
# keep resolving.
from hugr_core.discovery import (
    CompositionHit,
    Recipe,
    RecipeIndex,
    _extract_compose_section,
    _parse_recipes,
)

__all__ = [
    "MCP_TOOL",
    "Recipe",
    "RecipeIndex",
    "CompositionHit",
    "suggest_composition",
    "get_recipe_index",
    "_parse_recipes",
    "_extract_compose_section",
]

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml"
_VENOUS_ROOT = Path(__file__).resolve().parents[2] / "core" / "venous"


_INDEX: RecipeIndex | None = None
_INDEX_LOCK = threading.Lock()


def get_recipe_index() -> RecipeIndex:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = RecipeIndex(_REGISTRY_PATH, _VENOUS_ROOT)
    return _INDEX


def suggest_composition(intent: str, limit: int = 5) -> list[dict]:
    """Rank compose-with recipes against a free-text intent.

    Args:
        intent: natural-language description of what the caller wants to build
            — e.g. ``"webhook receiver with dedupe and audit"``.
        limit: maximum compositions to return (1-5, capped at 5).

    Returns:
        List of ``{primitives, rationale, score, source, name}`` dicts
        ranked by BM25 descending. Zero LLM calls, zero network.
    """
    limit = min(max(0, int(limit)), 5)
    if limit == 0:
        return []
    return [h.as_dict() for h in get_recipe_index().query(intent, limit=limit)]
