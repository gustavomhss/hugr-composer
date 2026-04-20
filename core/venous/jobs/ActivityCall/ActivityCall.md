# ActivityCall

## What it does (plain language)

An ActivityCall is the "do the side-effect" unit inside a workflow — charge
a card, send an email, call a third-party API. The workflow says "please
run activity X on task-queue Y with these args", and the runtime takes care
of scheduling, retrying on failure, and reporting success or a terminal
error back to the workflow.

### Plain-English glossary

- **task_queue**: the named inbox the activity worker listens on
  (`payments`, `emails`).
- **start_to_close_s**: how long the activity has to finish ONE attempt.
- **heartbeat_s**: how often a long-running activity must "ping" to prove
  it is still alive. If it stops pinging the runtime retries.
- **RetryPolicy**: `initial_interval_s * backoff_coefficient^(attempt-1)`
  up to `maximum_attempts`.
- **at-least-once**: the runtime may call your activity more than once, so
  the activity code MUST be idempotent (safe to run twice with the same
  input).

## Purpose

Pin the activity contract so every tool uses the same timeouts, retry
policy, heartbeat rules, and terminal-error escalation — no tool rolls its
own tenacity loop.

## When to use and when NOT to use

- USE: any workflow-scoped side effect (payments, notifications, storage
  uploads).
- DO NOT USE: deterministic pure compute (do it inline in the workflow).
- DO NOT USE: synchronous request/response where the caller waits — prefer
  RPC.

## API surface

See `ActivityCall.contract.json` for the catalog `PrimitiveSpec`. The
implementation `ActivityCall.py` exposes `ActivityCall` + `RetryPolicy`
dataclasses (with full field validation in `__post_init__`) and an
`InMemoryActivityExecutor` reference executor that registers handlers by
name and enforces attempt-limit + timeout semantics.

## Invariants

| ID | Rule |
|---|---|
| AC_INV_01 | Execution is at-least-once; activity code MUST be idempotent. |
| AC_INV_02 | `start_to_close_s` MUST be a positive int. |
| AC_INV_03 | A missed heartbeat CANNOT be treated as success. |
| AC_INV_04 | Reaching `maximum_attempts` MUST surface a terminal error to the workflow. |
| AC_INV_05 | Heartbeat details NEVER outlive a successful attempt. |

## Formal model

`ActivityCall.tla` models the attempt lifecycle (pending / success /
exhausted). Safety invariants `NoSilentDrop`, `Monotone`, and
`AttemptsBounded` are checked by TLC 2.19 with `MaxAttempts=3`; "No error
has been found".

## Invariant -> test mapping

`invariant_bindings.json` is the authoritative binding; every invariant has
confirms / prevents / under_failure tests.

## Thread and async safety

- The reference executor is asyncio-only; handlers run under the current
  event loop.
- Production deployments back this contract with a Temporal 1.24 worker
  pool that isolates activity code in a sandboxed thread or process,
  reconciles attempts against the server-side event history, and exposes
  heartbeat cancellation back to the in-flight handler.

## Production-readiness notes

The catalog `PrimitiveSpec.maturity` is `battle_tested` because the contract
is the Temporal 1.24 activity contract — verbatim: same at-least-once
guarantee, same retry-policy field names, same start-to-close / heartbeat
semantics. Two production runtimes implement this contract today:

1. **Temporal server + Python SDK 1.x** — handles durable attempt
   accounting, heartbeat cancellation, and worker failover across
   machines.
2. **Dapr Workflow runtime** — a Dapr-native implementation with the same
   surface and retry policy shape.

The shipped `InMemoryActivityExecutor` is a reference runtime for unit /
integration tests; swapping it for the Temporal SDK is a single-line
change because both expose `async def execute(call: ActivityCall) -> Any`.
Every invariant (AC-INV-01..05) is a contract obligation for any
implementation — the reference runtime enforces all five today, the
Temporal runtime enforces them via the server's event history.

## Operational characteristics (for SRE)

- `activity.attempts` counter labels by `activity_name`, `outcome`.
- `activity.attempt.duration` histogram (ms) — p99 by activity identifies
  slow integrations.
- `activity.heartbeat.missed` counter — sustained misses signal downstream
  saturation.

## Security considerations

- Activity args MUST be a tuple (deterministic, serialisable) to prevent a
  mutable-list replay attack.
- `maximum_attempts` bounds retry budget, preventing unintended DoS against
  flaky downstreams.
- Heartbeat details do not cross attempts — a prior attempt's secrets
  cannot leak into the next.

## Provenance

- Source agent: Agent #2 DISTRIBUTED.
- Primary source: Temporal 1.24 Activities concept page — at-least-once
  semantics, heartbeat, retry policy, timeouts paragraphs.

## Alternatives considered and rejected

- `tenacity` retries in-process: no `schedule_to_close` envelope, no
  heartbeat, no durable state on crash.
- Custom queue per feature: duplicates scheduling and observability
  plumbing.

## Extension contract

Register activity implementations on a worker for a named task queue; add
cross-cutting behavior with worker interceptors that wrap `execute`.
Adapters implement transport-specific payload conversion.

## Usage

```python
call = ActivityCall(
    name="ChargeCard", task_queue="payments",
    start_to_close_s=30, schedule_to_close_s=120, heartbeat_s=10,
    retry=RetryPolicy(initial_interval_s=1.0, backoff_coefficient=2.0, maximum_attempts=5),
    args=(order_id,),
)
receipt: str = await executor.execute(call)
```

## Compose with:

- **Typed step contract** → `WorkflowRun` + `RetryPolicy`
  Every workflow step declares its ActivityCall; retry and timeout are part of the contract — not per-step boilerplate.

- **Heartbeated long work** → `TimeoutBudget` + `HealthProbe`
  Long activities heartbeat within the budget; a stalled activity is reclaimed and retried without a silent orphan.

- **At-least-once activities** → `IdempotentConsumer` + `InboxDeduplicator`
  Activities are retried on worker loss; idempotency keys make repeat execution safe — correctness does not depend on 'exactly once'.
