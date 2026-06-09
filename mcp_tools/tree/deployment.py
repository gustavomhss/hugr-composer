"""`fastapi_deployment` — the deployment-domain tree dispatcher.

ONE MCP tool that routes to slice tool(s) + primitive(s) under the `deployment` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. The data tables (SLICES / PRIMITIVES /
BUNDLE_SLICES / MCP_TOOL) are unchanged, so the public contract is
byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "deployment"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the deployment domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_docker_production": {
        "mod": "add_docker_production",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add a multi-stage production Dockerfile, .dockerignore, docker-compose.prod.yml, and docker-...",
    },
    "add_request_tracing_ui": {
        "mod": "add_request_tracing_ui",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add an embedded request tracing dashboard: TracingBuffer ring buffer (last 1000 requests), T...",
    },
}

PRIMITIVES: dict[str, str] = {}

# Curated 'bundle' — 2 canonical deployment slices.
# Rationale: Production deployment essentials: multi-stage Docker image + request tracing UI for live observability.

BUNDLE_SLICES: tuple[str, ...] = (
    "add_docker_production",
    "add_request_tracing_ui",
)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_deployment",
    "description": (
        "Deployment domain dispatcher (HuGR tree pattern). ONE tool that routes to every deployment-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full deployment tree.\n  • 'bundle' → one-shot: installs 2 curated deployment slices (add_docker_production, add_request_tracing_ui).\n  • '<slice>' → install ONE slice (add_docker_production, add_request_tracing_ui).\n  • 'primitive' → N/A (no core.venous primitives here).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["deployment", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_deployment",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="deployment",
    tool_name="fastapi_deployment",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="deployment domain tree (2 bundle + 2 slices)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    toolinput_factory=_toolinput_factory,
)

fastapi_deployment = make_dispatcher(_CONFIG)
