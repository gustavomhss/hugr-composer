# StreamSubject

## What it does (plain language)

StreamSubject is the dot-separated routing name that event producers send to
and event consumers filter on. One character class, two wildcards, and a
reserved-prefix rule give the whole fan-out system predictable behavior.

## Purpose

Provide one shared type for hierarchical subject names and pattern matching
so routing, filtering, and multi-tenant isolation are implemented once
instead of in every consumer.

## When to use and when NOT to use

- USE: broker subjects, stream capture filters, consumer routing predicates,
  tenant-scoped fan-out.
- DO NOT USE: regex-style routing — use a dedicated matcher; `StreamSubject`
  deliberately forbids regex.
- DO NOT USE: arbitrary tag metadata — that belongs on `EventEnvelope`.

## API surface

See `StreamSubject.contract.json` for the catalog Protocol. The
implementation adds a `SubjectRegistry` for stateful tests that proves
invariants under subscription churn.

## Invariants

| ID | Rule |
|---|---|
| SS_INV_01 | Subject name tokens MUST NOT contain null, whitespace, `.`, `*`, or `>`. |
| SS_INV_02 | The `>` wildcard SHALL appear only as the final token of a pattern. |
| SS_INV_03 | The `*` wildcard MUST match exactly one token, never zero or multiple. |
| SS_INV_04 | Names starting with `$` are FORBIDDEN for user subjects. |
| SS_INV_05 | Publishers ALWAYS send to a fully specified subject. |

## Formal model

`StreamSubject.tla` declares a TLC-verified bounded subscription registry
and `DeliveryMatches` safety invariant: every delivered pair `(subject,
pattern)` satisfies the matching oracle. Maps to SS_INV_02 and SS_INV_03.

## Invariant → test mapping

See `invariant_bindings.json`.

## Thread and async safety

- `StreamSubject` is a frozen dataclass — immutable and thread-safe.
- `SubjectRegistry` serialises mutations under `threading.Lock`.

## Operational characteristics (for SRE)

- Matching is O(n) in pattern token count; p99 is well under 1µs for typical
  4-token patterns.
- Self-observability: `subject.publications.total`, `subject.fanout.size`
  histogram, `subject.subscriptions.active` gauge.

## Security considerations

- System prefix (`$`) is reserved; user subjects with that prefix are
  rejected to prevent system-subject shadowing (e.g. `$SYS.ACCOUNT.*`).
- Token chars exclude whitespace and null to block log / header injection.
- Publishers cannot publish to wildcard subjects — this prevents rogue
  publishers from flooding every subscription.

## Provenance

- Source agent: Agent #2 DISTRIBUTED.
- Primary sources: NATS 2.10 Subjects concept documentation; JetStream
  subject mapping transformations.

## Alternatives considered and rejected

- Plain string equality topics — lose hierarchical fan-out.
- Regex-based routing — expressive but rejects NATS-style constraints and
  costs more at scale.

## Extension contract

Extend routing by composing a `StreamSubject` with a predicate filter or by
registering a subject-mapping adapter on stream ingestion. Custom taxonomies
plug in by implementing a naming convention validator that wraps the
constructor.

## Usage

```python
from StreamSubject import StreamSubject, SubjectRegistry

reg = SubjectRegistry()
reg.subscribe("orders.>", "fulfillment")
count = reg.publish(StreamSubject("orders.created.v1"))
```

## Compose with:

- **Hierarchical routing** → `EventEnvelope` + `TopicBus`
  Subjects like `orders.v1.created` route to pattern subscribers without payload parsing; one primitive governs producer and consumer filters.

- **Subject-scoped authz** → `RequestGuard` + `TopicBus`
  Subscription authorization is an allow-list over subject patterns — not a free-text filter audited line by line.

- **Stream partitioning** → `EventStream` + `EventEnvelope`
  Subject + partition key together determine placement; the same subject never spans inconsistent partitions.
