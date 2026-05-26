# AGENT 3 — PATTERNS

Research cohort output for the HuGR Arsenal venous-system catalog.

- Agent: 3 (`PATTERNS`)
- Namespaces owned: `data`, `events`, `api`
- Canonical corpus: Fowler PEAA (2002), Evans DDD (2003), Richardson MP (2018), Kleppmann DDIA (2017), Vernon IDDD (2013)
- Deliverable status: `check_deliverable.py --agent 3` → exit 0
- Primitives: 20 • Unique sources: 7 • Insights: 7 • Gaps: 10

## Scope

This agent extracts the enterprise, DDD, microservices, and data-intensive
patterns that must become **shared primitives** rather than per-tool code. Three
concerns cut through every chapter read: **atomicity** (how we resist the
dual-write trap), **identity** (how we name the thing a change belongs to), and
**boundary discipline** (how we stop models from bleeding across teams).

Out of scope — and delegated to other agents — are language-specific
implementations, framework mappings, and tutorial-grade examples.

## The 20 primitives

Each primitive below is declared as a Python Protocol in the JSON deliverable
with full invariants, extension contract, consumption example, and citations.
The table groups them by namespace and maps each to its canonical source.

### `data` namespace (11)

| Primitive | Anchored in | Role |
|---|---|---|
| `UnitOfWork` | Fowler PEAA Ch. 11 | One commit boundary per business transaction. |
| `Repository` | Evans DDD Ch. 6, Fowler PEAA Ch. 18 | Collection-like access to aggregate roots. |
| `IdentityMap` | Fowler PEAA Ch. 11 | Referential identity of loaded objects per session. |
| `DataMapper` | Fowler PEAA Ch. 10 | Domain objects that stay ignorant of storage. |
| `Specification` | Evans DDD Ch. 9, Fowler/Evans white paper | Reusable predicate over a domain type. |
| `Aggregate` | Evans DDD Ch. 6, Vernon IDDD Ch. 10 | Consistency boundary with a single root. |
| `ValueObject` | Evans DDD Ch. 5, Vernon IDDD Ch. 6 | Immutable attribute-equality type. |
| `BoundedContext` | Evans DDD Ch. 14, Vernon IDDD Ch. 2 | Linguistic/model boundary. |
| `AntiCorruptionLayer` | Evans DDD Ch. 14, Vernon IDDD Ch. 3 | Translator against foreign model leak. |
| `MaterializedView` | Kleppmann DDIA Ch. 11, Richardson MP Ch. 7 | Incrementally maintained read model. |
| `ChangeDataCapture` | Kleppmann DDIA Ch. 11, Richardson MP Ch. 3 | Ordered mutation stream from the source of truth. |

### `events` namespace (7)

| Primitive | Anchored in | Role |
|---|---|---|
| `DomainEvent` | Evans DDD, Vernon IDDD Ch. 8, Richardson MP Ch. 5 | Immutable domain fact with stable id. |
| `TransactionalOutbox` | Richardson MP Ch. 3, Kleppmann DDIA Ch. 11 | Atomic state-and-message write. |
| `InboxDeduplicator` | Richardson MP Ch. 3, Kleppmann DDIA Ch. 11 | Exactly-once effects over at-least-once delivery. |
| `IdempotentConsumer` | Richardson MP Ch. 3, Kleppmann DDIA Ch. 11 | Consumer contract for replay safety. |
| `SagaOrchestrator` | Richardson MP Ch. 4, Garcia-Molina/Salem 1987 | Coordinated cross-service transaction + compensation. |
| `EventStream` | Kleppmann DDIA Ch. 11, Richardson MP Ch. 3 | Partitioned, replayable append-only log. |
| `EventSourcedStore` | Fowler 'Event Sourcing' essay, Vernon IDDD App. A, Richardson MP Ch. 6 | Aggregate state as folded event history. |

### `api` namespace (2)

| Primitive | Anchored in | Role |
|---|---|---|
| `ContextMap` | Evans DDD Ch. 14, Vernon IDDD Ch. 3 | Catalog of inter-context integration kinds. |
| `CommandQuerySeparator` | Richardson MP Ch. 7, Fowler PEAA Ch. 9, Vernon IDDD Ch. 4 | Explicit write/read split at the API layer. |

## Cross-cutting insights

1. Atomicity is the unifying concern: `UnitOfWork`, `TransactionalOutbox`,
   `InboxDeduplicator`, and `EventSourcedStore` all refuse the dual-write trap
   by co-locating a side-effect's record with the state change in one
   transaction.
2. Identity is explicit infrastructure: `IdentityMap`, `Aggregate.id`,
   `DomainEvent.event_id`, and `EventStream` partition keys each declare who
   or what a change belongs to so replay and dedupe remain sound.
3. Boundary discipline cascades: Evans's `BoundedContext`, Vernon's
   `ContextMap`, and the `AntiCorruptionLayer` together prevent the silent
   model drift that Richardson's saga and CQRS primitives assume is already
   handled.
4. Immutability is the cheap trick that unlocks replay: `ValueObject`,
   `DomainEvent`, and `EventStream` all forbid in-place mutation, which is
   precisely what makes `MaterializedView` rebuilds and `EventSourcedStore`
   folds deterministic.
5. At-least-once delivery is assumed end-to-end: `TransactionalOutbox`,
   `IdempotentConsumer`, `InboxDeduplicator`, and `SagaOrchestrator` all treat
   duplicates as the normal case and encode exactly-once as a property of the
   consumer, not the transport (Kleppmann Ch. 11).
6. `Specification`, `Repository`, and `CommandQuerySeparator` share one
   refactor path: they move policy out of callsites into a named object that
   tests, optimizers, and projections can all inspect without re-reading SQL
   strings.
7. CDC and Event Sourcing are rival origins for the same downstream primitives
   (`MaterializedView`, `EventStream`); the choice determines whether the log
   is derived from rows or whether rows are derived from the log, but the
   consumer contract stays identical.

## Source coverage

| Source | Primitives citing |
|---|---|
| Richardson "Microservices Patterns" (2018) | 9 |
| Vernon "Implementing Domain-Driven Design" (2013) | 8 |
| Evans "Domain-Driven Design" (2003) | 7 |
| Fowler "Patterns of Enterprise Application Architecture" (2002) | 6 |
| Kleppmann "Designing Data-Intensive Applications" (2017) | 6 |
| Fowler and Evans "Specifications" white paper (2002) | 1 |
| Garcia-Molina and Salem "Sagas" (1987) as cited in Richardson | 1 |

No source exceeds 70% of total primitive citations (max share: 9/37 ≈ 24%).

## Gaps observed in SKILL-001

The JSON deliverable's `gaps_observed` enumerates ten primitives the canonical
corpus treats as foundational that SKILL-001 does not currently expose as
shared primitives:

1. `UnitOfWork` as an explicit commit boundary.
2. `TransactionalOutbox` to eliminate dual writes.
3. `IdempotentConsumer` + `InboxDeduplicator` for consumer-side exactly-once.
4. `ContextMap` for integration topology.
5. `MaterializedView` + `ChangeDataCapture` for read-path consistency.
6. `Specification` as a reusable query predicate.
7. `SagaOrchestrator` for cross-tool workflows with compensation.
8. `EventSourcedStore` as an opt-in aggregate persistence strategy.
9. `CommandQuerySeparator` enforced at the API layer.
10. `AntiCorruptionLayer` to guard the domain from third-party SDK types.

These gaps are the input set for the next phase: turning the catalog into
Arsenal tools that materialize each primitive with the invariants above.

## Provenance

Every primitive carries ≥1 `SourceCitation` with chapter- or page-level
locators. No vague citations ("the docs", "industry standard") were used. The
contract validator (`docs/research/contracts/briefing_contract.py`) enforces
this at schema time and is additionally cross-checked by the acceptance gate
(`validate_deliverable`) at delivery time.
