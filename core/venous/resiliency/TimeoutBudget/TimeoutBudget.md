# TimeoutBudget

## What it does (plain language)

TimeoutBudget is the hierarchical deadline primitive for every inbound request.
Ingress attaches a monotonic deadline to the request; every downstream call
then uses the *remaining* budget, never its local timeout alone. Children
derived from a parent budget CANNOT outlive it — deadlines move in one
direction only: down.

## Purpose

Attach a monotonic deadline to an inbound request and propagate the remaining
budget to every downstream call so no call outlives its originating request.

## When to use and when NOT to use

- USE: any inbound request that fans out to downstream services, databases,
  or caches — i.e. any non-trivial handler. The budget is the contract that
  stops a slow dependency from cascading into a stampede of zombie work.
- USE: background jobs that represent a bounded piece of logical work; open
  a fresh root budget at the job boundary.
- DO NOT USE: long-running streams or idle connections — they deliberately
  outlive any request budget and MUST use a separate liveness mechanism.
- DO NOT USE: already-scheduled retries that re-open the budget — retries
  MUST stay inside the existing budget (TB-INV-04: no extensions in scope).

## API surface

The catalog `api_signature` in `TimeoutBudget.contract.json` is the authority.
The module exposes:

- `MonotonicTimeoutBudget.from_ms(total_ms, origin)` — open a root budget.
- `budget.remaining_ms()` — the remaining budget in whole milliseconds, never
  negative.
- `budget.for_call(max_ms)` — returns `min(max_ms, remaining_ms())` and
  raises `TimeoutBudgetExpired` if the budget is exhausted — refusing the
  dispatch BEFORE any socket I/O.
- `budget.expired()` — boolean check for the remaining-budget condition.
- `budget.derive(child_max_ms=…)` — produces a child budget whose deadline is
  at most the parent's deadline.
- `bind(budget)` / `current()` — propagate the active budget through a
  `contextvars.ContextVar`, never thread-local state.
- `DeadlineHeaderCodec` — encode / decode the remaining budget as an
  `X-Deadline-Ms` header so hops across HTTP / gRPC transports preserve the
  monotonic-decrease rule.
- `GuardedCall` — a transport-adjacent dispatcher that proves TB-INV-01 /
  TB-INV-03 in tests (records each dispatch's effective timeout; refuses when
  expired).

## Invariants

| ID | Rule |
|---|---|
| TB_INV_01 | Every outbound call MUST use `min(local_timeout, remaining_ms())` and NEVER the local timeout alone. |
| TB_INV_02 | The deadline MUST be measured on a monotonic clock and SHALL NOT move backward on wall-clock jumps. |
| TB_INV_03 | A call issued when `remaining_ms` is not positive SHALL be refused before any socket I/O begins. |
| TB_INV_04 | The budget CANNOT be extended inside the request scope; a derived child budget MUST NEVER exceed the parent's deadline. |
| TB_INV_05 | The budget SHALL be propagated across task boundaries via the `CURRENT_BUDGET` context variable and NEVER via thread-local state. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `MonotonicTimeoutBudget` is immutable: `__setattr__` refuses every post-init
  write, so the budget CANNOT be extended by a racy caller (TB-INV-04).
- `CURRENT_BUDGET` is a `contextvars.ContextVar` — asyncio tasks and
  `contextvars.copy_context()` handoffs inherit the budget automatically.
  Plain `threading.Thread` MUST NOT assume propagation: start threads via
  `contextvars.copy_context().run(...)` to carry the budget into the child.
- `GuardedCall` is lock-free: each dispatch records a tuple; the list append
  is not atomic across CPython threads, so chaos tests use it for ordering
  assertions only (counts held under per-test locks).

## Operational characteristics (for SRE)

- Budget expiration ALWAYS refuses the dispatch; the caller sees
  `TimeoutBudgetExpired` before any socket is touched.
- A sustained rise in `timeout.budget.refusals{reason="expired"}` is the
  primary symptom of an upstream slowness cascading into retries that would
  otherwise flood the dependency.
- The `timeout.budget.for_call` histogram distribution is the canonical
  picture of how much budget survives to each hop; a flattening near zero
  indicates callers running at the edge of their SLA.

## Security considerations

- The deadline header is trust-on-input: a hostile upstream can only SHRINK
  the budget (decoding to `≤ 0` raises `TimeoutBudgetExpired`). Widening is
  structurally impossible — `decode` opens a fresh root budget whose total is
  capped at the header's stated remaining ms.
- `origin` is a free-form label used for logging and trace attribution; it
  MUST NOT be trusted as a principal identifier. Authorization decisions
  belong to `RequestGuard`, not TimeoutBudget.

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Primary sources:
  - Beyer et al., *The Site Reliability Workbook* (O'Reilly, 2018), Chapter
    22 "Addressing Cascading Failures", section "Server Overload" discussing
    deadline propagation.
  - Nygard, *Release It!* 2nd edition (Pragmatic Bookshelf, 2018), Chapter
    5 "Stability Patterns", section "Timeouts", pages 91–97.
  - Envoy proxy documentation, HTTP connection manager
    (`api-v3/config/route/v3/route_components.proto` RouteAction.timeout and
    idle_timeout semantics).

## Alternatives considered and rejected

- Static per-client timeout — cannot shrink as the request ages through hops;
  the budget silently exceeds the inbound SLA by multiples on a retry chain.
- Server-side cancellation only — wastes client and network resources before
  the server decides; the client has already paid the tail latency.
- Budget enforced via exception unwinding — triggers too late to free
  downstream resources; the zombie work proceeds until the raise fires.

## Extension contract

Adopters bind a `DeadlineSource` adapter to ingress (HTTP header, gRPC
deadline, CLI flag) and register a propagation middleware for each transport
client so the remaining budget is written into outbound headers (e.g.
`grpc-timeout`, `X-Deadline-Ms`). `DeadlineHeaderCodec` is the reference
implementation; transport middlewares MUST NOT shortcut it — every hop reads
`budget.remaining_ms()` at emit time so the budget shrinks, never renews.

## Schema of `TimeoutBudget.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from TimeoutBudget import MonotonicTimeoutBudget, bind, current

async def fetch_profile(uid: str) -> Profile:
    budget = current()
    call_ms = budget.for_call(max_ms=250)
    return await http.get(f"/profile/{uid}", timeout_ms=call_ms)

# Ingress (one hop earlier):
root = MonotonicTimeoutBudget.from_ms(total_ms=1000, origin="req-42")
with bind(root):
    profile = await fetch_profile("u-1")
```

## Compose with:

- **Deadline propagation** → `RequestShape` + `MiddlewarePipeline`
  Pipeline stamps the deadline on entry; every downstream call reads the remaining budget — no handler extends time by accident.

- **Bounded retries** → `RetryPolicy` + `CircuitBreaker`
  Retries never outlast the budget; budget-exhausted failures fail fast and surface meaningfully to the caller.

- **Priority interaction** → `LoadShedder` + `Bulkhead`
  Admission considers (budget, priority, pool) together; a near-deadline low-priority request is dropped before it wastes capacity.

- **Deadline-capped batch fetch** → `DataLoader` + `RequestContext`
  The `DataLoader` dispatcher honors the remaining `TimeoutBudget` when firing the bulk batch; overflow batches that would outlast the deadline fail fast instead of hanging the request. Invariant gained: a slow upstream bulk fetch cannot exceed the caller's deadline.
