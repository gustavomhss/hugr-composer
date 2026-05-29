"""WP-17 — curated compose-data entries for the `cache` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === cache`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== cache
    "DistributedLock": (
        "Give workers a single contract for rare, sequential, cross-process work such as leader-only cron, serialized migrations, and exclusive file IO.",
        ["KeyValueBucket", "CircuitBreaker", "TimeoutBudget", "WorkflowRun"],
        [
            (
                "Leader-only cron",
                ["WorkflowRun", "TimeoutBudget"],
                "Only the lock holder runs the scheduled job; the lease is shorter than the budget so a stalled leader loses leadership before it can run twice.",
            ),
            (
                "Safe migration fence",
                ["KeyValueBucket", "AuditEvent"],
                "A data migration acquires the lock and writes a revision record to the KV bucket; concurrent deploys observe the fence and abort cleanly.",
            ),
            (
                "Fault-tolerant acquisition",
                ["CircuitBreaker", "RetryPolicy"],
                "Lock acquisition wraps the Redis/etcd call in a breaker so a backend outage fails fast rather than queuing a thundering herd.",
            ),
        ],
    ),
    "KeyValueBucket": (
        "Provide one small contract over optimistic concurrency (create/update/delete with revision) plus a capped read-through cache.",
        ["DistributedLock", "IdentityMap", "CircuitBreaker", "MetricMeter"],
        [
            (
                "Lost-update prevention",
                ["DistributedLock", "AuditEvent"],
                "Updates carry a revision; on mismatch the caller re-reads instead of overwriting, and the conflict is audited — two writers cannot silently clobber each other.",
            ),
            (
                "Read-through cache",
                ["IdentityMap", "MetricMeter"],
                "Identity-map-like semantics per process plus bucket-level TTL keep hot keys in memory; cache hit ratio is a first-class metric, not a guess.",
            ),
            (
                "Graceful degradation",
                ["CircuitBreaker", "LoadShedder"],
                "When the KV backend is unhealthy the bucket returns stale-on-error under a breaker, while the shedder rejects low-priority writes — availability over freshness.",
            ),
        ],
    ),
}
