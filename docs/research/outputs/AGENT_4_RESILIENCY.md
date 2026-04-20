# Agent 4 — RESILIENCY

> Stability and resiliency primitives extracted from Nygard (*Release It!* 2nd ed., 2018), resilience4j 2.2.0, Netflix Hystrix (retirement + post-Hystrix guidance), Google SRE Book/Workbook, Envoy proxy semantics, and adjacent canonical sources (Reactive Streams, AWS Backoff-and-Jitter, Kubernetes probes, Basiri et al. chaos engineering). Every primitive is a sealed, citable contract.

## Mission

Promote stability concerns (circuit breakers, bulkheads, timeouts, retries, shedding, backpressure, graceful degradation, chaos injection) to **first-class primitives** of the venous system, in namespaces `resiliency` and `extras`. No vendor libraries; neutral PascalCase names; every invariant testable.

## Primitives (12)

| # | Name | Namespace | Maturity | Problem it solves |
|---|------|-----------|----------|-------------------|
| 1 | `CircuitBreaker` | resiliency | battle_tested | Short-circuit a sick dependency; half-open probes; no thundering herd on recovery. |
| 2 | `Bulkhead` | resiliency | battle_tested | Partition concurrency so one stall cannot exhaust unrelated dependencies. |
| 3 | `TimeoutBudget` | resiliency | battle_tested | Monotonic deadline propagated to every downstream call; no zombie work past SLA. |
| 4 | `RetryPolicy` | resiliency | battle_tested | Bounded retries with jitter, global budget, idempotency gate; stops N-per-layer amplification. |
| 5 | `LoadShedder` | resiliency | battle_tested | Priority-aware admission control; reject sheddable before critical. |
| 6 | `BackpressureSignal` | resiliency | emerging | Producer-visible pressure from consumer/queue; bounded buffers, explicit slow-path. |
| 7 | `FallbackChain` | resiliency | battle_tested | Typed degraded result; no circular fallbacks; contract preserved. |
| 8 | `OutlierEjection` | resiliency | battle_tested | Evict sick instances from the LB pool within a quorum cap. |
| 9 | `ChaosInjector` | resiliency | emerging | Controlled fault injection; flag-gated, blast-radius capped, observable. |
| 10 | `RateLimiter` | resiliency | battle_tested | Per-key rolling-rate enforcement with token/leaky/sliding algorithms. |
| 11 | `HealthProbe` | resiliency | battle_tested | Typed liveness vs. readiness; debounced transitions; no secret leakage. |
| 12 | `RequestShape` | extras | emerging | Immutable request context (priority, deadline, idempotency, attempt). |

## Design rationale

### Why the Nygard frame still holds in 2025
The canonical taxonomy — Timeouts, Circuit Breaker, Bulkhead, Steady-State, Fail Fast, Governor — published in *Release It!* 1st ed. (2007) and refined in the 2nd ed. (2018, Ch. 5 "Stability Patterns") remains the most-cited concrete stability vocabulary. Every primitive here maps to one of Nygard's patterns or the 2018 extensions (Governor → `RateLimiter`, Shed Load → `LoadShedder`).

### Why Hystrix-style is archived, not replaced
Netflix retired Hystrix in 2018 (README: "Hystrix is no longer in active development") and pointed to adaptive concurrency limits (Netflix/concurrency-limits). The primitive `CircuitBreaker` keeps the state-machine semantics that proved correct (closed → open → half-open, bounded probes), but removes the Hystrix-specific thread-pool coupling by delegating isolation to `Bulkhead`. This is the post-Hystrix guidance in practice: *keep the circuit breaker, separate the isolation*.

### Why the set composes as a pipeline, not a grab-bag
```
ingress → RequestShape → LoadShedder → Bulkhead → TimeoutBudget → CircuitBreaker
       → RetryPolicy → FallbackChain → OutlierEjection → egress
                               ↑
                       ChaosInjector (scoped)
                       HealthProbe  (orchestrator plane)
                       BackpressureSignal (producer plane)
                       RateLimiter  (per-key plane)
```

Each primitive consumes the output of a prior one (`TimeoutBudget.remaining_ms()` caps `RetryPolicy.execute`, `RequestShape.priority` drives `LoadShedder.admit`, `CircuitBreaker` open state gates before `RetryPolicy`). This is why the set is 12 primitives rather than one monolithic "Resiliency" tool.

### Why `TimeoutBudget` is its own primitive, not a parameter
The Google SRE Workbook (Ch. 22 "Addressing Cascading Failures") and Envoy's `x-envoy-expected-rq-timeout-ms` header both demonstrate that the deadline must *shrink* on every hop. A per-call timeout parameter cannot shrink. A monotonic deadline propagated via a `ContextVar` can — and must — shrink.

### Why retries require idempotency and a budget, not just backoff
Marc Brooker's 2015 AWS post "Exponential Backoff and Jitter" showed that exponential backoff without jitter synchronizes retry storms. Google SRE Workbook Ch. 22 adds the second half: without a retry budget, retries amplify by N per layer, turning a localized outage into a cascade. `RetryPolicy.budget_ratio` and `RetryPolicy.requires_idempotency` are the two invariants that prevent both failure modes.

### Why `BackpressureSignal` is separate from `LoadShedder`
They are duals: `LoadShedder` decides admission at the consumer's front door; `BackpressureSignal` teaches the producer to slow down. Reactive Streams 1.0.4 §2.1 made this separation explicit with `Subscription.request(n)`. A system that only has shedding drops traffic after the producer already paid to create it.

### Why `HealthProbe` separates liveness from readiness
Kubernetes v1.29 probes documentation makes the classic failure explicit: if liveness flips on a slow dependency, the kubelet restarts a healthy process, and the slow dependency causes a *crash-loop* instead of a degradation. `HealthProbe` enforces in the invariants that liveness responds only to forward-progress failures, never to dependency slowness.

### Why `ChaosInjector` is a primitive, not a test tool
Basiri et al. (IEEE Software 2016, "Chaos Engineering") defined chaos as an experiment that runs in production under a steady-state hypothesis with minimized blast radius. That set of rules IS a contract, and the contract IS the primitive. Shipping chaos as ad-hoc test code loses the blast-radius cap and the observability tagging, both of which are invariants here.

## Cross-cutting insights (7)

1. Resiliency primitives compose into a pipeline: `RequestShape` arrives → `LoadShedder` admits → `Bulkhead` partitions → `TimeoutBudget` bounds → `CircuitBreaker` guards → `RetryPolicy` amplifies with care → `FallbackChain` degrades.
2. Every primitive depends on a monotonic deadline. Without `TimeoutBudget` propagation, retries and circuit-breaker cooldowns drift past the request's real SLA and create zombie work.
3. Separating liveness from readiness (`HealthProbe`) and separating ejection from breaking (`OutlierEjection` vs `CircuitBreaker`) prevents the classic cascade where a slow dependency triggers a crash-loop.
4. Retry budgets and jitter turn the naive N-per-layer amplification into a capped, desynchronized correction — the difference between recovery and a synchronized retry storm.
5. Backpressure and load shedding are dual: one slows producers, the other rejects consumers; both require priority awareness carried by `RequestShape`.
6. Chaos injection is the only mechanism that keeps the other primitives honest; without `ChaosInjector` exercising them, `CircuitBreaker` and `FallbackChain` decay into untested code paths.
7. Every resiliency decision must be observable: state transitions, ejections, sheds, fallbacks and injections emit structured events so the control plane can alert and operators can correlate.

## Gaps observed vs. SKILL-001

- **`TimeoutBudget`**: SKILL-001 has per-call timeouts; no monotonic deadline propagation across async boundaries.
- **`Bulkhead`**: Worker pools and HTTP clients share resources with no partitioning primitive.
- **`RetryPolicy`**: Retry logic is ad-hoc per tool; no shared budget or idempotency gate.
- **`LoadShedder`**: Admission control is binary at the reverse proxy; no priority classes.
- **`ChaosInjector`**: No hooks wired into resiliency primitives; behavior is unverified.
- **`RequestShape`**: Immutable request context is not propagated end-to-end; priority and idempotency keys are lost across hops.

## Source coverage

Fifteen unique sources cited, dominant source at 6/27 ≈ 22% (well below the 70% cap):

| Source | Primitives citing |
|---|---|
| Nygard, *Release It!* 2nd ed. (2018) | 6 |
| Google SRE Workbook (2018) | 6 |
| resilience4j 2.2.0 reference | 3 |
| Google SRE Book (2016) | 2 |
| Envoy HTTP connection manager | 2 |
| Envoy retry policy | 1 |
| Envoy outlier detection | 1 |
| Envoy rate limiting filter | 1 |
| Envoy HTTP fault injection filter | 1 |
| Netflix Tech Blog (Christensen 2011) | 1 |
| Netflix Hystrix wiki archive (2018 retirement) | 1 |
| AWS "Exponential Backoff and Jitter" (Brooker 2015) | 1 |
| Reactive Streams Specification 1.0.4 | 1 |
| Basiri et al. "Chaos Engineering" (IEEE 2016) | 1 |
| Kubernetes probes documentation (v1.29) | 1 |

## Self-check

```
$ skills/SKILL-001-fastapi-production/.venv/bin/python \
    docs/research/contracts/check_deliverable.py \
    --agent 4 --deliverable docs/research/outputs/AGENT_4_RESILIENCY.json
✓ DELIVERABLE VALID
  Agent 4 (RESILIENCY)
  Primitives: 12 (min 10)
  Unique sources: 15 (min 5)
  Insights: 7
  Gaps observed: 6
```
