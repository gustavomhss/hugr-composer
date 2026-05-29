"""WP-17 — curated compose-data entries for the `data` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === data`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== data
    "Aggregate": (
        "Define a consistency boundary around a cluster of entities and value objects governed by a single root that enforces invariants.",
        ["Repository", "UnitOfWork", "ValueObject", "DomainEvent"],
        [
            (
                "Transactional consistency",
                ["Repository", "UnitOfWork"],
                "All mutations to the aggregate flow through the root and commit atomically through the UoW — no child entity can be modified outside the root's invariants.",
            ),
            (
                "Immutable inner model",
                ["ValueObject", "Specification"],
                "Aggregate state is composed of value objects; selection predicates are Specifications — the internal structure never leaks as ORM types.",
            ),
            (
                "Event-sourced commits",
                ["DomainEvent", "TransactionalOutbox"],
                "Each aggregate change emits a domain event; the outbox guarantees the event ships if and only if the state change committed.",
            ),
        ],
    ),
    "AntiCorruptionLayer": (
        "Translate between a local model and a foreign or legacy model so upstream semantics cannot leak into the downstream domain.",
        ["BoundedContext", "ContextMap", "OutboundBinding", "ValueObject"],
        [
            (
                "Upstream translation",
                ["ContextMap", "OutboundBinding"],
                "The ACL owns the inbound mapping declared by the context map; upstream schema churn stays contained to one adapter file.",
            ),
            (
                "Conformist escape hatch",
                ["BoundedContext", "ValueObject"],
                "Foreign DTOs are turned into local value objects at the boundary — downstream code never imports upstream types.",
            ),
            (
                "Legacy strangulation",
                ["OutboundBinding", "CircuitBreaker"],
                "Calls to the legacy system go through the ACL behind a breaker so the new context degrades predictably when the legacy is down.",
            ),
        ],
    ),
    "BoundedContext": (
        "Declare the explicit linguistic and model boundary within which one ubiquitous language and one set of invariants apply.",
        ["ContextMap", "AntiCorruptionLayer", "Aggregate", "DomainEvent"],
        [
            (
                "Language isolation",
                ["Aggregate", "ValueObject"],
                "Inside the context, one term means one thing; aggregates and value objects are named in the context's ubiquitous language without qualifiers.",
            ),
            (
                "Explicit integration",
                ["ContextMap", "AntiCorruptionLayer"],
                "Every cross-context call routes through an ACL named in the context map — silent cross-context imports are prevented at the module boundary.",
            ),
            (
                "Published events",
                ["DomainEvent", "TopicBus"],
                "Events emitted by a context form its published language; other contexts subscribe through the bus and translate via their own ACL.",
            ),
        ],
    ),
    "ChangeDataCapture": (
        "Publish an ordered stream of row-level changes from a source database so downstream systems can consume mutations without double-writing.",
        ["EventStream", "TransactionalOutbox", "MaterializedView", "IdempotentConsumer"],
        [
            (
                "Log-based outbox alternative",
                ["TransactionalOutbox", "EventStream"],
                "CDC reads the DB commit log as the single source of truth; downstream consumers see the same order as the database — no application-level outbox poller.",
            ),
            (
                "Derived read model",
                ["MaterializedView", "IdempotentConsumer"],
                "A view subscribes to CDC and rebuilds itself idempotently from a snapshot + ongoing stream; reprocessing never produces drift.",
            ),
            (
                "Cross-store replication",
                ["EventStream", "AntiCorruptionLayer"],
                "CDC feeds a downstream context through its ACL so the target schema never has to mirror the source schema.",
            ),
        ],
    ),
    "ConfigBinding": (
        "Bind a namespaced slice of runtime configuration to a typed record, validated at startup so misconfiguration fails fast, not at request time.",
        ["DiContainer", "SecretsVault", "LifetimeScope", "FeatureToggle"],
        [
            (
                "Fail-fast startup",
                ["DiContainer", "LifetimeScope"],
                "DI resolution requires every declared binding; a missing or mistyped value crashes boot instead of surfacing as a 500 under load.",
            ),
            (
                "Secrets vs config split",
                ["SecretsVault", "FeatureToggle"],
                "ConfigBinding holds non-secret, per-env shape; secrets come from the vault at request time; feature toggles drive per-cohort behavior — three distinct lifecycles, three distinct tools.",
            ),
            (
                "Typed reload",
                ["LifetimeScope", "AuditEvent"],
                "Hot-reload of config rebinds the typed record and emits an audit event with a diff — no operator 'maybe I changed that flag' ambiguity.",
            ),
        ],
    ),
    "DataMapper": (
        "Move state between in-memory domain objects and rows in storage while keeping both ignorant of each other's shape.",
        ["Repository", "UnitOfWork", "IdentityMap", "ValueObject"],
        [
            (
                "Classic mapper sandwich",
                ["Repository", "UnitOfWork"],
                "Repository is the collection-style façade; DataMapper is the translation layer; UoW is the transaction — each seam does exactly one job.",
            ),
            (
                "Identity-preserving load",
                ["IdentityMap", "Repository"],
                "Loaded aggregates register in the identity map; a second load returns the same instance — mapper output is cached by identity, not duplicated.",
            ),
            (
                "Value-object hydration",
                ["ValueObject", "Specification"],
                "Rows become frozen value objects at hydration; Specifications translate into storage queries — the domain never sees raw columns.",
            ),
        ],
    ),
    "DiContainer": (
        "Registry that resolves a typed request for a dependency into a constructed instance obeying the declared lifetime scope.",
        ["LifetimeScope", "ConfigBinding", "Repository", "UnitOfWork"],
        [
            (
                "Scoped per-request wiring",
                ["LifetimeScope", "UnitOfWork"],
                "Request-scoped UoW and repositories are resolved once per request and disposed at pipeline exit — handlers never 'new' a transaction.",
            ),
            (
                "Typed configuration graph",
                ["ConfigBinding", "LifetimeScope"],
                "Config records are singleton bindings; their consumers are request-scoped — hot-reload rewires consumers without rebooting singletons.",
            ),
            (
                "Testable seams",
                ["Repository", "OutboundBinding"],
                "Every integration is a registered interface; tests swap in fakes without touching production wiring — integration seams are mockable by construction.",
            ),
        ],
    ),
    "IdentityMap": (
        "Cache loaded domain objects by identity inside one session so the same row is never represented twice and in-memory mutations are visible.",
        ["Repository", "UnitOfWork", "DataMapper", "Aggregate"],
        [
            (
                "Consistent-read guarantee",
                ["Repository", "UnitOfWork"],
                "Within one UoW, two `get(id)` calls return the same instance — mutations applied to one reference are visible to all readers.",
            ),
            (
                "No lost updates",
                ["DataMapper", "UnitOfWork"],
                "Mapper flushes only tracked instances; mutations applied outside the map are rejected at commit rather than silently skipped.",
            ),
            (
                "Aggregate coherence",
                ["Aggregate", "Repository"],
                "The map holds aggregate roots; child entities are reached through the root — the same root is shared across all child accesses in the session.",
            ),
        ],
    ),
    "LegalHold": (
        "Suspend retention-driven deletion and erasure cascades for records covered by a litigation or regulatory hold.",
        ["RetentionPolicy", "DataSubjectRequest", "AuditEvent", "TamperEvidentAuditLog"],
        [
            (
                "Hold-first delete",
                ["RetentionPolicy", "AuditEvent"],
                "Every retention sweep calls `covers(record_id)` before deleting; a covered record stays and a deferred-delete audit is emitted with the hold id.",
            ),
            (
                "DSR survival",
                ["DataSubjectRequest", "AuditEvent"],
                "An erasure DSR on a held subject produces a documented deferral instead of a deletion; the subject is notified the hold exists (where lawful).",
            ),
            (
                "Hold lifecycle",
                ["TamperEvidentAuditLog", "AuditEvent"],
                "Open, extend, and release events are sealed into the audit chain so 'show me who released this hold and when' is one signed query.",
            ),
        ],
    ),
    "LifetimeScope": (
        "Typed enumeration that fixes how long a resolved instance lives: the whole process, one request, or one operation.",
        ["DiContainer", "ConfigBinding", "UnitOfWork", "RequestContext"],
        [
            (
                "Per-request UoW",
                ["DiContainer", "UnitOfWork"],
                "Request scope owns the UoW; entering the pipeline creates it, exiting disposes it — handlers never leak transactions across requests.",
            ),
            (
                "Singleton config",
                ["ConfigBinding", "DiContainer"],
                "Typed config is singleton; request-scoped consumers re-read it without re-parsing — hot-reload of config is O(1) per request.",
            ),
            (
                "Operation-scoped tracing",
                ["RequestContext", "Tracer"],
                "Operation scope matches span scope; spawned spans inherit request context without handlers threading anything by hand.",
            ),
        ],
    ),
    "MaterializedView": (
        "Maintain a pre-computed query result kept up to date by an incremental feed so read queries never recompute the whole source.",
        ["ChangeDataCapture", "EventStream", "IdempotentConsumer", "Specification"],
        [
            (
                "CDC-driven rebuild",
                ["ChangeDataCapture", "IdempotentConsumer"],
                "View subscribes to CDC; rebuilds are idempotent — a replay from snapshot produces a byte-identical view without double-applying effects.",
            ),
            (
                "CQRS read model",
                ["EventStream", "Specification"],
                "Commands mutate aggregates; a projector subscribes to the event stream and maintains the view; Specifications are the only query surface — no SQL leaks.",
            ),
            (
                "Stale-bounded reads",
                ["MetricMeter", "HealthProbe"],
                "View freshness is a first-class metric; readiness probe goes unhealthy if lag exceeds SLO — stale reads are a visible failure mode.",
            ),
        ],
    ),
    "PiiClassification": (
        "Tag every persisted field with a sensitivity class so serialization goes through one central mask that redacts above the audience's cap.",
        ["RetentionPolicy", "DataSubjectRequest", "DataResidencyPolicy", "OutputEncoder"],
        [
            (
                "Mask-at-the-edge",
                ["OutputEncoder", "AccessLog"],
                "Outbound responses pass through mask(audience); the read is then accounted in the access log with the audience — de-identification is mechanical, not a review item.",
            ),
            (
                "Classification-driven residency",
                ["DataResidencyPolicy", "RetentionPolicy"],
                "Class declares TTL and allowed regions; a single tag drives storage limitation and cross-border transfer rules.",
            ),
            (
                "DSR scope",
                ["DataSubjectRequest", "LegalHold"],
                "Erasure walks every store holding a given class; LegalHold overrides deletion where lawful — one map drives both.",
            ),
        ],
    ),
    "Repository": (
        "Mediate between the domain model and the data-mapping layer with a collection-like interface scoped to one aggregate root.",
        ["UnitOfWork", "IdentityMap", "Specification", "Aggregate"],
        [
            (
                "DDD persistence sandwich",
                ["UnitOfWork", "IdentityMap"],
                "Repo enlists every mutation with the active UoW and consults the identity map first on reads — no silent direct writes and no stale in-memory copies.",
            ),
            (
                "Query via Specification",
                ["Specification", "Aggregate"],
                "find() accepts a Specification and returns only aggregate roots; ORM syntax never crosses the boundary.",
            ),
            (
                "Aggregate-only surface",
                ["Aggregate", "DomainEvent"],
                "One repo per root; child entities are reached through navigation; mutations emit domain events the outbox relays — the repo stays pure.",
            ),
        ],
    ),
    "Specification": (
        "Encapsulate a predicate over a domain object so selection, validation, and criteria share one executable definition.",
        ["Repository", "Aggregate", "ValueObject", "DataMapper"],
        [
            (
                "Query + validate twins",
                ["Repository", "Aggregate"],
                "The same Specification filters `find()` results and validates admission to an aggregate invariant — server-side and in-memory checks cannot drift.",
            ),
            (
                "Composable predicates",
                ["ValueObject", "DataMapper"],
                "Spec composition (and/or/not) builds a new value object; the mapper translates the tree to the storage dialect on the fly.",
            ),
            (
                "Domain-only vocabulary",
                ["Repository", "AntiCorruptionLayer"],
                "Specifications speak only domain terms; foreign filters are translated by the ACL before the repo ever sees them.",
            ),
        ],
    ),
    "TransactionalBatch": (
        "Offer cross-key atomicity against one state store without application-level two-phase commit or compensating transactions.",
        ["UnitOfWork", "KeyValueBucket", "TransactionalOutbox", "IdempotentConsumer"],
        [
            (
                "All-or-nothing writes",
                ["KeyValueBucket", "UnitOfWork"],
                "Multiple keys commit atomically; optimistic revisions on each key turn conflicts into explicit retries rather than partial application.",
            ),
            (
                "State + outbox together",
                ["TransactionalOutbox", "UnitOfWork"],
                "The batch includes the outbox row; the downstream event ships if and only if the state change committed — no phantom events.",
            ),
            (
                "Idempotent retry",
                ["IdempotentConsumer", "RetryPolicy"],
                "Batch ids act as idempotency keys so a retried commit is a no-op on the second apply — safe to retry without bookkeeping.",
            ),
        ],
    ),
    "UnitOfWork": (
        "Track object changes during a business transaction and flush them to storage as one atomic commit or rollback.",
        ["Repository", "IdentityMap", "TransactionalOutbox", "LifetimeScope"],
        [
            (
                "Transactional consistency",
                ["Repository", "IdentityMap"],
                "Every mutation enlists with the active UoW; the identity map holds the in-flight graph; a rollback leaves memory and storage aligned.",
            ),
            (
                "Outbox in the same tx",
                ["TransactionalOutbox", "DomainEvent"],
                "Domain events written to the outbox commit with the state change; the relay publishes them out-of-band — at-least-once delivery without dual writes.",
            ),
            (
                "Request-scoped lifetime",
                ["LifetimeScope", "DiContainer"],
                "UoW is resolved per request by the container; pipeline exit triggers commit or rollback — handlers never forget to close a transaction.",
            ),
        ],
    ),
    "ValueObject": (
        "Represent a descriptive concept whose identity is defined by its attributes and which is immutable once constructed.",
        ["Aggregate", "Specification", "DataMapper", "InputValidator"],
        [
            (
                "Immutable domain state",
                ["Aggregate", "Specification"],
                "Aggregates compose value objects; state changes replace them rather than mutate — invariants are checked at construction, once.",
            ),
            (
                "Validated hydration",
                ["InputValidator", "DataMapper"],
                "Inbound payloads become value objects through the validator; the mapper re-emits them to storage — invalid state is unrepresentable at the type level.",
            ),
            (
                "Pure equality",
                ["Specification", "DomainEvent"],
                "VO equality is structural, so event payloads and specification matches compare cleanly across processes — no hidden identity.",
            ),
        ],
    ),
}
