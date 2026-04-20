# VirtualActor

## What it does (plain language)

A VirtualActor is a stateful object addressed by type + key (`Account/alice`,
`Device/serial-123`). The runtime ensures one message at a time per actor,
private state (no one reads it except through `invoke`), and durable
reminders that survive host failure. Callers never pick a host — placement
is the runtime's job.

## Purpose

Serialize writes per entity without hand-rolling locks; give entities a
durable reminder surface for periodic work; hide actor placement from
clients so failover does not leak into application code.

## When to use and when NOT to use

- USE: per-user / per-device / per-session state machines that need single-
  writer semantics and a small durable scheduler (reminders).
- DO NOT USE: high-throughput stateless work (use `jobs.ActivityCall`).
- DO NOT USE: read-heavy aggregates over the actor's private state — the
  actor IS the only read path by design (VACT-INV-02).

## API surface

See `VirtualActor.contract.json` for the verbatim catalog Protocol. The
implementation `VirtualActor.py` provides `InMemoryVirtualActor` as a
reference runtime that registers handlers per `ActorId`, serializes
invocations via an asyncio lock, and holds reminders in memory (a real
deployment swaps in a persistent store for reminders).

## Invariants

| ID | Rule |
|---|---|
| VACT_INV_01 | Only one invocation of a given ActorId runs at a time; concurrent calls MUST queue in arrival order. |
| VACT_INV_02 | Actor state NEVER escapes the actor instance; callers ALWAYS read it through `invoke`. |
| VACT_INV_03 | Reminders MUST survive actor deactivation and restart; they SHALL fire after the configured period regardless of host. |
| VACT_INV_04 | In-actor (non-reminder) timers CANNOT outlive deactivation; reminders are the durable option. |
| VACT_INV_05 | Caller code MUST NOT depend on the physical host; placement can migrate on failover. |

## Invariant -> test mapping

See `invariant_bindings.json`; every invariant has confirms / prevents /
under_failure tests.

## Thread and async safety

- Every `invoke` holds a per-ActorId `asyncio.Lock`. Distinct ActorIds run
  in parallel; the same ActorId strictly serializes.
- Handlers that raise propagate the exception and release the lock via the
  `async with` contract — subsequent invocations are unaffected.
- The runtime is event-loop-bound; it does not spawn threads.

## Operational characteristics (for SRE)

- `actor.invoke.calls` counter (labels: `actor_type`, `method`, `outcome`).
- `actor.invoke.duration` histogram (ms) — p99 per actor type is the
  primary latency lens.
- `actor.queue.depth` gauge — sustained depth > 1 indicates a hot key;
  split the key space or shard the actor type.
- Reminder count is a bounded gauge; unbounded growth is a leak symptom.

## Security considerations

- State encapsulation (VACT-INV-02) prevents a caller from exfiltrating
  actor state via a side channel; all access is mediated by the method
  table.
- Payload bytes are opaque to the runtime — callers MUST apply authz in
  the handler, not at the transport layer.
- Reminders persist regardless of the reminder content; callers MUST NOT
  put secrets inside reminder names.

## Provenance

- Source agent: Agent #2 DISTRIBUTED
  (`docs/research/outputs/AGENT_2_DISTRIBUTED.json`).
- Primary source: Dapr 1.14 Actors building-block overview — Turn-based
  access, Placement, Timers vs Reminders sections.

## Alternatives considered and rejected

- Row-level DB locks: do not scale horizontally; couple correctness to a
  single database.
- Consumer-group rebuild of actor semantics: loses reminders and state
  affinity.

## Extension contract

Implement new actor behaviors by subclassing a base actor type and
registering it with the runtime via `register(actor_type, key, handlers)`;
cross-cutting concerns (tracing, policy) plug in as server-side
interceptors around `invoke`. The Protocol surface is v1.

## Schema of `VirtualActor.contract.json`

Verbatim copy of the catalog `PrimitiveSpec` dict.

## Usage

```python
async def credit(bank: VirtualActor, user: str, amount: int) -> bytes:
    account = ActorId(actor_type="Account", key=user)
    return await bank.invoke(account, method="credit", payload=str(amount).encode())
```

## Compose with:

- **Per-entity serialization** → `DistributedLock` + `IdempotentConsumer`
  Writes to one entity run sequentially even across hosts; idempotent framing means a rehomed actor never double-applies an in-flight message.

- **Durable reminders** → `DurableTimer` + `WorkflowRun`
  Actor reminders survive restarts; a workflow step scheduled for next week fires once regardless of deploy churn.

- **Saga participant** → `SagaOrchestrator` + `WorkflowRun`
  Actors respond to saga commands and emit events; compensations land as messages the actor processes in order.
