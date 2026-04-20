# DomainEvent

## What it does (plain language)

A DomainEvent is an immutable record of something that already happened in the
domain — "account.opened", "order.placed", "invoice.issued". Once constructed
it cannot be changed, re-dated, re-versioned, or retro-edited. Events are
collected during a unit of work, then published to downstream consumers only
after the business transaction commits. Each event carries a globally unique
`event_id` (UUID v7) so idempotent consumers can dedupe, and a per-aggregate
`version` that orders the stream of facts about one aggregate.

## Purpose

Record an immutable fact about something meaningful that happened in the
domain and publish it to downstream consumers without inventing a bespoke
payload shape, identifier strategy, or ordering protocol per tool.

## When to use and when NOT to use

- USE: persisting a domain decision that downstream services, audit trails,
  projections, sagas, or read models need to observe (account opened,
  payment captured, order placed, inventory reserved).
- USE: bridging an aggregate commit to an outbox / event bus — collect events
  pre-commit, publish post-commit.
- DO NOT USE: for commands or intents (`order.place`, `user.update`). Those
  are requests; a DomainEvent records what has already happened.
- DO NOT USE: for pure integration-layer messages with no domain meaning —
  use `EventEnvelope` (CloudEvents) directly.

## API surface

The catalog `api_signature` in `DomainEvent.contract.json` is the authority:

```python
class DomainEvent(Protocol):
    @property
    def event_id(self) -> str: ...
    @property
    def aggregate_id(self) -> str: ...
    @property
    def occurred_at(self) -> str: ...
    @property
    def version(self) -> int: ...
    @property
    def payload(self) -> Mapping[str, Any]: ...
```

The reference implementation `FrozenDomainEvent` is a frozen dataclass that
validates every attribute on construction and freezes the payload transitively
with `MappingProxyType`. Three collaborators ship alongside:

- `SchemaRegistry` — enforces DE-INV-05 additive-only schema evolution
  across `(event_type, schema_version)` pairs.
- `AggregateEventStream` — pre-commit collector + post-commit publisher with
  strict per-aggregate version monotonicity (DE-INV-04).
- `InMemoryDedupSet` — reference oracle for idempotent consumers keyed on
  `event_id` (DE-INV-02).

## Invariants

| ID | Rule |
|---|---|
| DE_INV_01 | A DomainEvent MUST be immutable after construction; mutation or retroactive edit of any attribute is FORBIDDEN. Payload is transitively frozen (`MappingProxyType` + tuples for lists). |
| DE_INV_02 | `event_id` MUST be a lowercase RFC 9562 UUID v7 so idempotent consumers CAN dedupe and two distinct facts SHALL never share an id. |
| DE_INV_03 | The event NEVER carries commands or intents; `event_type` is a dotted past-tense fact, and imperative verbs (create, update, delete, place, process, …) are FORBIDDEN as the terminal segment. |
| DE_INV_04 | `version` SHALL increment by exactly one per aggregate stream and is the ordering key; gaps, duplicates, and retroactive inserts are FORBIDDEN. |
| DE_INV_05 | Schema evolution within an `event_type` MUST be additive; a `schema_version` bump CANNOT drop or rename fields — use a new `event_type` instead. |

## Invariant → test mapping

Each invariant has three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}` in `test_DomainEvent.py`.
See `invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `AggregateEventStream.stage` serialises access to the version counter under
  an internal lock so concurrent stagers on the SAME aggregate never observe
  a race on `version`.
- `flush()` snapshots pending events under the lock and calls `publish_fn`
  OUTSIDE the lock so a slow publisher cannot deadlock stagers on a
  different aggregate.
- `SchemaRegistry.register` is locked so concurrent registration from
  multiple threads is safe; re-registration with an identical descriptor is
  idempotent.
- A stream is scoped to one logical process / region. Cross-region ordering
  is outside this primitive's remit — combine with a partitioned log.

## Operational characteristics (for SRE)

- Failed publishers do NOT advance the watermark: if `publish_fn` raises mid
  batch, `last_version` stays put and the unpublished events remain pending,
  so retry is safe (at-least-once).
- Dedup is the consumer's responsibility; the primitive guarantees `event_id`
  uniqueness and provides `InMemoryDedupSet` as the reference oracle.
- Self-observability: `domain.event.published` (counter, `aggregate_type` +
  `event_type` labels), `domain.event.rejected` (counter, `invariant_id`
  label), `domain.event.stream.pending` (gauge), `domain.event.publish.duration`
  (histogram, ms).
- A sustained rise in `domain.event.rejected{invariant_id="DE_INV_04"}` is
  the leading indicator of a buggy aggregate or a retry-loop attempting
  retroactive inserts.

## Security considerations

- Events are immutable AUDIT EVIDENCE. Never put secrets (passwords, tokens,
  raw PII) in the payload — the payload is preserved forever in the outbox
  and downstream sinks.
- `event_id` is a UUID v7, which leaks the creation time in its first 48
  bits by design. That is acceptable for business facts but callers handling
  secret workflows MUST consider whether creation-time leakage matters.
- The payload MAY contain arbitrary objects by reference. The validator
  freezes only known container types (dicts → `MappingProxyType`, lists →
  tuples). Custom objects passed in the payload MUST be themselves immutable
  — reviewers must flag any mutable domain entity placed inside an event.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Evans — *Domain-Driven Design* (2003), Chapter 8, Domain Events.
  - Vernon — *Implementing Domain-Driven Design* (2013), Chapter 8,
    pp. 281-320.
  - Richardson — *Microservices Patterns* (2018), Chapter 5,
    Event-driven architecture, event structure, pp. 162-170.

## Alternatives considered and rejected

- Integration-only messages — miss the domain semantics and couple to
  transport.
- Bare payload dicts — no stable identity, ordering, or schema contract.
- CRUD notifications — leak storage shape and lose intent.

## Extension contract

New event types extend `FrozenDomainEvent` by subclassing (or by using it
directly with a distinct `event_type`) and registering their schema with
`SchemaRegistry.register(SchemaDescriptor(event_type, schema_version,
required_fields))`. Schema evolution is additive: `schema_version = N+1`
MUST declare a required-field set that is a superset of `schema_version N`'s.
Removing or renaming fields requires a new `event_type`. Publishers MUST
call `SchemaRegistry.validate_event(evt)` (or use `AggregateEventStream`
wired to a registry) before releasing the event to downstream consumers.

## Schema of `DomainEvent.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from DomainEvent import (
    AggregateEventStream,
    FrozenDomainEvent,
    SchemaDescriptor,
    SchemaRegistry,
)

registry = SchemaRegistry()
registry.register(SchemaDescriptor("account.opened", 1, frozenset({"currency"})))
stream = AggregateEventStream(registry)

def open_account(aggregate_id: str, currency: str) -> None:
    evt = FrozenDomainEvent(
        event_id="018f5c2a-7b3d-7d8a-9e1c-2b4c5d6e7f81",
        aggregate_id=aggregate_id,
        occurred_at="2025-01-01T00:00:00Z",
        version=1,
        payload={"currency": currency},
        aggregate_type="Account",
        event_type="account.opened",
        schema_version=1,
    )
    stream.stage(evt)
    # ... business transaction commits ...
    stream.flush(event_bus.publish)
```

## Compose with:

- **Aggregate-emitted facts** → `Aggregate` + `TransactionalOutbox`
  Aggregates raise events on state change; the outbox commits them with the state — no event ships without its corresponding mutation.

- **Typed published language** → `EventEnvelope` + `TopicBus`
  Events travel inside a CloudEvents envelope so schema, source, and id are wire-level — consumers in other contexts never speak raw dict.

- **Event-driven integration** → `TopicBus` + `IdempotentConsumer`
  Subscribers consume through idempotent consumers; at-least-once from the bus becomes effectively exactly-once at the handler.
