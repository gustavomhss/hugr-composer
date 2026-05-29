"""WP-17 — curated compose-data entries for emerging (non-manifest) primitives.

Pure-data module. Mirrors the source ``EMERGING`` dict that lived in
``engine/audit/_build_compose.py`` (no ``.manifest.json`` yet; covered by
§B1.2 grep validation only). The entry shape differs from production ``E``:
each value is a ``[patterns]`` list (no ``purpose`` / ``compose_with`` tuple).

Merged into the master ``EMERGING`` dict by
``engine.audit.compose_data._assembly``.
"""

from __future__ import annotations

ENTRIES: dict[str, list[tuple[str, list[str], str]]] = {
    "BatchCore": [
        (
            "Idempotent batch endpoint",
            ["IdempotencyStore", "RequestShape"],
            "Client sends a retry of the same batch with the same idempotency key; the store returns the cached per-item result set and BatchCore never re-invokes any handler.",
        ),
        (
            "Bounded parallelism",
            ["Bulkhead", "TimeoutBudget"],
            "Per-item semaphore + inherited deadline: a slow item cannot expand beyond its share of the pool or survive past the request's budget.",
        ),
        (
            "All-or-nothing transactional batch",
            ["UnitOfWork", "TransactionalOutbox"],
            "Failure stops processing; UoW rolls back; the outbox never emits events for items that didn't commit — downstream consumers see a coherent batch or no batch.",
        ),
    ],
    "CommandBus": [
        (
            "Write-side dispatch",
            ["CommandQuerySeparator", "UnitOfWork"],
            "Bus accepts only typed commands; each handler executes inside one UoW — commands that mutate state always commit atomically or not at all.",
        ),
        (
            "Idempotent commands",
            ["IdempotencyStore", "RequestShape"],
            "Command id is the idempotency key; the store caches the outcome — retried commands return the original result without re-executing side effects.",
        ),
        (
            "Auditable handler registry",
            ["AuditEvent", "RequestGuard"],
            "Every command dispatch audits the principal and authorized action; forbidden commands never reach the handler.",
        ),
    ],
    "DeprecationEntry": [
        (
            "Catalog + emit",
            ["DeprecationRegistry", "DeprecationReporter"],
            "Entry is the frozen value; registry routes requests to it; reporter counts hits — three primitives, one lifecycle for RFC 8594.",
        ),
        (
            "Schema-aware deprecation",
            ["SchemaComparator", "DeprecationRegistry"],
            "Comparator flags breaking changes between OpenAPI releases; the flagged endpoint becomes an Entry, scheduled for Sunset on the next release.",
        ),
        (
            "Sunset observability",
            ["DeprecationReporter", "StructuredLogger"],
            "Reporter emits structured counters per endpoint; operators see real traffic to retiring paths before the Sunset date arrives.",
        ),
    ],
    "DeprecationRegistry": [
        (
            "Middleware-stamped headers",
            ["MiddlewarePipeline", "DeprecationEntry"],
            "Pipeline asks the registry on every request; a hit stamps Sunset/Deprecation/Link headers uniformly — individual handlers never remember to do this.",
        ),
        (
            "Usage-driven retirement",
            ["DeprecationReporter", "MetricMeter"],
            "Registry lookups feed the reporter; hot deprecated endpoints are the signal not to retire on schedule.",
        ),
        (
            "Versioned rollout",
            ["SchemaComparator", "FeatureToggle"],
            "Schema diff populates the registry with sunset entries; a toggle can force 410 Gone once usage falls below threshold.",
        ),
    ],
    "DeprecationReporter": [
        (
            "Sunset-date triage",
            ["DeprecationRegistry", "DeprecationEntry"],
            "Reporter's usage_report joins with the registry's entries; the 'hottest deprecated endpoint' is obvious, and the scheduled Sunset date is one column away.",
        ),
        (
            "Metric-fed alerting",
            ["MetricMeter", "HealthProbe"],
            "Counter values feed dashboards; high usage past a threshold flips a readiness-style warning for API product owners.",
        ),
        (
            "Audit trail of retirement",
            ["AuditEvent", "StructuredLogger"],
            "Resets and Sunset enforcements are audited — there is no 'silent retirement' that support can't reconstruct.",
        ),
    ],
    "IdempotencyStore": [
        (
            "Retried-write dedup",
            ["CommandBus", "BatchCore"],
            "Handlers stash results keyed by the client's idempotency key; a retried request returns the stored result and never re-invokes the side effect.",
        ),
        (
            "Inbox-style dedup at the edge",
            ["InboundVerifier", "IdempotentConsumer"],
            "Inbound webhook verifier produces a stable event id; the store refuses replays with the same id — webhook at-least-once becomes effectively-once.",
        ),
        (
            "Bounded memory budget",
            ["CardinalityGuard", "MetricMeter"],
            "Store size is bounded and metered; an abusive client cannot exhaust memory by flooding unique keys.",
        ),
    ],
    "InboundVerifier": [
        (
            "Vendor-specific webhook trust",
            ["SignatureVerifier", "IdempotencyStore"],
            "Subclass delegates to SignatureVerifier with vendor's pinned key; the verified event id feeds the idempotency store — replay AND forgery are blocked in one pass.",
        ),
        (
            "Dispatcher seam",
            ["MiddlewarePipeline", "AuditEvent"],
            "One middleware selects the verifier by endpoint; every rejection is audited with the vendor name — forensic trails are uniform across vendors.",
        ),
        (
            "Graceful-failure envelope",
            ["CircuitBreaker", "RequestGuard"],
            "When a vendor key rotation is mid-flight, the breaker fails fast and the guard returns 401 — no ambiguous 500s during key overlap.",
        ),
    ],
    "MemoryPubSubBackend": [
        (
            "In-process event bus",
            ["EventBus", "LifecycleHook"],
            "Single-worker fan-out for intra-process events; shutdown hooks drain queues before SIGKILL — no dropped events on graceful exit.",
        ),
        (
            "Test-friendly TopicBus",
            ["TopicBus", "EventEnvelope"],
            "Conforms to the TopicBus contract with CloudEvents envelopes; tests run the pubsub layer without a broker.",
        ),
        (
            "FIFO per subscriber",
            ["StreamSubject", "CardinalityGuard"],
            "Subjects drive routing; per-topic cardinality is bounded — a typo cannot spawn unlimited queues.",
        ),
    ],
    "QueryBus": [
        (
            "Read-side dispatch",
            ["CommandQuerySeparator", "Specification"],
            "Query handlers take Specifications and return read models; the bus is the single seam where read-only semantics are enforced — no handler issues a write.",
        ),
        (
            "Cached query results",
            ["KeyValueBucket", "MaterializedView"],
            "Hot queries hit the bucket or view; cache miss falls through to the handler — response times stay bounded under spike.",
        ),
        (
            "Principal-scoped queries",
            ["CurrentPrincipal", "RequestGuard"],
            "Every query is scoped by principal + tenant; cross-tenant reads are a policy decision at the bus, not a developer oversight.",
        ),
    ],
    "FeatureFlagCache": [
        (
            "Low-latency toggle evaluation",
            ["FeatureToggle", "KeyValueBucket"],
            "Cache keeps per-cohort flag values hot; toggle evaluation is O(1) on the request path; misses refill via the bucket with bounded TTL.",
        ),
        (
            "Invalidation on change",
            ["EventBus", "AuditEvent"],
            "Flag-change events invalidate cache entries and audit the change — stale reads are bounded and the change is attributable.",
        ),
        (
            "Safe fallback",
            ["CircuitBreaker", "ConfigBinding"],
            "If the upstream provider is unreachable, the cache serves last-known-good; ConfigBinding supplies the default — a feature-flag outage never 500s a route.",
        ),
    ],
    "SchemaComparator": [
        (
            "Compat gate for CI",
            ["DeprecationEntry", "DeprecationRegistry"],
            "Breaking changes turn into DeprecationEntries in the registry automatically; CI fails if a breaking change ships without a sunset plan.",
        ),
        (
            "Canary rollout",
            ["FeatureToggle", "RequestGuard"],
            "Behavioral changes are gated behind a toggle; the guard reads toggle state per request — old and new shapes coexist until the toggle is retired.",
        ),
        (
            "Audit of schema evolution",
            ["AuditEvent", "TamperEvidentAuditLog"],
            "Every OpenAPI release seals a diff hash into the audit log; auditors verify 'what shape was public on date X' cryptographically.",
        ),
    ],
    "CostTracker": [
        (
            "Per-request cost attribution",
            ["RequestShape", "MetricMeter"],
            "Tracker composes estimators keyed by component; results ride on the request shape, flushed to metrics — cost per endpoint/tenant is observable, not inferred.",
        ),
        (
            "Budget-enforced shedding",
            ["LoadShedder", "TimeoutBudget"],
            "When a request exceeds its cost budget, the shedder can drop it before downstream calls fire — budget is a first-class admission signal.",
        ),
        (
            "LLM cost governance",
            ["LlmTrace", "PromptTemplate"],
            "LLM spans carry template + token cost; tracker sums per template — A/B prompt costs are comparable across releases.",
        ),
    ],
    "ExcelExporter": [
        (
            "Bounded-memory export",
            ["LoadShedder", "TimeoutBudget"],
            "Chunked streaming + max_rows cap + shedder admission means an export request cannot starve general traffic.",
        ),
        (
            "Observable long work",
            ["MetricMeter", "StructuredLogger"],
            "Chunk counters + duration histograms make export SLOs measurable; a slow export is visible, not anecdotal.",
        ),
        (
            "Secured output",
            ["PiiClassification", "OutputEncoder"],
            "Rows pass through classification-driven masking before sheet writes — audience-aware exports are mechanical, not a review checklist.",
        ),
    ],
    "GracefulShutdown": [
        (
            "Drain-then-stop",
            ["LifecycleHook", "HealthProbe"],
            "Shutdown flips readiness false first; hooks drain queues; in-flight requests complete within the phase budget — no 502 during deploys.",
        ),
        (
            "Coordinated with workflows",
            ["WorkflowRun", "ActivityCall"],
            "Activities heartbeat through the drain phase; workflows survive the restart and resume on the next pod — no orphaned long-running work.",
        ),
        (
            "Bounded cleanup",
            ["TimeoutBudget", "ErrorSink"],
            "Cleanup has a hard cap; lingering errors flush to the error sink before exit — nothing is silently lost on SIGTERM.",
        ),
    ],
    "ModelRegistry": [
        (
            "Lazy versioned loading",
            ["KeyValueBucket", "LifecycleHook"],
            "Registry caches loaded models keyed by name:version; lifecycle hooks warm the hot set at boot — the first request isn't a cold-start cliff.",
        ),
        (
            "Safe A/B rollout",
            ["FeatureToggle", "LlmTrace"],
            "Toggle routes a cohort to a new model version; traces carry the version attribute — quality diffs are per-version, not per-deploy.",
        ),
        (
            "Bounded memory",
            ["MetricMeter", "CardinalityGuard"],
            "Loaded-model count is metered and bounded; one stray version cannot OOM the server.",
        ),
    ],
    "Redactor": [
        (
            "Log-path PII hygiene",
            ["StructuredLogger", "PiiClassification"],
            "Structlog processor consumes classification tags; every emitted record is masked before any sink sees it — PII cannot escape via the log stream.",
        ),
        (
            "Audit-compatible masking",
            ["AuditEvent", "AccessLog"],
            "Audit and access records share the same redactor; the tamper-evident chain records masked values, never raw PII.",
        ),
        (
            "Error-path safety",
            ["ErrorSink", "StructuredLogger"],
            "Exception captures route through the redactor; stack traces containing request bodies are sanitized before Sentry or the local sink.",
        ),
    ],
    "TracingBuffer": [
        (
            "Dev-time trace inspector",
            ["Tracer", "StructuredLogger"],
            "Ring buffer of the last N traces drives a local UI; developers reproduce issues without spinning up the full OTel stack.",
        ),
        (
            "Bounded memory",
            ["CardinalityGuard", "MetricMeter"],
            "Fixed-size ring + bounded per-record size prevents a buggy loop from OOMing the process through trace capture.",
        ),
        (
            "Error-triage bridge",
            ["ErrorSink", "CorrelationContext"],
            "Exception capture attaches the latest traces for the same correlation id — 'what was happening just before this error' is one click.",
        ),
    ],
    "RetryBudget": [
        (
            "Retry-storm prevention",
            ["RetryPolicy", "CircuitBreaker"],
            "Sliding-window ratio gate ensures retries cannot exceed a fraction of the window; a partial outage does not amplify into a full outage.",
        ),
        (
            "Budget-aware policy",
            ["TimeoutBudget", "RequestShape"],
            "Retry admission considers remaining request budget and priority class — low-priority retries yield first under pressure.",
        ),
        (
            "Observable retry health",
            ["MetricMeter", "HealthProbe"],
            "Retry ratio is a first-class metric; a breaker-style readiness flip fires before customer impact.",
        ),
    ],
}
