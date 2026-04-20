# WorkflowRun

## What it does (plain language)

Imagine a multi-step business process (shipping an order: charge card,
reserve stock, send email). A WorkflowRun is a durable, replayable
recording of that whole process, identified by a `workflow_id` (like
`order-42`) and a `run_id` (the specific attempt). Every decision the
workflow makes is written to an **event history**. If the server crashes
halfway through, any other server can pick up that `workflow_id`, read
the history, and continue exactly where the previous server stopped — no
lost steps, no duplicate side-effects.

### Plain-English glossary

- **workflow_id**: stable business-level name (`order-42`). You choose it.
- **run_id**: internal attempt counter. Allocated by the runtime for each
  start. Two runs with the same workflow_id always have different run_ids.
- **event history**: append-only log of decisions. The workflow's memory.
- **replay**: rebuild the workflow state by re-reading the history.
- **deterministic**: given the same history, a replay produces the same
  next decision. That's why you cannot call `random()` or `time.time()`
  inside a workflow — those values change on each replay.

### Why operators and product managers care

- Every workflow is observable: you can list active runs, check their
  status, and cancel them by id.
- Every workflow is replayable: a bug fix can be deployed and the same
  business process resumes from the exact point of the crash.
- Every workflow is auditable: the event history is a tamper-evident
  record of who decided what, and in what order.

## Purpose

Give the application a single contract for long-running orchestrations that
survive process restart, enforce determinism, and pin the identity model so
operators can describe / cancel / resume runs uniformly.

## When to use and when NOT to use

- USE: multi-step business processes (order shipping, loan approval),
  long-lived sagas with time-based coordination.
- DO NOT USE: tight synchronous request/response — the replay machinery is
  excessive overhead.
- DO NOT USE: plain fire-and-forget tasks — use `ActivityCall` directly.

## API surface

See `WorkflowRun.contract.json` for the verbatim catalog Protocol. The
`InMemoryWorkflowClient` reference implementation provides `start`,
`describe`, `cancel` plus non-surface helpers for tests
(`schedule_activity`, `complete`, `fail`, `replay`, `history_of`,
`status_of`, `all_runs_of`). The workflow Protocol intentionally exposes no
wall-clock / random / network methods — WFR-INV-02 is enforced by absence.

## Invariants

| ID | Rule |
|---|---|
| WFR_INV_01 | Workflow code MUST be deterministic for replay to reconstruct the same decisions. |
| WFR_INV_02 | Non-deterministic calls (random, wall-clock, direct network IO) are FORBIDDEN inside workflow code. |
| WFR_INV_03 | A completed/canceled run CANNOT be resumed under the same run_id; reruns ALWAYS get a new run_id. |
| WFR_INV_04 | Every externally observable effect MUST flow through an activity, timer, signal, or child workflow. |
| WFR_INV_05 | Starting with an id that already has an open run SHALL follow the configured id-reuse policy (REJECT / REUSE_EXISTING / TERMINATE_EXISTING). |

## Invariant -> test mapping

See `invariant_bindings.json`; every invariant has confirms / prevents /
under_failure tests.

## Formal model

`WorkflowRun.tla` models workflow identity + lifecycle under three actions
(StartNew, CompleteOpen, CancelOpen) with safety invariants `AtMostOneOpen`
(WFR-INV-05) and `UniqueRunIds` (WFR-INV-03). TLC 2.19 checks it with
bounded workflow set + MaxRuns = 3 and reports "No error has been found".

## Thread and async safety

- The reference `InMemoryWorkflowClient` is not thread-safe but is safe
  under asyncio single-threaded execution. Operations on different
  workflow_ids are independent.
- Real deployments back this with Temporal's server + sticky task queues,
  which serialize per-run decisions.

## Operational characteristics (for SRE)

- `workflow.runs.started` counter (labels: `workflow_type`, `task_queue`).
- `workflow.run.duration` histogram (ms, labels: `workflow_type`, `outcome`).
- `workflow.active.runs` gauge — the fundamental capacity signal.

## Security considerations

- `workflow_id` regex (`^[A-Za-z0-9][A-Za-z0-9_\-./]{0,99}$`) prevents
  control characters / whitespace from being used as identity, which
  otherwise lets an attacker overwrite another workflow's identity via
  normalization collisions.
- Args payload is a typed tuple (deterministic). Non-tuple args are
  rejected — this blocks a class of replay attacks where a mutable list is
  captured and modified between replays.

## Provenance

- Source agent: Agent #2 DISTRIBUTED.
- Primary sources: Temporal 1.24 Workflows concept page — Workflow
  Definition, Determinism, Event History, and Replay paragraphs.

## Alternatives considered and rejected

- Chained Celery tasks: no durable replay, no event history.
- Custom state machines per worker: repeat the same determinism bugs.

## Extension contract

Register new workflow types as decorated functions on a worker polling a
named task queue; extend behavior by composing interceptors on the worker
that wrap workflow and activity invocations, and by implementing custom
payload converters as adapters.

## Usage

```python
async def kickoff(client: WorkflowClient) -> WorkflowRun:
    run: WorkflowRun = await client.start("ShipOrder",
        workflow_id="order-42", task_queue="orders", args=(42,))
    return run
```

## Compose with:

- **Durable orchestration** → `ActivityCall` + `DurableTimer`
  Workflow code is deterministic; activities are side-effectful; timers are durable — the workflow history is the single replay source of truth.

- **Saga host** → `SagaOrchestrator` + `ActivityCall`
  Sagas run as workflows; compensations are activities; the framework guarantees at-most-once compensation per step.

- **Actor substrate** → `VirtualActor` + `DurableTimer`
  Workflows host virtual actor instances; reminders and state survive host loss — 'one actor per entity, always' is mechanical.
