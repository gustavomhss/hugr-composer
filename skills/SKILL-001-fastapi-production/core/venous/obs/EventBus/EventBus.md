# EventBus

## What it does (plain language)

EventBus is an in-process publish/subscribe point for named framework and
application events — think `sql.query.executed`, `http.request`, or
`circuit_breaker.opened`. Producers call `publish(name, payload)`; consumers
(tracing, metrics, audit) call `subscribe(pattern, handler)` and receive every
matching event synchronously. It turns "I need to know when X happens" into a
subscription, instead of a monkey-patch.

## Purpose

In-process publish/subscribe point for named framework and application events
with structured payloads.

## When to use and when NOT to use

- USE: framework-internal instrumentation hooks (SQL, HTTP, cache, circuit
  breaker), lifecycle signals (`app.started`), cross-cutting concerns that
  need to attach without forking the framework.
- DO NOT USE: distributed pub/sub across processes or services — use a
  dedicated broker (Kafka, NATS) and the `events` namespace primitives
  (`TopicBus` / `EventEnvelope`).
- DO NOT USE: high-reliability delivery with at-least-once semantics —
  EventBus is best-effort in-process; subscriber crashes don't retry.
- DO NOT USE: as an audit trail — `AuditEvent` is tamper-evident; EventBus
  delivery is lossy by design (INV-02 isolates but does not retry).

## API surface

The catalog `api_signature` is the sole authority; see `EventBus.contract.json`
for the verbatim Protocol declaration. The implementation `EventBus.py`
re-declares the Protocol and provides `InMemoryEventBus` as a reference.

```python
from typing import Any, Callable, Mapping, Protocol

Subscriber = Callable[[str, Mapping[str, Any]], None]

class EventBus(Protocol):
    def publish(self, name: str, payload: Mapping[str, Any]) -> None: ...
    def subscribe(self, pattern: str, handler: Subscriber) -> Callable[[], None]: ...
```

### Pattern grammar

- A **literal segment** matches exactly (`sql.query` matches only `sql.query`).
- `*` matches a single segment (`sql.*` matches `sql.query`, but NOT
  `sql.query.slow`).
- `**` matches one or more trailing segments and may appear only as the last
  segment (`sql.**` matches `sql.query` and `sql.query.slow`).
- Event names use lowercase segments `[a-z][a-z0-9_]*` with at least one dot.

## Invariants

| ID | Rule |
|---|---|
| EVENTBUS_INV_01 | `publish()` MUST deliver to every matching subscriber synchronously (or through a declared executor); delivery order per subscriber is subscription order. |
| EVENTBUS_INV_02 | A subscriber that raises MUST NOT abort delivery to other subscribers; the error is reported to the observability sink. |
| EVENTBUS_INV_03 | The returned unsubscribe callable MUST be idempotent; calling it twice cannot remove a different subscription. |
| EVENTBUS_INV_04 | Event names MUST follow a dotted namespace; wildcards use the documented pattern syntax. |
| EVENTBUS_INV_05 | Payloads MUST be treated as immutable by subscribers; mutating a payload to signal another subscriber is FORBIDDEN. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `publish()` snapshots the matching-subscriber list under an internal lock,
  then dispatches synchronously outside the lock. This lets handlers re-enter
  `publish()` or `subscribe()` without deadlock.
- `subscribe()` and the returned unsubscribe callable are thread-safe via the
  same internal lock.
- The bus itself is stateless from the caller's perspective — the bus is a
  dep, not a singleton. Instances don't share state; discarding an instance
  discards its subscriptions.

## Operational characteristics (for SRE)

- Delivery is **synchronous** and **best-effort**. A hung subscriber blocks
  the publishing caller; pin handlers to fast, non-blocking work or offload
  to a worker pool inside the handler.
- Self-observability: `eventbus.publish.count`, `eventbus.delivery.latency`,
  `eventbus.subscriber.errors`, `eventbus.subscribers.active`.
- Failure policy: subscriber exceptions are caught and reported via an
  optional `error_sink` callable. Errors never propagate to the publisher.
- Subscriber cap: `MAX_TOTAL_SUBSCRIBERS = 10_000` per bus instance
  (global across all patterns), to catch runaway subscribe loops.

## Security considerations

- EventBus does NOT authenticate publishers or subscribers. Any in-process
  caller with a reference to the bus can publish and subscribe.
- Payloads flow verbatim (wrapped read-only) to every subscriber. Do NOT
  include secrets or unredacted PII in payloads — downstream observability
  sinks will surface them.
- Payload immutability (INV-05) prevents one subscriber from using the
  payload as a covert channel to signal another subscriber. Attempts to
  mutate raise `TypeError` which is caught by the bus and recorded.
- Event-name validation (INV-04) rejects malformed names up front, so
  attacker-controlled strings cannot inject hierarchy-breaking tokens
  (e.g. an upstream-constructed pattern cannot smuggle `**` mid-path).

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - Ruby on Rails 7 — `ActiveSupport::Notifications`
    (`guides.rubyonrails.org/active_support_instrumentation.html`).
  - Spring Boot 3.x — Application Events and `@EventListener`
    (`docs.spring.io/spring-boot/reference/features/spring-application.html`).

## Alternatives considered and rejected

- AOP / monkey-patching around framework methods — fragile and invisible at
  debug time.
- Dedicated callbacks per concern — combinatorial wiring as the number of
  concerns and framework hook points grows.
- External broker for in-process events — overkill latency and ops burden
  for events that never leave the process.

## Extension contract

Downstream tools publish named events via `publish()`; consumers subscribe
via `subscribe()` or an `@EventListener`-style decorator built on top of
`subscribe()`. Tracing, metrics, and audit plug in as providers that
subscribe to patterns (e.g. `*.active_record`) without touching producers.
Extensions must preserve the five invariants above. Semver: the Protocol
surface is v1; additive subscribers may register without breaking producers.

## Schema of `EventBus.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from EventBus import InMemoryEventBus

bus = InMemoryEventBus()

def on_sql(name: str, payload):
    duration = payload.get("duration", 0)
    # record to histogram, emit tracing span, etc.
    _ = (name, duration)

unsub = bus.subscribe("sql.*", on_sql)
bus.publish("sql.query", {"duration": 12})
unsub()  # idempotent
```

## Compose with:

- **Framework extensibility** → `LifecycleHook` + `StructuredLogger`
  Lifecycle phases publish on the bus; plugins subscribe without patching core — observability hooks compose cleanly.

- **Telemetry fan-out** → `MetricMeter` + `StructuredLogger`
  Metrics meters and log handlers subscribe to the same event without coupling; one source of truth drives multiple sinks.

- **In-process → bus bridge** → `EventEnvelope` + `TopicBus`
  Internal events convert to envelopes at the edge; cross-process subscribers see the same semantics through the topic bus.

- **Per-aggregate causal fan-out** → `CausalReorderBuffer` + `IdempotentConsumer`
  Events drained in causal order publish onto the in-process bus; downstream subscribers consume with the same at-most-once contract they already have.
