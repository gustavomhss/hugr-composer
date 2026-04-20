# EventEnvelope

## What it does (plain language)

EventEnvelope is the canonical shape that every event in the system carries.
It names the five required fields of the CloudEvents 1.0 standard (id, source,
type, specversion, plus optional subject/time/extensions/data) and enforces
the dedup identity tuple `(source, id)`. Every producer uses this envelope so
that any consumer — regardless of transport — parses the same structure.

## Purpose

Provide a frozen, validated dataclass that captures the CloudEvents 1.0.2
canonical shape and makes consumer-side dedup reliable by pinning `(source, id)`
as the stable occurrence identity.

## When to use and when NOT to use

- USE: every domain event crossing a process, queue, or network boundary.
- DO NOT USE: tightly-coupled in-process callbacks where no audit or replay
  is needed — those can stay as function calls.
- DO NOT USE: for log records or metrics — those primitives have their own
  contracts and cardinality policies.

## API surface

`EventEnvelope.contract.json` holds the verbatim `PrimitiveSpec` from the
research catalog. The implementation declares:

- `EventEnvelope` — frozen dataclass with required `id`, `source`, `type`, and
  optional CE attributes plus a typed `extensions` map.
- `InMemoryDedupSet` — reference consumer-side dedup oracle proving EE_INV_01
  end-to-end.
- `validate_*` helpers — pure functions that back `__post_init__`.

## Invariants

| ID | Rule |
|---|---|
| EE_INV_01 | Producers MUST make the tuple `(source, id)` unique per distinct occurrence so consumers can deduplicate. |
| EE_INV_02 | Resending the same logical event ALWAYS reuses the original id so retries do not appear as new occurrences. |
| EE_INV_03 | `specversion` MUST equal `'1.0'` for envelopes produced under this contract. |
| EE_INV_04 | Extension attribute names MUST match CloudEvents naming rules and CANNOT collide with reserved core attribute names. |
| EE_INV_05 | `time` when present SHALL be an RFC 3339 timestamp in UTC (`Z` or `+00:00` suffix only). |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `EventEnvelope` is frozen — instances are safe to share across threads /
  tasks.
- `InMemoryDedupSet` is NOT thread-safe by itself; callers MUST serialize
  access (e.g. with `threading.Lock`) when used across threads. The chaos
  suite demonstrates this pattern.

## Operational characteristics (for SRE)

- Construction cost is dominated by regex checks on `id`, `source`, `type`,
  optional `time`, and extension keys. 10k envelopes/sec on a single core is
  comfortable.
- Self-observability: producers emit `event.envelope.constructed.total` and
  `event.envelope.rejected.total` (labelled by `invariant_id`). Consumers
  emit `event.envelope.dedup.decision` (labelled `outcome={accepted,duplicate}`).
  Full schema in `observability_schema.json`.
- Failure policy: validation failure raises `EventEnvelopeInvariantError`
  synchronously. There is no retry loop inside the primitive; callers decide.

## Security considerations

- `id`, `source`, `type`, `subject` MUST NOT contain null bytes; the validator
  rejects them as a defense against log / header injection.
- `extensions` values MUST be strings; nested structures are rejected so the
  envelope cannot smuggle an un-sanitized payload through attribute space.
- `time` MUST be UTC — accepting arbitrary offsets would let an attacker
  backdate or future-date events past audit thresholds.
- The reserved-name set blocks extensions named `id`, `source`, `type`, etc.,
  which would otherwise shadow core attributes after wire serialization.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary sources:
  - CloudEvents 1.0.2 Core Specification
    (`github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md`):
    Required Attributes, Optional Attributes, Extension Context Attributes.
  - RFC 3339 § 5.6 (date-time format) and § 4.2 (UTC offset).

## Alternatives considered and rejected

- Plain JSON blobs per producer — rejected because it breaks consumer dedup
  and forces each consumer to re-implement occurrence identity.
- AsyncAPI-style schema registry coupling — rejected because it pins the
  producer to a transport earlier than necessary; CloudEvents is deliberately
  transport-agnostic.

## Extension contract

Add custom attributes by registering an extension name in the `extensions`
map that satisfies the CloudEvents Extension Context Attributes rules
(`^[a-z0-9]{1,20}$`, not in the reserved core set). Consumers extend by
composing filters on `type` or `subject` via a decorator that wraps the
handler. Extensions MUST preserve the five invariants above.

## Schema of `EventEnvelope.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from EventEnvelope import EventEnvelope, InMemoryDedupSet

def publish(dedup: InMemoryDedupSet, payload: bytes) -> bool:
    envelope = EventEnvelope(
        id="order-42",
        source="/svc/orders",
        type="com.example.order.created",
        time="2026-04-18T12:00:00Z",
        extensions={"traceid": "4bf92f3577b34da6a3ce929d0e0e4736"},
        data=payload,
    )
    return dedup.accept(envelope)
```

## Compose with:

- **Wire-format contract** → `DomainEvent` + `TopicBus`
  Envelope is the single on-the-wire shape across brokers; producers and consumers never negotiate format per integration.

- **Subject-based routing** → `StreamSubject` + `TopicBus`
  The subject field drives hierarchical routing; consumers subscribe by pattern without parsing payloads.

- **Dedupe by envelope id** → `IdempotentConsumer` + `InboxDeduplicator`
  The envelope id is the canonical idempotency key; any consumer can dedupe by id without inventing its own hashing.
