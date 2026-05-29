"""WP-17 — curated compose-data entries for the `events` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === events`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== events
    "DeadLetterRoute": (
        "Named destination where undeliverable or repeatedly failed messages are routed after the redelivery budget is exhausted.",
        ["IdempotentConsumer", "RetryPolicy", "TopicBus", "AuditEvent"],
        [
            (
                "Budget-exhausted routing",
                ["RetryPolicy", "IdempotentConsumer"],
                "When the retry budget burns down, the message lands on the DLR with its full failure history — no infinite redelivery storm.",
            ),
            (
                "Poison-pill quarantine",
                ["TopicBus", "AuditEvent"],
                "Malformed messages are quarantined out of the primary topic and audited; operators can replay after fix without crashing the consumer fleet.",
            ),
            (
                "Reprocess with dedupe",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Replaying from DLR preserves original idempotency keys; already-applied effects stay applied once — replay is safe by construction.",
            ),
        ],
    ),
    "DomainEvent": (
        "Record an immutable fact about something meaningful that happened in the domain and publish it to domain subscribers.",
        ["EventEnvelope", "TransactionalOutbox", "Aggregate", "TopicBus"],
        [
            (
                "Aggregate-emitted facts",
                ["Aggregate", "TransactionalOutbox"],
                "Aggregates raise events on state change; the outbox commits them with the state — no event ships without its corresponding mutation.",
            ),
            (
                "Typed published language",
                ["EventEnvelope", "TopicBus"],
                "Events travel inside a CloudEvents envelope so schema, source, and id are wire-level — consumers in other contexts never speak raw dict.",
            ),
            (
                "Event-driven integration",
                ["TopicBus", "IdempotentConsumer"],
                "Subscribers consume through idempotent consumers; at-least-once from the bus becomes effectively exactly-once at the handler.",
            ),
        ],
    ),
    "EventEnvelope": (
        "Frozen, validated dataclass that captures the CloudEvents 1.0.2 canonical shape and makes routing/version/time first-class.",
        ["DomainEvent", "TopicBus", "StreamSubject", "IdempotentConsumer"],
        [
            (
                "Wire-format contract",
                ["DomainEvent", "TopicBus"],
                "Envelope is the single on-the-wire shape across brokers; producers and consumers never negotiate format per integration.",
            ),
            (
                "Subject-based routing",
                ["StreamSubject", "TopicBus"],
                "The subject field drives hierarchical routing; consumers subscribe by pattern without parsing payloads.",
            ),
            (
                "Dedupe by envelope id",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "The envelope id is the canonical idempotency key; any consumer can dedupe by id without inventing its own hashing.",
            ),
        ],
    ),
    "EventSourcedStore": (
        "Persist aggregate state as an ordered sequence of domain events and reconstruct current state by folding over the log.",
        ["DomainEvent", "EventStream", "Aggregate", "MaterializedView"],
        [
            (
                "State-from-events",
                ["DomainEvent", "Aggregate"],
                "Aggregates are rehydrated by replaying their event stream; there is no mutable state of record — the log is authoritative.",
            ),
            (
                "Snapshotted rebuild",
                ["EventStream", "MaterializedView"],
                "Read models and aggregate snapshots are materialized from the stream; a rebuild from genesis is always a valid recovery path.",
            ),
            (
                "Temporal queries",
                ["EventStream", "Specification"],
                "Because history is the source of truth, 'state as of time T' is a fold truncated at T — audit queries are a library concern, not a schema migration.",
            ),
        ],
    ),
    "EventStream": (
        "Ordered, append-only log of events partitioned by key and replayable from any offset by any number of independent consumers.",
        ["TopicBus", "EventEnvelope", "IdempotentConsumer", "ChangeDataCapture"],
        [
            (
                "Partitioned ordering",
                ["TopicBus", "IdempotentConsumer"],
                "Per-key order is preserved; consumers dedupe by envelope id so a replay never re-applies effects even though it re-reads events.",
            ),
            (
                "Replay as recovery",
                ["MaterializedView", "EventSourcedStore"],
                "Views and aggregates can be rebuilt from any offset; disaster recovery is 'reset the consumer group' — not 'restore a backup'.",
            ),
            (
                "CDC ingress",
                ["ChangeDataCapture", "EventEnvelope"],
                "CDC lands directly on an event stream wrapped in envelopes — downstream consumers do not care whether the source was a DB or a producer.",
            ),
        ],
    ),
    "IdempotentConsumer": (
        "Apply a message's effect at most once per logical key while tolerating at-least-once delivery from the transport.",
        ["InboxDeduplicator", "TransactionalOutbox", "DeadLetterRoute", "SignatureVerifier"],
        [
            (
                "Webhook receiver",
                ["SignatureVerifier", "InboxDeduplicator"],
                "Inbound request is verified for authenticity, then dedup'd by event id — replay attacks and duplicate deliveries are both neutralized.",
            ),
            (
                "Consume-then-publish",
                ["InboxDeduplicator", "TransactionalOutbox"],
                "Inbox dedup gates handle(); handle() writes state + outbox in one tx; downstream consumers dedupe similarly — the whole pipeline is effectively exactly-once.",
            ),
            (
                "Bounded retries",
                ["DeadLetterRoute", "RetryPolicy"],
                "Budget-bounded retries land on the DLR with full context; manual replay reuses the original idempotency key — zero double-apply risk.",
            ),
        ],
    ),
    "InboxDeduplicator": (
        "Record processed message identifiers in the consumer's database so redelivered messages are detected by a local primary-key conflict.",
        ["IdempotentConsumer", "TransactionalOutbox", "UnitOfWork", "EventStream"],
        [
            (
                "Local dedup gate",
                ["IdempotentConsumer", "UnitOfWork"],
                "The inbox row is inserted in the same transaction as the business effect; a duplicate redelivery fails on PK and the handler is skipped.",
            ),
            (
                "Effectively-once downstream",
                ["TransactionalOutbox", "IdempotentConsumer"],
                "Combined with an outbox, the consumer's own emitted events carry stable ids — the next hop in the pipeline dedupes the same way.",
            ),
            (
                "Replay-safe recovery",
                ["EventStream", "DeadLetterRoute"],
                "Replaying from the stream or from the DLR never double-applies; the inbox is the single source of truth for 'have I already done this?'.",
            ),
        ],
    ),
    "SagaOrchestrator": (
        "Coordinate a multi-step business transaction across services by driving each step and triggering compensations on partial failure.",
        ["WorkflowRun", "TransactionalOutbox", "DomainEvent", "IdempotentConsumer"],
        [
            (
                "Compensating transaction",
                ["WorkflowRun", "TransactionalOutbox"],
                "Each step and its compensation are durable workflow activities; partial failure triggers compensations in reverse order without a distributed 2PC.",
            ),
            (
                "Event-driven coordination",
                ["DomainEvent", "IdempotentConsumer"],
                "Saga reacts to domain events and emits commands via idempotent consumers — at-least-once delivery never causes double-compensation.",
            ),
            (
                "Observable long-running state",
                ["Tracer", "HealthProbe"],
                "Workflow spans cover the entire saga; unhealthy sagas surface on the readiness probe before a customer complaint.",
            ),
        ],
    ),
    "StreamSubject": (
        "Shared type for hierarchical subject names and pattern matching so routing, filtering, and authorization share one vocabulary.",
        ["EventEnvelope", "TopicBus", "EventStream", "RequestGuard"],
        [
            (
                "Hierarchical routing",
                ["EventEnvelope", "TopicBus"],
                "Subjects like `orders.v1.created` route to pattern subscribers without payload parsing; one primitive governs producer and consumer filters.",
            ),
            (
                "Subject-scoped authz",
                ["RequestGuard", "TopicBus"],
                "Subscription authorization is an allow-list over subject patterns — not a free-text filter audited line by line.",
            ),
            (
                "Stream partitioning",
                ["EventStream", "EventEnvelope"],
                "Subject + partition key together determine placement; the same subject never spans inconsistent partitions.",
            ),
        ],
    ),
    "TopicBus": (
        "Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to named subscribers.",
        ["EventEnvelope", "StreamSubject", "IdempotentConsumer", "DeadLetterRoute"],
        [
            (
                "Published-language fabric",
                ["EventEnvelope", "StreamSubject"],
                "Bus speaks only envelopes routed by subject; producers and consumers never care which broker implements the topic.",
            ),
            (
                "Safe fan-out",
                ["IdempotentConsumer", "DeadLetterRoute"],
                "Each subscriber dedupes by envelope id and shunts poison messages to the DLR; one bad consumer does not stall the fleet.",
            ),
            (
                "Cross-context integration",
                ["ContextMap", "AntiCorruptionLayer"],
                "Context boundaries publish through the bus; consumers translate via their own ACL — no synchronous coupling across contexts.",
            ),
        ],
    ),
    "TransactionalOutbox": (
        "Store outgoing messages in the same local transaction as the state change so a relay can publish them at-least-once without dual writes.",
        ["UnitOfWork", "IdempotentConsumer", "DomainEvent", "EventStream"],
        [
            (
                "Dual-write elimination",
                ["UnitOfWork", "DomainEvent"],
                "State change + event row commit together; a crash between the two is impossible — the relay republishes what the DB already saw.",
            ),
            (
                "End-to-end idempotency",
                ["IdempotentConsumer", "InboxDeduplicator"],
                "Outbox rows carry stable ids; downstream consumers dedupe — a relay retry never re-applies an effect.",
            ),
            (
                "Stream-bridged integration",
                ["EventStream", "ChangeDataCapture"],
                "The relay is the outbox tailer or CDC; either way, the stream sees exactly the events the database committed.",
            ),
        ],
    ),
}
