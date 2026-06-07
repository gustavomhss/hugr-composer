"""BM25 retrieval over primitives_by_concern.yaml + primitive .md bodies.

Contract: B2.1 (CONTRACT.md §B).

This module is now a thin **skill-side adapter** over the generic
``hugr_core.discovery`` engine: the stemmer, tokenizer, BM25 ranking, and the
``PrimitiveIndex`` itself live in the shared core. Everything below is THIS
skill's binding — the registry/venous paths, the process-level index singleton,
the CONTRACT §B2.1 ``limit`` cap, and the MCP tool descriptor (skill vocabulary,
discovered by the catalog scanner under the ``discovery`` scan root).

- Pure retrieval, zero LLM calls, zero network.
- Index loaded once per process (module-level cache).
- Query latency target: p95 < 50 ms for N=97 primitives (enforced by tests).
- Ranking: BM25 (k1=1.5, b=0.75) over a weighted multi-field concatenation —
  name and concern are boosted so exact-name queries rank the primitive first.
"""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_meta_search_primitive",
    "description": (
        "BM25 retrieval over primitives_by_concern.yaml. Returns ranked "
        "{name, namespace, concern, purpose, score} hits. Pure retrieval, "
        "deterministic, <50ms p95. Narrower than fastapi_meta_search "
        "(which unifies tools + primitives + recipes); kept because "
        "CONTRACT §B2.1 quality gates pin accuracy thresholds against this "
        "exact retrieval path."
    ),
    "tags": ["meta", "discovery", "retrieval"],
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
    "entry": "find_primitive",
}

import threading
from pathlib import Path

# Ranking engine + index live in the shared core; re-exported so existing
# imports (`from engine.discovery.find_primitive import _stem`, `_tokenize`,
# `_K1`, `_B`, `PrimitiveIndex`) keep resolving.
from hugr_core.discovery import (
    _B,
    _K1,
    PrimitiveHit,
    PrimitiveIndex,
    _camel_split,
    _stem,
    _tokenize,
)

__all__ = [
    "MCP_TOOL",
    "PrimitiveHit",
    "PrimitiveIndex",
    "find_primitive",
    "get_index",
    "_B",
    "_K1",
    "_stem",
    "_camel_split",
    "_tokenize",
]

_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "primitives_by_concern.yaml"
_VENOUS_ROOT = Path(__file__).resolve().parents[2] / "core" / "venous"


_INDEX: PrimitiveIndex | None = None
_INDEX_LOCK = threading.Lock()


def get_index() -> PrimitiveIndex:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = PrimitiveIndex(_REGISTRY_PATH, _VENOUS_ROOT)
    return _INDEX


def find_primitive(concern: str = "", query: str = "", limit: int = 10) -> list[dict]:
    """Public retrieval API — MCP-facing.

    Args:
        concern: one of the registry's concern tags, or empty for all.
        query: natural-language fragment, e.g. "dedupe webhooks".
        limit: maximum hits (contract caps at 10).

    Returns:
        List of `{name, namespace, concern, purpose, score}` dicts,
        ranked by BM25 relevance descending.
    """
    limit = min(max(0, int(limit)), 10)
    if limit == 0:
        return []
    return [h.as_dict() for h in get_index().query(concern, query, limit=limit)]
