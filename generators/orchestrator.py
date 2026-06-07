"""Orchestrator: generates a complete FastAPI production project.

Calls all generators in the correct dependency order, producing a
fully-wired project that runs out of the box.  This is the single
MCP tool exposed to the LLM — the LLM calls ``generate_project()``
with business-domain parameters, the orchestrator handles all infra.

Usage:
    from generators.orchestrator import generate_project

    result = generate_project(
        output_dir="/tmp/my-ecommerce",
        name="ecommerce",
        models={
            "Product": {"name": "str", "price": "Decimal", "stock": "int"},
            "Order": {"user_id": "uuid", "status": "str", "total": "Decimal"},
        },
        owner_models={"Order": "user"},
    )

Implementation note
-------------------
The implementation was split across ``orchestrator__impl1`` /
``orchestrator__impl2`` / ``orchestrator__impl3`` to keep every file
under the 500-LOC cap.  This module re-exports the public surface so
``from generators.orchestrator import generate_project`` (and the
``PROFILES`` table) continues to work unchanged.
"""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_resiliency_generate_project",
    "description": "Generate a complete production-ready FastAPI project.",
    "tags": ["generator", "orchestrator"],
    "entry": "generate_project",
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
}

# --- Public API (preserved import path) -----------------------------------
from generators.orchestrator__impl1 import (  # noqa: E402
    PROFILES,
    _UNSET,
    _Ctx,
    generate_project,
)

# --- Internal helpers (kept importable for backwards compatibility) -------
from generators.orchestrator__impl2 import (  # noqa: E402
    _generate_package_inits,
    _generate_requirements,
    _write_bola_shared_models_audit,
)

__all__ = [
    "MCP_TOOL",
    "PROFILES",
    "generate_project",
]
