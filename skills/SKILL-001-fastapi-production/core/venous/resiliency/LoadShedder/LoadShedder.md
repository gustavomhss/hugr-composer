# LoadShedder

## What it does (plain language)

LoadShedder is the priority-aware admission-control primitive. When the server
enters overload, it drops low-priority work first (batch, crawlers,
best-effort) so that high-priority traffic (payment, auth, checkout) keeps
meeting its SLA. It reads live signals — CPU EWMA, queue depth — composes
them into a single pressure value, and publishes a cutoff priority. Anything
at or above the cutoff is admitted; everything else is rejected with an
explicit HTTP 503 / `UNAVAILABLE` signal carrying a `Retry-After` hint.

## Purpose

Drop or reject low-priority work when the server enters an overload regime so
that high-priority traffic continues to meet its SLA.

## When to use and when NOT to use

- USE: any ingress or queue boundary that serves mixed-priority traffic
  (user-facing + batch + crawlers) and could experience sub-second overload
  spikes (autoscaling alone cannot respond in time).
- USE: any admission point where the cost of overload is *cascading failure*
  (queues growing faster than they drain).
- DO NOT USE: a single-tenant, uniform-priority service — a fixed rate limiter
  is enough.
- DO NOT USE: purely async background pipelines where backpressure from
  downstream consumers already shapes the producer (queue-theoretic load
  shedding is implicit).

## API surface

The catalog `api_signature` in `LoadShedder.contract.json` is the authority:

```python
from typing import Protocol, Literal

Priority = Literal['critical', 'normal', 'sheddable_plus', 'sheddable']

class LoadShedder(Protocol):
    def admit(self, priority: Priority, queue_depth: int, cpu_load_ewma: float) -> bool: ...
    def current_cutoff(self) -> Priority: ...
    def shed_rate(self) -> float: ...
```

Callers invoke `admit(...)` at the ingress edge. When the result is `False`,
the caller MUST construct a 503 response containing a `Retry-After` header —
`rejection_signal()` returns the pre-packaged structure.

## Invariants

| ID | Rule |
|---|---|
| LSH_INV_01 | The shedder SHALL admit strictly by descending priority class and MUST NEVER admit a lower class while a higher class is being rejected. |
| LSH_INV_02 | A rejected request MUST be returned with an explicit overload signal (HTTP 503 or status UNAVAILABLE) and a retry-after hint. |
| LSH_INV_03 | The cutoff priority CANNOT change more than once per `control_interval_ms` to prevent oscillation. |
| LSH_INV_04 | A request that passed admission control SHALL NEVER be shed later in the pipeline. |
| LSH_INV_05 | The shedder MUST publish the current cutoff as a metric so clients can cooperate with backoff. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Priority → rank table

| Priority        | Rank | Semantics                                  |
|-----------------|-----:|--------------------------------------------|
| critical        |    0 | Payments, auth, checkout. ALWAYS admitted. |
| normal          |    1 | Normal user traffic.                       |
| sheddable_plus  |    2 | Deferrable but still user-facing.          |
| sheddable       |    3 | Batch, crawlers, best-effort.              |

Lower rank = higher priority. A cutoff of `normal` means: admit every class
with rank ≤ 1 (i.e. `critical`, `normal`); reject `sheddable_plus` and
`sheddable`.

## Pressure → cutoff band table

| Pressure p      | Regime   | Cutoff         |
|-----------------|----------|----------------|
| p ≥ 0.95        | extreme  | critical       |
| 0.85 ≤ p < 0.95 | heavy    | normal         |
| 0.70 ≤ p < 0.85 | warm     | sheddable_plus |
| p < 0.70        | healthy  | sheddable      |

Pressure = `composition(cpu_load_ewma, queue_depth / queue_saturation)`. The
composition adapter is configurable (`compose_max` default, `compose_ewma`,
`compose_quantile`).

## Thread and async safety

- All mutations are serialised under a single internal lock — concurrent
  `admit()` calls from many workers preserve priority ordering (LSH-INV-01)
  and hysteresis (LSH-INV-03).
- The metric sink is invoked INSIDE the critical section with exceptions
  swallowed — telemetry failures MUST NEVER break the admission path or
  retroactively shed an admitted request (LSH-INV-04).
- `current_cutoff()` and `shed_rate()` are O(1) and safe to poll from any
  thread.

## Operational characteristics (for SRE)

- Self-observability: `load_shedder.current_cutoff` (gauge,
  `cutoff` label), `load_shedder.admissions` (counter, `priority`/`result`
  labels), `load_shedder.shed_rate` (histogram).
- Alert suggestions:
  - `load_shedder.current_cutoff != "sheddable"` for > 1 minute → warn
  - `current_cutoff == "critical"` for > 30 s → page
  - `shed_rate > 0.2` sustained → investigate capacity
- The `RejectionSignal` returned via `rejection_signal()` carries a
  `retry_after_seconds` floor equal to `max(0.1, control_interval_ms/1000)`
  so clients cooperate with the hysteresis window.
- Runbook actions: scale out upstream, throttle cron traffic, verify
  signal providers are not reporting stale CPU EWMA (signal plateau is the
  #1 cause of oscillation fallback).

## Security considerations

- The shedder is NOT a security gate — it implements graceful degradation,
  not authorisation. Never substitute `admit()` for authentication.
- Priority is a caller-supplied value. Deployments MUST wire a trusted
  `PriorityExtractor` that derives priority from an authenticated token
  claim, NOT from a client-controlled header — otherwise an adversary can
  self-elevate to `critical` and starve legitimate traffic.
- `retry_after_seconds` is capped at a known floor; callers that ignore the
  hint and hot-loop will be further shed — the shedder is self-protective
  against naïve clients.

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Primary sources:
  - Google SRE Workbook (Beyer et al., O'Reilly, 2018), Chapter 21
    "Managing Load", sections "Graceful Service Degradation" and
    "Load Shedding".
  - Google SRE Book (Beyer et al., O'Reilly, 2016), Chapter 22 "Addressing
    Cascading Failures", section "Preventing Server Overload".

## Alternatives considered and rejected

- Fixed rate limiter — caps QPS but CANNOT differentiate priorities and
  under-uses idle capacity.
- Backpressure from downstream only — reacts too late, after a queue has
  already formed.
- Autoscaling alone — scale-out latency NEVER matches a sub-second overload
  spike.

## Extension contract

Adopters register:
- A `LoadSignal` provider (CPU, queue depth, event-loop lag, p99 latency).
- A `PriorityExtractor` hook that reads the priority class from request
  context (MUST be authenticated input — see Security above).
- A `CompositionAdapter` (`compose_max`, `compose_ewma`, `compose_quantile`,
  or a custom `Callable[[float, float], float]`) that fuses signals into a
  single pressure value in `[0, 1]`.

## Schema of `LoadShedder.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from LoadShedder import InMemoryLoadShedder, SealedAdmit

shedder = InMemoryLoadShedder(control_interval_ms=100)
sealed = SealedAdmit(shedder)

def handle(request, priority):
    token = sealed.admit(priority, queue_depth=len(request_queue), cpu_load_ewma=cpu())
    if token is None:
        sig = shedder.rejection_signal()
        return Response(status=sig.http_status,
                        headers={"Retry-After": str(sig.retry_after_seconds)})
    # LSH-INV-04: downstream stages accept the token as proof of admission;
    # they MUST NOT call the shedder again for the same request.
    return process(request, token)
```

## Compose with:

- **Priority-aware admission** → `RequestShape` + `Bulkhead`
  Priority class + pool utilization drive admission; shed requests return 503 fast instead of queuing past their deadline.

- **Protect tail latency** → `TimeoutBudget` + `RateLimiter`
  Under overload, the shedder trims tail work; the rate limiter maintains per-tenant fairness — p99 stays honest.

- **Cascade prevention** → `CircuitBreaker` + `HealthProbe`
  Shedding before breakers trip keeps capacity observable; probes see real state, not 'every downstream breaker open'.
