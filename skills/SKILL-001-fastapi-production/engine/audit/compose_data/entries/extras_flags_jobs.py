"""WP-17 — curated compose-data entries for the `extras+flags+jobs` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === extras`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== extras
    "OutboundBinding": (
        "Keep every external integration behind one declarative adapter that exposes a typed-operation surface and hides SDK quirks.",
        ["AntiCorruptionLayer", "CircuitBreaker", "RetryPolicy", "SecretsVault"],
        [
            (
                "Typed SDK facade",
                ["AntiCorruptionLayer", "SecretsVault"],
                "Callers see typed operations; the adapter loads credentials from the vault and translates SDK types — no vendor import leaks into business code.",
            ),
            (
                "Resilient egress",
                ["CircuitBreaker", "RetryPolicy"],
                "Every outbound call is wrapped in a breaker + retry policy; a flaky vendor does not cascade into the primary transaction.",
            ),
            (
                "Swap-in-place",
                ["DiContainer", "FeatureToggle"],
                "Adapters are DI-registered; a toggle switches between vendors at runtime without redeploy — vendor lock-in becomes a configuration decision.",
            ),
        ],
    ),
    "RequestShape": (
        "Capture a request's resiliency context — priority class, deadline, idempotency key, retry-count — so downstream primitives react the same way.",
        ["TimeoutBudget", "LoadShedder", "IdempotentConsumer", "RetryPolicy"],
        [
            (
                "Deadline propagation",
                ["TimeoutBudget", "MiddlewarePipeline"],
                "The shape carries the remaining budget; every downstream call reads the same deadline — no handler extends the budget by accident.",
            ),
            (
                "Priority-aware shedding",
                ["LoadShedder", "Bulkhead"],
                "Shed/admit decisions are driven by the request's priority class — high-priority work survives overload without retries becoming a feedback loop.",
            ),
            (
                "Idempotent retries",
                ["RetryPolicy", "IdempotentConsumer"],
                "Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never doubles effects.",
            ),
        ],
    ),
    "RpcInterceptor": (
        "Define the single middleware seam for remote calls, specifying what an interceptor may do and in what order interceptors compose.",
        ["OutboundBinding", "MiddlewarePipeline", "CorrelationContext", "Tracer"],
        [
            (
                "Symmetric middleware",
                ["MiddlewarePipeline", "OutboundBinding"],
                "Inbound pipeline and outbound interceptors share a contract — one mental model governs every hop in and out of the service.",
            ),
            (
                "Correlation propagation",
                ["CorrelationContext", "Tracer"],
                "Interceptors inject correlation id and trace context on every RPC; distributed traces stitch end-to-end without handler code.",
            ),
            (
                "Policy injection",
                ["CircuitBreaker", "RetryPolicy"],
                "Resiliency policies mount as interceptors; swapping policy per call is a registration change, not a rewrite.",
            ),
        ],
    ),
    "VirtualActor": (
        "Serialize writes per entity without hand-rolling locks; give entities a durable reminder surface for time-based behavior.",
        ["WorkflowRun", "DistributedLock", "IdempotentConsumer", "DurableTimer"],
        [
            (
                "Per-entity serialization",
                ["DistributedLock", "IdempotentConsumer"],
                "Writes to one entity run sequentially even across hosts; idempotent framing means a rehomed actor never double-applies an in-flight message.",
            ),
            (
                "Durable reminders",
                ["DurableTimer", "WorkflowRun"],
                "Actor reminders survive restarts; a workflow step scheduled for next week fires once regardless of deploy churn.",
            ),
            (
                "Saga participant",
                ["SagaOrchestrator", "WorkflowRun"],
                "Actors respond to saga commands and emit events; compensations land as messages the actor processes in order.",
            ),
        ],
    ),
    # ======================================================== flags
    "FeatureToggle": (
        "Named boolean or variant predicate, evaluated against the current context, that controls whether a code path runs.",
        ["RequestGuard", "ConfigBinding", "CurrentPrincipal", "AuditEvent"],
        [
            (
                "Gradual rollout",
                ["CurrentPrincipal", "AuditEvent"],
                "Toggle evaluation keys on principal cohort; every activation and deactivation is audited so 'who saw the new path' is always answerable.",
            ),
            (
                "Kill switch",
                ["CircuitBreaker", "RequestGuard"],
                "A toggle flipped off short-circuits the feature before the breaker trips; an ops team can stop the bleed without a redeploy.",
            ),
            (
                "Config-vs-flag boundary",
                ["ConfigBinding", "AuditEvent"],
                "Static shape lives in config; per-cohort variability lives in toggles — two distinct change-management paths, both auditable.",
            ),
        ],
    ),
    # ======================================================== jobs
    "ActivityCall": (
        "Pin the activity contract so every tool uses the same timeouts, retry policy, heartbeat rules, and typed inputs/outputs.",
        ["WorkflowRun", "RetryPolicy", "TimeoutBudget", "IdempotentConsumer"],
        [
            (
                "Typed step contract",
                ["WorkflowRun", "RetryPolicy"],
                "Every workflow step declares its ActivityCall; retry and timeout are part of the contract — not per-step boilerplate.",
            ),
            (
                "Heartbeated long work",
                ["TimeoutBudget", "HealthProbe"],
                "Long activities heartbeat within the budget; a stalled activity is reclaimed and retried without a silent orphan.",
            ),
            (
                "At-least-once activities",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Activities are retried on worker loss; idempotency keys make repeat execution safe — correctness does not depend on 'exactly once'.",
            ),
        ],
    ),
    "DurableTimer": (
        "Expose a replay-safe sleep API so workflows can wait for minutes, hours, or days without holding a thread or losing state on restart.",
        ["WorkflowRun", "VirtualActor", "SagaOrchestrator", "ActivityCall"],
        [
            (
                "Long-wait workflow",
                ["WorkflowRun", "ActivityCall"],
                "`sleep(7d)` survives deploys; the next activity fires exactly once at the scheduled wall clock — no cron, no shared scheduler.",
            ),
            (
                "Actor reminders",
                ["VirtualActor", "WorkflowRun"],
                "Virtual actors use timers as durable reminders; an entity 'wakes itself up' in the future without a centralized scheduler.",
            ),
            (
                "Saga timeouts",
                ["SagaOrchestrator", "ActivityCall"],
                "Sagas schedule compensating deadlines via durable timers; a lost participant triggers compensation at T+N regardless of process lifetimes.",
            ),
        ],
    ),
    "WorkflowRun": (
        "Give the application a single contract for long-running orchestrations that survive process restart, rebalancing, and deploy.",
        ["ActivityCall", "DurableTimer", "SagaOrchestrator", "VirtualActor"],
        [
            (
                "Durable orchestration",
                ["ActivityCall", "DurableTimer"],
                "Workflow code is deterministic; activities are side-effectful; timers are durable — the workflow history is the single replay source of truth.",
            ),
            (
                "Saga host",
                ["SagaOrchestrator", "ActivityCall"],
                "Sagas run as workflows; compensations are activities; the framework guarantees at-most-once compensation per step.",
            ),
            (
                "Actor substrate",
                ["VirtualActor", "DurableTimer"],
                "Workflows host virtual actor instances; reminders and state survive host loss — 'one actor per entity, always' is mechanical.",
            ),
        ],
    ),
}
