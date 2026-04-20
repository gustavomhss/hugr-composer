# SagaOrchestrator

## What it does (plain language)

A **saga** is a business transaction that spans multiple services and CANNOT
use a distributed lock. SagaOrchestrator drives that transaction one step at a
time: it emits a command asking the next participant to do its part, waits for
the participant's reply, and — if any step fails — it runs the previously
completed steps' **compensating actions** in strict reverse order to undo the
work. If the shipping service rejects an order after the payment has gone
through, the orchestrator issues a refund before marking the saga failed; the
customer never ends up charged for an undelivered order.

## Purpose

Coordinate a multi-step business transaction across services by driving each
step and triggering compensations when a later step fails.

## When to use and when NOT to use

- USE: any cross-service workflow that must succeed or fail as a whole but
  cannot use a distributed transaction (order placement, payment + shipping,
  account provisioning across services, multi-tenant onboarding).
- DO NOT USE: a single-aggregate write that fits inside one `UnitOfWork` — a
  saga is overkill and introduces asynchronous coordination complexity.
- DO NOT USE: workflows that demand strict linearizability across services —
  the saga model is explicitly eventually-consistent (SAGA-INV-04).

## API surface

The catalog `api_signature` in `SagaOrchestrator.contract.json` is the
authority. Callers:

1. Build a `SagaDefinition` and register each forward step with the
   `@sd.register("step_name", compensator=...)` decorator. Every step MUST
   declare a compensator — the registration itself rejects steps without one.
2. Create `InMemorySagaOrchestrator(definition, command_sink=my_bus)`.
3. Call `saga.start(correlation_id, input)` to begin. The orchestrator
   journals the state transition and emits the first `invoke_<step>` command
   through the sink.
4. As participants reply, call `saga.step(correlation_id, step_name, outcome)`.
   A dict `outcome` with `{"__saga_failed__": True, "reason": "..."}` flips
   the saga into compensation.
5. `saga.status(correlation_id)` returns `(state, completed_step_names)`.
6. `saga.compensate(correlation_id, from_step)` is an operator escape hatch
   that runs the tail's compensator (and every earlier compensator in reverse).

## State machine

| From           | On                         | To             |
|----------------|---------------------------|----------------|
| pending        | `start()`                  | running        |
| running        | step success (not last)    | running        |
| running        | step success (last)        | completed      |
| running        | step failure               | compensating   |
| running        | `compensate()`             | compensating   |
| compensating   | each compensator fires     | compensating   |
| compensating   | all compensators fired     | failed         |
| completed      | any further call           | (ignored)      |
| failed         | any further call           | (ignored)      |

`completed` and `failed` are terminal. Further `step()` or `compensate()` calls
on a terminal saga are a silent no-op so re-delivered messages from the bus
cannot cause a ghost advance.

## Invariants

| ID | Rule |
|---|---|
| SAGA_INV_01 | Every forward step MUST declare a compensating action, or the saga CANNOT include it. |
| SAGA_INV_02 | Compensation order SHALL be the reverse of the completed forward steps; out-of-order compensation is FORBIDDEN. |
| SAGA_INV_03 | The orchestrator's state transitions MUST be persisted atomically with the command it emits so crashes NEVER leave dangling sagas. |
| SAGA_INV_04 | A saga NEVER assumes strong consistency across services; all coordination SHALL be via asynchronous messages. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `InMemorySagaOrchestrator` serialises state mutations behind a reentrant
  lock. Step reports, compensations, and starts are all linearised so two
  threads racing to advance the same saga cannot produce duplicate
  compensations or skipped state transitions.
- The command sink is always invoked OUTSIDE the lock, so a sink that blocks
  on the network CANNOT deadlock the orchestrator.
- Idempotency is enforced on `(step_name, outcome_key)` — re-deliveries from
  the bus collapse to a single advance. This is the mechanical backbone of
  SAGA-INV-04.

## Operational characteristics (for SRE)

- Alerts: `rate(saga_outcomes_total{outcome="failed"}[5m])` rising is the
  primary SLO violation — a single failure is fine; a sustained rise is not.
- If the command sink is unavailable, the orchestrator STILL journals every
  state transition. Operators can replay the journal (`saga.journal_for(cid)`)
  to recover emitted-but-undelivered commands.
- `saga.active_count()` + `saga.known_correlations()` expose the working set
  for dashboards and capacity planning.
- A compensator that raises halts the saga in the `compensating` state (not
  `failed`) with `last_error` set, so an operator can resume after fixing the
  downstream service — compensation is never silently swallowed.

## Security considerations

- Outcomes are deep-copied on ingress; a malicious participant CANNOT smuggle
  a mutable reference that later rewrites journal records.
- `correlation_id` is used as-is; callers SHOULD use opaque UUIDs to prevent
  information leakage via audit logs.
- The `{"__saga_failed__": True}` sentinel is a dict key, not a flag on the
  message envelope — upstream filters SHOULD strip this key from untrusted
  participant replies if they might originate from external HTTP bodies.

## Provenance

- Source agent: Agent #3 PATTERNS
  (`docs/research/outputs/AGENT_3_PATTERNS.json`).
- Primary sources:
  - Richardson — *Microservices Patterns* (2018), Chapter 4, *Managing
    Transactions with Sagas*, pp. 114–149.
  - Garcia-Molina and Salem — *Sagas* (1987), as cited in Richardson
    Chapter 4, *Origins of Sagas*, pp. 114–117.

## Alternatives considered and rejected

- **Distributed 2PC (XA)** — long locks, poor failure modes, not supported
  across HTTP services. Rejected: blocks independent service deployment.
- **Pure choreography** — simpler start but compensation logic gets
  duplicated per participant. Rejected: no central place to reason about
  failure recovery.
- **Ignore partial failure** — silently corrupts cross-service state.
  Rejected as operationally indefensible.

## Extension contract

Downstream flows extend SagaOrchestrator by declaring a `SagaDefinition` and
registering handlers + compensators via `@sd.register(name, compensator=…)`.
Cross-cutting concerns (timeouts, retries, tracing) plug in through
middleware (`sd.add_middleware(fn)`). Middleware MUST NOT reorder
compensation — only wrap individual step invocations.

## Schema of `SagaOrchestrator.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from SagaOrchestrator import InMemorySagaOrchestrator, SagaDefinition

sd = SagaDefinition("order")
sd.register("reserve", compensator=lambda r: release_reservation(r))(
    lambda payload: reservation_service.reserve(payload)
)
sd.register("charge", compensator=lambda t: refund(t))(
    lambda payload: payment_service.charge(payload)
)
sd.register("ship", compensator=lambda s: cancel_shipping(s))(
    lambda payload: shipping_service.create_shipment(payload)
)

saga = InMemorySagaOrchestrator(sd, command_sink=async_bus.publish)
saga.start(order_id, {"items": items, "buyer": buyer_id})
# ... as participants reply:
saga.step(order_id, "reserve", reservation_reply)
# ... if anything fails, the orchestrator drives compensators in reverse.
```

## Compose with:

- **Compensating transaction** → `WorkflowRun` + `TransactionalOutbox`
  Each step and its compensation are durable workflow activities; partial failure triggers compensations in reverse order without a distributed 2PC.

- **Event-driven coordination** → `DomainEvent` + `IdempotentConsumer`
  Saga reacts to domain events and emits commands via idempotent consumers — at-least-once delivery never causes double-compensation.

- **Observable long-running state** → `Tracer` + `HealthProbe`
  Workflow spans cover the entire saga; unhealthy sagas surface on the readiness probe before a customer complaint.
