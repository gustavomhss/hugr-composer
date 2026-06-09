"""`fastapi_api` — the api-domain tree dispatcher.

ONE MCP tool that routes to 7 slice tool(s) + 17 primitive(s) under the `api` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.

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
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "api"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the api domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_api_deprecation": {
        "mod": "add_api_deprecation",
        "pkg": "adapt.extend.api_design",
        "desc": "Add endpoint lifecycle management with RFC 8594 Sunset headers, usage tracking, and @depreca...",
    },
    "add_api_versioning": {
        "mod": "add_api_versioning",
        "pkg": "adapt.extend.api_design",
        "desc": "Add URL-based API versioning (/api/v1, /api/v2) with deprecation headers",
    },
    "add_batch_endpoint": {
        "mod": "add_batch_endpoint",
        "pkg": "adapt.extend.api_design",
        "desc": "Add a generic batch request endpoint that fans out to multiple sub-requests",
    },
    "add_cqrs": {
        "mod": "add_cqrs",
        "pkg": "adapt.extend.api_design",
        "desc": "Add a production-grade CQRS layer with CommandBus, QueryBus, read-replica session routing, a...",
    },
    "add_graphql": {
        "mod": "add_graphql",
        "pkg": "adapt.extend.api_design",
        "desc": "Add GraphQL endpoint (Strawberry) alongside the existing REST API",
    },
    "add_graphql_subscriptions": {
        "mod": "add_graphql_subscriptions",
        "pkg": "adapt.extend.api_design",
        "desc": "Add WebSocket GraphQL subscriptions (graphql-ws protocol) to a FastAPI project, extending th...",
    },
    "add_long_running_task": {
        "mod": "add_long_running_task",
        "pkg": "adapt.extend.api_design",
        "desc": "Copy WorkflowRun + DurableTimer primitives + FastAPI WorkflowAdapter into the project and wi...",
    },
}

PRIMITIVES: dict[str, str] = {
    "BatchCore": "Async batch executor with per-item timeout, bounded parallelism, and two isolation modes (al...",
    "CommandBus": "Dispatch Commands to their registered async handlers.",
    "CommandQuerySeparator": "Partitions the API into write commands that mutate state and read queries that observe it so...",
    "ContextMap": "Catalogs every BoundedContext and the integration relationship so upstream/downstream teams...",
    "DataLoader": "Batches and dedupes per-request loads from N-per-resolver patterns into one bulk fetch per k...",
    "DeprecationEntry": "Value object carrying the metadata required to emit RFC 8594 Sunset / Deprecation headers fo...",
    "DeprecationRegistry": "Index DeprecationEntry objects by their (METHOD, path) composite key so request middleware c...",
    "DeprecationReporter": "In-memory call-count tracker for deprecated endpoints: record a hit per request, emit a usag...",
    "IdempotencyStore": "Thread-safe in-memory key-to-result cache used to deduplicate retried requests: get/put/seen...",
    "InboundVerifier": "Abstract extension point for provider-specific inbound webhook verification (Stripe, GitHub,...",
    "MemoryPubSubBackend": "In-process fan-out pub/sub backend: publish() broadcasts a payload to every live subscriber...",
    "MiddlewarePipeline": "Ordered chain of components that each transform the RequestContext and decide whether to cal...",
    "PersistedQueryRegistry": "SHA-256 keyed allow-list of pre-registered queries; clients send 64-char ids and unregistere...",
    "QueryBus": "Dispatch Queries to their registered async handlers.",
    "RequestContext": "Per-request bag that carries identity, headers, correlation id, and free-form assigns throug...",
    "RouterPipeline": "Named bundle of middleware that a route joins with `pipe_through` so groups share edge polic...",
    "ValueTransform": "Strongly-typed parse/validate step that converts a raw inbound argument into the domain type...",
}

# Curated 'bundle' — 5 canonical api slices.
# Rationale: Production API surface: versioning, deprecation headers, batch endpoint, CQRS, and durable long-running task support.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_api_versioning",
    "add_api_deprecation",
    "add_batch_endpoint",
    "add_cqrs",
    "add_long_running_task",
)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_api",
    "description": (
        "Api domain dispatcher (HuGR tree pattern). ONE tool that routes to every api-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full api tree + primitive catalog.\n  • 'bundle' → one-shot: installs 5 curated api slices (add_api_versioning, add_api_deprecation, add_batch_endpoint, add_cqrs, add_long_running_task).\n  • '<slice>' → install ONE slice (add_api_deprecation, add_api_versioning, add_batch_endpoint, add_cqrs, add_graphql, add_graphql_subscriptions, add_long_running_task).\n  • 'primitive' → copy ONE Lego block (BatchCore, CommandBus, CommandQuerySeparator, ContextMap, DataLoader, DeprecationEntry, DeprecationRegistry, DeprecationReporter, IdempotencyStore, InboundVerifier, MemoryPubSubBackend, MiddlewarePipeline, PersistedQueryRegistry, QueryBus, RequestContext, RouterPipeline, ValueTransform).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["api", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_api",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="api",
    tool_name="fastapi_api",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="api domain tree (5 bundle + 7 slices + 17 primitives)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    toolinput_factory=_toolinput_factory,
    primitive_missing_args_next_steps=(
        "Example: fastapi_api(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
        "Call fastapi_api(action='list') to see available primitive names.",
    ),
    list_usage_examples=(
        "fastapi_api(action='bundle', params={'output_dir':'/tmp/my-app'})",
        "fastapi_api(action='add_api_versioning', params={'output_dir':'/tmp/my-app'})",
        "fastapi_api(action='primitive', params={'name':'BatchCore','output_dir':'/tmp/my-app'})",
    ),
)

fastapi_api = make_dispatcher(_CONFIG)
