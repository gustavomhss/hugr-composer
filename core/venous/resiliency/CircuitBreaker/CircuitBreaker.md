# CircuitBreaker

## What it does (plain language)

CircuitBreaker is the three-state stability guard that every call out to a
fallible dependency flows through. When failures pile up past a threshold it
flips to `open` and short-circuits further calls so the sick dependency is not
hammered; after a cooldown it enters `half_open` and lets a small number of
probe calls through to feel the water; one successful probe closes the
breaker again, one failed probe slams it back to `open` and restarts the
cooldown.

## Purpose

Short-circuit calls to a failing dependency by transitioning between `closed`,
`open`, and `half_open` states driven by a rolling failure metric.

## When to use and when NOT to use

- USE: any outbound call to a remote or flaky dependency (HTTP/RPC to other
  services, third-party APIs, databases under contention, message brokers).
- USE: whenever retry + timeout alone would amplify load on the dependency.
- DO NOT USE: a pure in-process pure-CPU function — there is no shared failure
  to short-circuit.
- DO NOT USE: alone as the whole stability story — pair with `TimeoutBudget`
  (deadline propagation), `Bulkhead` (partitioned concurrency), and
  `RetryPolicy` (budget-aware retries).

## API surface

The catalog `api_signature` in `CircuitBreaker.contract.json` is the authority.
Callers wrap their async call sites with `await breaker.call(fn, *args)`; the
breaker routes around `open` state, permits a bounded number of probes while
`half_open`, and records every outcome through `on_success` / `on_failure`.
Operators can force open a breaker with `force_open(reason)` during a planned
incident response.

## Invariants

| ID | Rule |
|---|---|
| CBREAK_INV_01 | When state is `open` the breaker MUST reject calls without invoking the wrapped function. |
| CBREAK_INV_02 | The transition from `open` to `half_open` SHALL occur only after the configured cooldown interval has elapsed on a monotonic clock. |
| CBREAK_INV_03 | A `half_open` breaker MUST permit at most `permitted_calls_in_half_open` probes concurrently. |
| CBREAK_INV_04 | A single failure recorded while `half_open` SHALL force the state back to `open` and restart the cooldown. |
| CBREAK_INV_05 | The breaker CANNOT make a transition decision using a sample smaller than `minimum_number_of_calls`. |
| CBREAK_INV_06 | The breaker NEVER mutates state without emitting a state_transition event on the observability bus. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding; TLA+ safety properties in
`CircuitBreaker.tla` back the same invariants with machine-checked proofs.

## Thread and async safety

- `InMemoryCircuitBreaker` serialises state and counter mutations via an
  internal `RLock` so concurrent outcome recordings, probe requests, and
  force-open calls CANNOT produce illegal states or leak extra probe permits.
- `call()` holds the lock only while it snapshots the gate decision; the
  wrapped coroutine runs OUTSIDE the lock so application code CANNOT deadlock
  on the breaker.
- One breaker instance is safe to share across an entire service's request
  pipeline — partition by dependency name (one breaker per downstream).

## Operational characteristics (for SRE)

- `circuitbreaker.transitions` (counter, labels: breaker, from_state, to_state)
  is the primary dashboard signal; an elevated `to_state="open"` rate for any
  breaker is an outbound-health alert.
- `circuitbreaker.calls` (counter, labels: breaker, outcome) separates
  accepted / rejected / failure outcomes so retry amplification can be watched.
- `circuitbreaker.call.duration` (histogram, ms) bounds latency even when the
  dependency is slow — the breaker itself adds near-zero overhead.
- Operators use `force_open(reason)` to pre-emptively short-circuit a
  dependency during planned maintenance; pair with an alert so the state is
  visible on the dashboard.

## Security considerations

- The breaker stores a short count-based outcome window only — no request
  payloads, no customer data. Rollback of a probe does not touch caller memory.
- `force_open` accepts a `reason` string that is copied into the event log;
  callers MUST NOT pass secrets in the reason.
- Attackers cannot use repeated force_open calls to emit extra events: the
  implementation makes redundant force_open calls (already `open`) a no-op.

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Primary sources:
  - Nygard, *Release It!* 2nd ed. (2018) — Chapter 5, pages 104-111.
  - resilience4j 2.2.0 reference documentation, core-modules/circuitbreaker.
  - Netflix Tech Blog: "Making the Netflix API More Resilient" (Christensen,
    2011) on Hystrix half-open probing.

## Alternatives considered and rejected

- Per-call timeout only — detects slowness but NEVER stops the caller from
  piling load onto a sick dependency.
- Retry with exponential backoff alone — amplifies load during outages
  instead of shedding it.
- Client-side rate limiter — caps throughput but cannot react to the
  dependency's actual health signals.

## Extension contract

Adopters register a `FailureClassifier` provider that decides which exceptions
count as failures, a `slow_call_duration_threshold`, and a state listener
hook; the sliding window type (count-based or time-based) is selected via a
`SlidingWindowPolicy` adapter. The rolling metrics and the state machine
itself remain sealed — downstream tools MUST NOT override transition logic.

## Schema of `CircuitBreaker.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
breaker = InMemoryCircuitBreaker(
    "payments",
    failure_rate_threshold=0.5,
    minimum_number_of_calls=5,
    cooldown_ms=30_000,
    permitted_calls_in_half_open=1,
)

async def charge(order_id: str) -> Receipt:
    return await breaker.call(_charge_impl, order_id)
```

## Compose with:

- **Bounded-retry guard** → `RetryPolicy` + `TimeoutBudget`
  Breaker opens before retry storms amplify; budgets ensure retries never outlast the request deadline.

- **Dependency isolation** → `Bulkhead` + `OutboundBinding`
  Each adapter has its own breaker and pool; one broken vendor does not take down the primary transaction path.

- **Probe-visible health** → `HealthProbe` + `MetricMeter`
  Open breakers flip readiness false for the affected capability; callers drain instead of piling on.

- **Worker-level failing-dependency backoff** → `HeterogeneousWorkerPool` + `Bulkhead`
  A `CircuitBreaker` wraps each worker's executor in `HeterogeneousWorkerPool`; consecutive failures trip the breaker, and the pool's `on_result(ok=False)` signal deprioritizes the worker in parallel. Invariant gained: pool and breaker agree on which worker is 'unhealthy' right now.
