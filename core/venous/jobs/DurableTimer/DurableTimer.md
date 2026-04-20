# DurableTimer

## What it does (plain language)

A DurableTimer is a persistent "wake me up in N seconds" primitive for
workflows. Unlike `asyncio.sleep`, a DurableTimer survives process
restart: if the worker dies at second 30 of a 600-second wait, any other
worker can pick up the same workflow and still fire the timer exactly once
when the deadline arrives.

### Plain-English glossary

- **delay_s**: non-negative seconds before the timer fires. `0.0` means
  "fire on the next decision tick".
- **fire**: the runtime records a `fired` event into the workflow's
  history, which unblocks the workflow decision that was awaiting the
  timer.
- **cancel**: the runtime records a `canceled` event and removes the
  timer from the fire queue. A canceled timer CANNOT fire.

## Purpose

Expose a replay-safe sleep API so workflows can wait for minutes, hours,
or days without holding a thread or losing state on restart. The
DurableTimer is the ONLY sleep surface available to workflow code.

## When to use and when NOT to use

- USE: business waits (retry delays, SLA timeouts, scheduled reminders).
- DO NOT USE: intra-step micro-sleeps inside an activity (use ordinary
  asyncio there; the activity handles its own retries).
- DO NOT USE: cron-style recurring schedules (use a cron primitive).

## API surface

See `DurableTimer.contract.json` for the catalog `PrimitiveSpec`. The
implementation `DurableTimer.py` exposes `DurableTimer` (dataclass with
field validation) and `InMemoryTimerService` as a reference runtime.
Production deployments substitute a Temporal 1.24 server-backed service.

## Invariants

| ID | Rule |
|---|---|
| DT_INV_01 | A fired timer MUST be recorded as an event so replay reconstructs the fire. |
| DT_INV_02 | Wall-clock sleep calls inside a workflow are FORBIDDEN. |
| DT_INV_03 | A canceled timer SHALL NEVER fire. |
| DT_INV_04 | `delay_s` MUST be non-negative. |
| DT_INV_05 | A single worker NEVER caps the number of concurrent durable timers. |

## Formal model

`DurableTimer.tla` models schedule / cancel / fire transitions. Safety
invariants `FiredRecordedAtMostOnce` (DT-INV-01) and `TerminalDisjoint`
(DT-INV-03) are checked by TLC 2.19 with bounded timer sets; "No error
has been found".

## Invariant -> test mapping

See `invariant_bindings.json`.

## Thread and async safety

- The reference runtime serializes transitions within one workflow_id via
  the event-counter; concurrent `start` / `cancel` / `fire` calls are
  ordered by the monotonic `_next_seq()` counter.
- Production Temporal server persists transitions durably; process
  restart of the worker does not lose in-flight timers.

## Operational characteristics (for SRE)

- `timer.scheduled` / `timer.fired` / `timer.canceled` counters are the
  primary signals.
- `timer.delay` histogram reveals distribution of configured delays —
  spikes toward very short delays often indicate a retry loop that should
  use `ActivityCall` retry policy instead.
- No per-worker gauge because there is no per-worker cap (DT-INV-05).

## Security considerations

- `delay_s` is bounded below at `0.0` but unbounded above; operators
  should set a policy-level upper cap (e.g. 90 days) at the workflow
  type boundary.
- `workflow_id` and `timer_id` are opaque strings — validators only
  check non-emptiness. Applications SHOULD keep them free of user input
  (use surrogate ids).

## Provenance

- Source agent: Agent #2 DISTRIBUTED.
- Primary sources: Temporal 1.24 Python timers guide; Workflows concept
  page — Durability and Event History sections.

## Alternatives considered and rejected

- `asyncio.sleep` inside workflow code: disappears on process restart,
  breaks replay determinism.
- External cron-style schedulers: cannot correlate to a workflow run_id.

## Extension contract

Add scheduling backends by implementing `TimerService` as an adapter over
the orchestrator; compose cross-cutting policies (quota, fairness) by
wrapping `start` with middleware registered on the worker.

## Usage

```python
async def park_until(svc: TimerService, wf_id: str, seconds: float) -> None:
    timer = DurableTimer(workflow_id=wf_id, timer_id=f"wait-{seconds}", delay_s=seconds)
    await svc.start(timer)
```

## Compose with:

- **Long-wait workflow** → `WorkflowRun` + `ActivityCall`
  `sleep(7d)` survives deploys; the next activity fires exactly once at the scheduled wall clock — no cron, no shared scheduler.

- **Actor reminders** → `VirtualActor` + `WorkflowRun`
  Virtual actors use timers as durable reminders; an entity 'wakes itself up' in the future without a centralized scheduler.

- **Saga timeouts** → `SagaOrchestrator` + `ActivityCall`
  Sagas schedule compensating deadlines via durable timers; a lost participant triggers compensation at T+N regardless of process lifetimes.
