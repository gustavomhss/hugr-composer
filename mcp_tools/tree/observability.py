"""`fastapi_observability` — the observability-domain tree dispatcher.

ONE MCP tool that routes to 3 slice tool(s) + 17 primitive(s) under the `observability` domain. The Claude agent chooses granularity by `action`.

See `mcp_tools/tree/auth.py` — the canonical POC template this file mirrors.

M3.2 fan-out: this module is now pure DATA + one
``make_dispatcher(DomainTreeConfig(...))`` call. The branch logic, envelope,
slice routing, and primitive copy live in ``hugr_core.dispatch`` — the generic
engine shared by every domain. The domain label is "observability" but the
on-disk primitive namespace is "obs"; ``venous_ns="obs"`` keeps the copy
target / files_created / import hint on the real namespace while the domain
label differs. The data tables are unchanged, so the public contract is
byte-identical to the pre-extraction dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hugr_core.dispatch import DomainTreeConfig, make_dispatcher

SKILL_ROOT = Path(__file__).resolve().parents[2]
VENOUS_DIR = SKILL_ROOT / "core" / "venous" / "obs"
ADAPTERS_FASTAPI = SKILL_ROOT / "core" / "venous" / "_adapters" / "fastapi"


# ---------------------------------------------------------------------------
# Tree declaration — single source of truth for the observability domain surface
# ---------------------------------------------------------------------------

SLICES: dict[str, dict[str, Any]] = {
    "add_opentelemetry": {
        "mod": "add_opentelemetry",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add OpenTelemetry traces, metrics, and logs with lazy SDK imports, OTELMiddleware for reques...",
    },
    "add_prometheus_metrics": {
        "mod": "add_prometheus_metrics",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Add Prometheus RED metrics (request_total, request_duration_seconds, request_errors_total) w...",
    },
    "add_structured_logging": {
        "mod": "add_structured_logging",
        "pkg": "adapt.extend.infrastructure",
        "desc": "Upgrade to structlog with JSON renderer, correlation ID binding, per-request context, and PI...",
    },
}

PRIMITIVES: dict[str, str] = {
    "AccessLog": "Record every successful READ of a classified record separately from the security audit log s...",
    "CardinalityGuard": "Bound the unique attribute-value combinations attached to a metric or log stream to prevent...",
    "CorrelationContext": "Propagate a stable request identifier and optional baggage across threads, async tasks, and...",
    "CorrelationId": "Opaque string that travels with a request across services and log lines so a reader can stit...",
    "ErrorSink": "Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation...",
    "EventBus": "In-process publish/subscribe point for named framework and application events with structure...",
    "HealthProbe": "Expose a typed liveness / readiness signal that reflects the real state of the process and i...",
    "HistogramBuckets": "Define explicit latency and size bucket boundaries for histogram instruments so quantile est...",
    "LifecycleHook": "Named callback fired at a defined application phase (starting, ready, stopping) so tools can...",
    "LlmTrace": "Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI sem...",
    "MetricMeter": "Record numeric measurements through four instrument shapes — counter, up-down counter, histo...",
    "ResourceDescriptor": "Describe the entity producing telemetry — service, version, deployment environment, instance...",
    "SamplingPolicy": "Decide whether a given trace or span is retained, combining head-based and tail-based rules...",
    "SemanticAttributes": "Expose OpenTelemetry semantic-convention attribute keys as typed constants and enforce that...",
    "StructuredLogger": "Emit machine-parseable key/value log records with a fixed level taxonomy and attached trace/...",
    "TelemetryExporter": "Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and delive...",
    "Tracer": "Create spans that represent a unit of work, attach attributes and events, link related spans...",
}

# Curated 'bundle' — 3 canonical observability slices.
# Rationale: The three pillars wired end-to-end: OpenTelemetry traces/metrics/logs, Prometheus RED metrics, structured JSON logging with PII redaction.
BUNDLE_SLICES: tuple[str, ...] = (
    "add_opentelemetry",
    "add_prometheus_metrics",
    "add_structured_logging",
)


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

MCP_TOOL = {
    "name": "fastapi_observability",
    "description": (
        "Observability domain dispatcher (HuGR tree pattern). ONE tool that routes to every observability-related capability the kit ships. Choose granularity via `action`:\n  • 'list' → returns the full observability tree + primitive catalog.\n  • 'bundle' → one-shot: installs 3 curated observability slices (add_opentelemetry, add_prometheus_metrics, add_structured_logging).\n  • '<slice>' → install ONE slice (add_opentelemetry, add_prometheus_metrics, add_structured_logging).\n  • 'primitive' → copy ONE Lego block (AccessLog, CardinalityGuard, CorrelationContext, CorrelationId, ErrorSink, EventBus, HealthProbe, HistogramBuckets, LifecycleHook, LlmTrace, MetricMeter, ResourceDescriptor, SamplingPolicy, SemanticAttributes, StructuredLogger, TelemetryExporter, Tracer).\nCall with action='list' if unsure. Every return carries `next_steps`."
    ),
    "tags": ["observability", "domain", "dispatcher"],
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "entry": "fastapi_observability",
}


def _toolinput_factory(**kwargs):
    """Lazily import adapt.contracts.ToolInput (keeps action='list' pydantic-free)."""
    from adapt.contracts import ToolInput

    return ToolInput(**kwargs)


_CONFIG = DomainTreeConfig(
    domain="observability",
    tool_name="fastapi_observability",
    tool_meta=MCP_TOOL,
    slices=SLICES,
    primitives=PRIMITIVES,
    bundle_slices=BUNDLE_SLICES,
    list_summary="observability domain tree (3 bundle + 3 slices + 17 primitives)",
    venous_dir=VENOUS_DIR,
    adapters_dir=ADAPTERS_FASTAPI,
    venous_ns="obs",
    toolinput_factory=_toolinput_factory,
    bundle_missing_output_dir_next_steps=(
        "Pass params={'output_dir':'/path/to/project'}.",
    ),
    primitive_missing_args_next_steps=(
        "Example: fastapi_observability(action='primitive', params={'name':'X','output_dir':'/tmp/app'}).",
        "Call fastapi_observability(action='list') to see available primitive names.",
    ),
    list_usage_examples=(
        "fastapi_observability(action='bundle', params={'output_dir':'/tmp/my-app'})",
        "fastapi_observability(action='add_opentelemetry', params={'output_dir':'/tmp/my-app'})",
        "fastapi_observability(action='primitive', params={'name':'AccessLog','output_dir':'/tmp/my-app'})",
    ),
)

fastapi_observability = make_dispatcher(_CONFIG)
