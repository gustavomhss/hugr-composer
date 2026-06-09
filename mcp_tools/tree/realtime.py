"""`fastapi_realtime` — the realtime-domain tree dispatcher.

ONE MCP tool that routes to 5 slice tool(s) + 12 primitive(s) under the `realtime` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. The domain label is "realtime" but the on-disk
primitive namespace is "events"; ``venous_ns="events"`` keeps the copy target /
files_created / import hint on the real namespace while the domain label
differs. The data tables are unchanged, so the public contract is byte-identical
to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "events"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the realtime domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_sse": {
        "mod": "add_sse",
        "pkg": "adapt.extend.realtime",
        "desc": "Add Server-Sent Events (SSE) endpoints for real-time push to browser clients",
    },
    "add_webhook_receiver": {
        "mod": "add_webhook_receiver",
        "pkg": "adapt.extend.realtime",
        "desc": "Copy SignatureVerifier+IdempotentConsumer+AuditEvent primitives and the WebhookReceiverAdapt...",
    },
    "add_webhook_sender": {
        "mod": "add_webhook_sender",
        "pkg": "adapt.extend.realtime",
        "desc": "Add outbound webhook delivery system with retry, signature, and delivery log",
    },
    "add_websocket_chat": {
        "mod": "add_websocket_chat",
        "pkg": "adapt.extend.realtime",
        "desc": "Add production-grade WebSocket chat with JWT auth, Redis pub/sub, rooms, and message history",
    },
    "add_websocket_presence": {
        "mod": "add_websocket_presence",
        "pkg": "adapt.extend.realtime",
        "desc": "Add production-grade WebSocket presence tracking with JWT auth, Redis pub/sub, heartbeat TTL...",
    },
}

PRIMITIVES: dict[str, str] = {
    "CausalReorderBuffer": "Buffer incoming events per (aggregate_id, sequence), drain in strict causal order, and emit...",
    "DeadLetterRoute": "Named destination where undeliverable or repeatedly failed messages are routed after the red...",
    "DomainEvent": "Record an immutable fact about something meaningful that happened in the domain and publish...",
    "EventEnvelope": "Frozen, validated dataclass that captures the CloudEvents 1.0.2 canonical shape and makes ro...",
    "EventSourcedStore": "Persist aggregate state as an ordered sequence of domain events and reconstruct current stat...",
    "EventStream": "Ordered, append-only log of events partitioned by key and replayable from any offset by any...",
    "IdempotentConsumer": "Apply a message's effect at most once per logical key while tolerating at-least-once deliver...",
    "InboxDeduplicator": "Record processed message identifiers in the consumer's database so redelivered messages are...",
    "SagaOrchestrator": "Coordinate a multi-step business transaction across services by driving each step and trigge...",
    "StreamSubject": "Shared type for hierarchical subject names and pattern matching so routing, filtering, and a...",
    "TopicBus": "Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to...",
    "TransactionalOutbox": "Store outgoing messages in the same local transaction as the state change so a relay can pub...",
}

# Curated 'bundle' — 5 canonical realtime slices.
# Rationale: Full realtime stack: WebSocket chat+presence, SSE push, and webhook receiver+sender with verification and delivery guarantees.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_websocket_chat",
    "add_websocket_presence",
    "add_sse",
    "add_webhook_receiver",
    "add_webhook_sender",
)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_realtime",
    "description": (
        "Realtime domain dispatcher (HuGR tree pattern). ONE tool that routes to every realtime-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full realtime tree + primitive catalog.\n  • 'bundle' → one-shot: installs 5 curated realtime slices (add_websocket_chat, add_websocket_presence, add_sse, add_webhook_receiver, add_webhook_sender).\n  • '<slice>' → install ONE slice (add_sse, add_webhook_receiver, add_webhook_sender, add_websocket_chat, add_websocket_presence).\n  • 'primitive' → copy ONE Lego block (CausalReorderBuffer, DeadLetterRoute, DomainEvent, EventEnvelope, EventSourcedStore, EventStream, IdempotentConsumer, InboxDeduplicator, SagaOrchestrator, StreamSubject, TopicBus, TransactionalOutbox).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["realtime", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_realtime",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="realtime",
    tool_name="fastapi_realtime",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="realtime domain tree (5 bundle + 5 slices + 12 primitives)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    venous_ns="events",
    toolinput_factory=_toolinput_factory,
    bundle_missing_output_dir_next_steps=(
        "Pass params={'output_dir':'/path/to/project'}.",
    ),
    primitive_missing_args_next_steps=(
        "Example: fastapi_realtime(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
        "Call fastapi_realtime(action='list') to see available primitive names.",
    ),
    list_usage_examples=(
        "fastapi_realtime(action='bundle', params={'output_dir':'/tmp/my-app'})",
        "fastapi_realtime(action='add_websocket_chat', params={'output_dir':'/tmp/my-app'})",
        "fastapi_realtime(action='primitive', params={'name':'CausalReorderBuffer','output_dir':'/tmp/my-app'})",
    ),
)

fastapi_realtime = make_dispatcher(_CONFIG)
