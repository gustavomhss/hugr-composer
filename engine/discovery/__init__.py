"""Discovery layer — pure-retrieval BM25 over primitives_by_concern.yaml."""

from __future__ import annotations

from engine.discovery.compose import (
    CompositionHit,
    Recipe,
    RecipeIndex,
    get_recipe_index,
    suggest_composition,
)
from engine.discovery.find_primitive import (
    PrimitiveHit,
    PrimitiveIndex,
    find_primitive,
    get_index,
)

__all__ = [
    "CompositionHit",
    "PrimitiveHit",
    "PrimitiveIndex",
    "Recipe",
    "RecipeIndex",
    "find_primitive",
    "get_index",
    "get_recipe_index",
    "suggest_composition",
]
