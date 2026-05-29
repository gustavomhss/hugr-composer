"""WP-17 — curated compose-data entries for the `policy+resiliency` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === policy`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== policy
    "CorsPolicy": (
        "Deny-by-default evaluator for cross-origin browser requests that only echoes an allowlisted Origin and filters requested headers.",
        ["RouterPipeline", "RequestGuard", "ContentSecurityPolicy", "CsrfGuard"],
        [
            (
                "Browser edge hardening",
                ["RouterPipeline", "ContentSecurityPolicy"],
                "CORS + CSP compose into one edge policy: cross-origin requests are rejected and inline-script injection is blocked at render time.",
            ),
            (
                "No `*` with credentials",
                ["CsrfGuard", "RequestGuard"],
                "Credentialed routes never reflect `*`; CSRF binds the request to the session and Guard authorizes it — three checks, one decision.",
            ),
            (
                "Preflight caching",
                ["MiddlewarePipeline", "CorrelationContext"],
                "Preflight decisions are cacheable and logged with correlation; operators see which origins actually hit the service.",
            ),
        ],
    ),
    "DataResidencyPolicy": (
        "Bind a data_class to a set of allowed storage regions plus a transfer mechanism, rejecting writes to non-allowed regions.",
        ["PiiClassification", "EncryptionPolicy", "ProcessingRecord", "RetentionPolicy"],
        [
            (
                "Classification-driven placement",
                ["PiiClassification", "EncryptionPolicy"],
                "Sensitivity class determines region + cipher; moving a field across tiers is one declaration, not a schema migration.",
            ),
            (
                "Cross-border enforcement",
                ["ProcessingRecord", "AuditEvent"],
                "Every cross-EEA write either matches a bound transfer mechanism or is denied and audited — GDPR Chapter V is executable, not procedural.",
            ),
            (
                "Retention per region",
                ["RetentionPolicy", "LegalHold"],
                "Residency and retention declarations compose: a record stays in-region for its TTL and survives deletion only under a lawful hold.",
            ),
        ],
    ),
    "EncryptionPolicy": (
        "Declare cipher, KMS key provider, and rotation cadence per data_class and reject writes of sensitive data before a policy is bound.",
        ["KeyRotationSchedule", "DataResidencyPolicy", "PiiClassification", "SecretsVault"],
        [
            (
                "Cipher-per-class",
                ["PiiClassification", "DataResidencyPolicy"],
                "Sensitivity class pins cipher and region; unencrypted writes are rejected at the port — 'we forgot to encrypt field X' is a boot-time failure.",
            ),
            (
                "Scheduled rotation",
                ["KeyRotationSchedule", "SecretsVault"],
                "Keys rotate on cadence with overlap; the vault serves the current version and retires the previous without app restart.",
            ),
            (
                "Transit-and-rest symmetry",
                ["ContentSecurityPolicy", "SignatureVerifier"],
                "Transport and payload use matched strengths; a weak cipher anywhere is a structural incident, not a runtime anomaly.",
            ),
        ],
    ),
    "KeyRotationSchedule": (
        "Rotate data-encryption keys on a fixed cadence with an overlap window so prior versions still decrypt existing records.",
        ["EncryptionPolicy", "SecretsVault", "CryptoEnvelope", "SignatureVerifier"],
        [
            (
                "Cadenced rotation",
                ["EncryptionPolicy", "SecretsVault"],
                "Policy declares cadence; the vault ships the next version before the overlap expires — writes use the new key while reads still honor the old.",
            ),
            (
                "Envelope versioning",
                ["CryptoEnvelope", "SignatureVerifier"],
                "Ciphertext carries the key version; readers fetch the right version from the vault — a rotation is not a mass re-encryption event.",
            ),
            (
                "Miss-detection alert",
                ["MetricMeter", "AuditEvent"],
                "Missed rotations flip a metric and write an audit event; compliance lapse is a page, not an audit-year surprise.",
            ),
        ],
    ),
    # ======================================================== resiliency
    "Bulkhead": (
        "Partition concurrency so saturation inside one dependency cannot exhaust resources shared with other dependencies.",
        ["CircuitBreaker", "TimeoutBudget", "LoadShedder", "RequestShape"],
        [
            (
                "Dependency isolation",
                ["CircuitBreaker", "RequestShape"],
                "Each downstream has its own bulkhead; a slow dependency saturates its own pool without starving the rest of the service.",
            ),
            (
                "Priority lanes",
                ["LoadShedder", "RequestShape"],
                "Priority classes get dedicated pools; low-priority work is shed before high-priority work even notices contention.",
            ),
            (
                "Deadline + capacity",
                ["TimeoutBudget", "CircuitBreaker"],
                "Admission combines remaining budget and pool availability; a request is rejected fast rather than queuing past its deadline.",
            ),
        ],
    ),
    "CircuitBreaker": (
        "Short-circuit calls to a failing dependency by transitioning between closed, open, and half-open on rolling failure signals.",
        ["RetryPolicy", "TimeoutBudget", "Bulkhead", "HealthProbe"],
        [
            (
                "Bounded-retry guard",
                ["RetryPolicy", "TimeoutBudget"],
                "Breaker opens before retry storms amplify; budgets ensure retries never outlast the request deadline.",
            ),
            (
                "Dependency isolation",
                ["Bulkhead", "OutboundBinding"],
                "Each adapter has its own breaker and pool; one broken vendor does not take down the primary transaction path.",
            ),
            (
                "Probe-visible health",
                ["HealthProbe", "MetricMeter"],
                "Open breakers flip readiness false for the affected capability; callers drain instead of piling on.",
            ),
        ],
    ),
    "LoadShedder": (
        "Drop or reject low-priority work when the server enters an overload regime so high-priority traffic survives.",
        ["RateLimiter", "Bulkhead", "RequestShape", "TimeoutBudget"],
        [
            (
                "Priority-aware admission",
                ["RequestShape", "Bulkhead"],
                "Priority class + pool utilization drive admission; shed requests return 503 fast instead of queuing past their deadline.",
            ),
            (
                "Protect tail latency",
                ["TimeoutBudget", "RateLimiter"],
                "Under overload, the shedder trims tail work; the rate limiter maintains per-tenant fairness — p99 stays honest.",
            ),
            (
                "Cascade prevention",
                ["CircuitBreaker", "HealthProbe"],
                "Shedding before breakers trip keeps capacity observable; probes see real state, not 'every downstream breaker open'.",
            ),
        ],
    ),
    "RateLimiter": (
        "Enforce a maximum rate of admitted operations over a rolling window with optional waiting and per-tenant fairness.",
        ["LoadShedder", "RequestShape", "Bulkhead", "AuditEvent"],
        [
            (
                "Per-tenant fairness",
                ["RequestShape", "AuditEvent"],
                "Buckets are keyed by tenant / principal; noisy neighbors are throttled and audited — operators never wonder whose traffic spiked.",
            ),
            (
                "Abuse protection",
                ["RequestGuard", "AuditEvent"],
                "Auth failures hit a stricter bucket; brute-force attempts audit with velocity — the guard and limiter act as one admission layer.",
            ),
            (
                "Composed with shedding",
                ["LoadShedder", "Bulkhead"],
                "Rate limits cap steady-state; shedder cuts transient spikes; bulkheads isolate pools — three primitives, one admission SLO.",
            ),
        ],
    ),
    "RetryPolicy": (
        "Describe under which conditions a failed call may be retried, bounded by max attempts, backoff with jitter, and budget.",
        ["CircuitBreaker", "TimeoutBudget", "IdempotentConsumer", "RequestShape"],
        [
            (
                "Safe retries",
                ["IdempotentConsumer", "RequestShape"],
                "Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never causes double effects.",
            ),
            (
                "Bounded cost",
                ["TimeoutBudget", "CircuitBreaker"],
                "Backoff respects the remaining budget; the breaker opens before retries become a feedback loop.",
            ),
            (
                "Jittered fan-out",
                ["OutboundBinding", "RpcInterceptor"],
                "Policy mounts as an interceptor with per-vendor jitter; synchronized retries across pods are impossible by construction.",
            ),
        ],
    ),
    "TimeoutBudget": (
        "Attach a monotonic deadline to an inbound request and propagate the remaining budget to every downstream call.",
        ["RequestShape", "CircuitBreaker", "RetryPolicy", "MiddlewarePipeline"],
        [
            (
                "Deadline propagation",
                ["RequestShape", "MiddlewarePipeline"],
                "Pipeline stamps the deadline on entry; every downstream call reads the remaining budget — no handler extends time by accident.",
            ),
            (
                "Bounded retries",
                ["RetryPolicy", "CircuitBreaker"],
                "Retries never outlast the budget; budget-exhausted failures fail fast and surface meaningfully to the caller.",
            ),
            (
                "Priority interaction",
                ["LoadShedder", "Bulkhead"],
                "Admission considers (budget, priority, pool) together; a near-deadline low-priority request is dropped before it wastes capacity.",
            ),
        ],
    ),
}
