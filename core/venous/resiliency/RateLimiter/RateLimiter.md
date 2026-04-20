# RateLimiter

## What it does (plain language)

RateLimiter is the per-key admission governor that caps how often a caller,
tenant, or resource is allowed to proceed in a given window. Every call site
that wants protection hands a key (e.g. the tenant id) to the limiter along
with an optional cost (how "expensive" the operation is) and a wait budget
(how long the caller is willing to queue). The limiter answers yes (and
consumes tokens), queues briefly and then answers yes, or refuses with a
typed `RateLimitedError` that carries `retry_after_ms`.

## Purpose

Enforce a maximum rate of admitted operations over a rolling window, with
optional waiting semantics, applied per caller, tenant or resource.

## When to use and when NOT to use

- USE: per-tenant quotas on internal service endpoints to stop one noisy
  tenant from harming all others.
- USE: outbound cost-amplifying fan-out (one incoming call => many downstream
  calls) where a cost > 1 is the honest price of the operation.
- USE: adversarial-login throttling (the security cross-cut from Agent 5 is
  preserved in the merged invariants).
- DO NOT USE: as the ONLY defense against a failing dependency — pair with a
  `CircuitBreaker` (short-circuits the dependency when it is sick) and
  `TimeoutBudget` (caps wall-clock budget per request).
- DO NOT USE: at the edge alone — edge-only rate limits ignore internal
  fan-out amplification.

## API surface

The catalog `api_signature` in `RateLimiter.contract.json` is the authority.
Callers use `try_acquire(key, cost=1)` for non-blocking attempts, and
`await acquire(key, cost=1, wait_ms=N)` when brief queuing is acceptable.
The reference implementation is `InMemoryRateLimiter`; distributed deployments
register a `CounterAdapter` (Redis, distributed log) via the extension
contract. The `AlgorithmProvider` hook lets adopters swap the default
token-bucket for leaky-bucket or sliding-window-log.

## Invariants

| ID | Rule |
|---|---|
| RATE_INV_01 | The long-run admitted rate per key MUST NEVER exceed `rate_per_second` over any window longer than `burst / rate_per_second` seconds. |
| RATE_INV_02 | A caller SHALL NEVER block for longer than `wait_ms`; after that the limiter MUST raise `RateLimitedError`. |
| RATE_INV_03 | State for a key CANNOT be shared across unrelated services; key scoping is FORBIDDEN from being implicit. |
| RATE_INV_04 | A rejection MUST include `retry_after_ms` information computed from the current depletion of the bucket. |
| RATE_INV_05 | The limiter SHALL distinguish `cost > 1` so large operations consume proportional tokens and NEVER equal `cost == 1`. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding; TLA+ safety properties in
`RateLimiter.tla` back the same invariants with machine-checked proofs
(`TokensBounded`, `TokensNonNegative`, `ClockBounded`).

## Thread and async safety

- `InMemoryRateLimiter` serialises bucket reads and token mutations via an
  internal `RLock`, so concurrent `try_acquire` callers on the same key
  CANNOT over-admit past `burst`.
- `acquire(..., wait_ms)` releases the lock between polls and uses
  `asyncio.sleep` so the event loop is never blocked for the full wait
  window, and one slow key CANNOT stall admissions for other keys.
- One limiter instance is safe to share across an entire service's request
  pipeline — the key string defines the partition.

## Operational characteristics (for SRE)

- `ratelimiter.admissions` (counter, labels: limiter, outcome) is the
  primary dashboard signal; an elevated `outcome="rejected"` rate for a
  limiter is a fairness alert (one tenant is starving others).
- `ratelimiter.wait.duration` (histogram, ms) bounds the queuing latency
  even under contention; the p99 should never exceed `wait_ms`.
- `ratelimiter.tokens` (gauge, labels: limiter, key) exposes per-key bucket
  depletion for on-call dashboards — useful for finding the top 3 loud
  tenants without log grepping.
- Operators call `reset(key)` during planned maintenance to clear a bucket
  (e.g. after a quota change) without disturbing other keys.

## Security considerations

- The limiter stores only a token count and a monotonic timestamp per key;
  no request payloads, no customer data. A `reset(key)` cannot leak state
  because the bucket is discarded, not archived.
- Key validation refuses non-string / empty / oversized keys (RATE_INV_03)
  so a malicious caller cannot inflate the bucket map to exhaust memory.
- `bool` is explicitly rejected as a cost (RATE_INV_05) to prevent the
  subtle Python pitfall where `True == 1` collapses proportional accounting.
- Event log entries carry the key verbatim; callers MUST NOT embed secrets
  in keys (operators should hash bearer tokens before using them as keys).

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Merged canonical spec: `docs/research/COLLISIONS_RESOLVED.md` §2.
- Primary sources:
  - Nygard, *Release It!* 2nd ed. (2018) — Chapter 5, pages 137-143
    ("Governor" and "Shed Load").
  - Google SRE Workbook (O'Reilly, 2018) — Chapter 21 "Managing Load".
  - Envoy proxy documentation, `token_bucket` filter
    (`api-v3/extensions/filters/http/local_ratelimit/v3`).
  - Algorithm adapted from the `limits` library
    (https://github.com/alisaifee/limits, MIT).

## Alternatives considered and rejected

- Edge-only rate limiting — ignores internal fan-out amplification per
  request.
- Quotas enforced by billing after the fact — NEVER prevents real-time damage.
- Connection count limits — a proxy for rate that CANNOT distinguish cheap
  from expensive calls.

## Extension contract

Adopters register an `AlgorithmProvider` (`token_bucket`, `leaky_bucket`,
`sliding_window_log`) and bind a `KeyExtractor` middleware that produces the
partition key from request context (tenant, api_key, route_pattern). Counter
storage is pluggable via a `CounterAdapter` (in-memory, Redis, distributed
log). The Protocol surface itself (`algorithm`, `rate_per_second`, `burst`,
`acquire`, `try_acquire`, `current_rate`) remains sealed.

## Schema of `RateLimiter.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
limiter = InMemoryRateLimiter(rate_per_second=100.0, burst=200)

# Non-blocking admission.
if not limiter.try_acquire(tenant_id, cost=1):
    raise TooManyRequests(tenant_id)

# Queuing admission with a small wait budget.
try:
    await limiter.acquire(tenant_id, cost=5, wait_ms=50)
except RateLimitedError as e:
    response.headers["Retry-After"] = str(e.retry_after_ms // 1000)
    raise TooManyRequests(tenant_id) from e
```

## Compose with:

- **Per-tenant fairness** → `RequestShape` + `AuditEvent`
  Buckets are keyed by tenant / principal; noisy neighbors are throttled and audited — operators never wonder whose traffic spiked.

- **Abuse protection** → `RequestGuard` + `AuditEvent`
  Auth failures hit a stricter bucket; brute-force attempts audit with velocity — the guard and limiter act as one admission layer.

- **Composed with shedding** → `LoadShedder` + `Bulkhead`
  Rate limits cap steady-state; shedder cuts transient spikes; bulkheads isolate pools — three primitives, one admission SLO.
