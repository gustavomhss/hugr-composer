# RetryPolicy

## What it does (plain language)

RetryPolicy is the single, coordinated place where "should I try this again?"
is answered for the whole service. It decides whether a failed call may be
retried, picks the delay (exponential backoff + jitter), caps total retry
amplification via a shared budget, and refuses to retry anything that is not
provably idempotent. Scattered `try/except: retry` loops are replaced by one
policy object that knows the rules.

## Purpose

Describe under which conditions a failed call may be retried, bounded by max
attempts, backoff with jitter, a retry budget, and an idempotency requirement.

## When to use and when NOT to use

- USE: an outbound call that can fail transiently (network timeouts,
  upstream 5xx, connection resets) where the same call can be safely made
  again (GET, idempotency-keyed POST, etc.).
- DO NOT USE: a non-idempotent mutation without an idempotency key —
  RetryPolicy will refuse to retry and surface `RetryPolicyInvariantError`;
  add the key first.
- DO NOT USE: inside a deeper layer that already retries. Amplification
  compounds across layers; keep retry at one boundary.

## API surface

The catalog `api_signature` in `RetryPolicy.contract.json` is the authority.
Callers construct `ExponentialBackoffRetryPolicy(...)` with sizing
parameters and call `await policy.execute(fn, idempotent=True, budget=...)`.
The optional `budget` is a `TimeoutBudget` carrier that bounds total
wall-clock spent in retries (RETRY-INV-04).

## Invariants

| ID | Rule |
|---|---|
| RETRY_INV_01 | A call MUST NEVER be retried unless it is marked idempotent or the policy has `requires_idempotency=False` by an explicit operator decision. |
| RETRY_INV_02 | The total retry attempts MUST NEVER exceed `budget_ratio` of successful traffic in the trailing window. |
| RETRY_INV_03 | Backoff intervals SHALL include jitter in the range `[0, jitter * base_interval]` to prevent synchronized retry storms. |
| RETRY_INV_04 | Retries CANNOT be issued when the governing `TimeoutBudget.remaining_ms` is less than or equal to zero. |
| RETRY_INV_05 | The policy SHALL classify errors as retryable / non_retryable / fatal and NEVER retry a non-retryable or fatal error. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `RetryBudget` serialises admissions and success counting via an internal
  lock; concurrent executes SHALL NOT overrun `min_floor + budget_ratio *
  successes`.
- `ExponentialBackoffRetryPolicy.execute` is cooperatively safe — it awaits
  `sleep_fn` between attempts and records a bounded attempts_log.
- A single policy object is designed to be shared across the service so that
  amplification is capped across all callers.

## Operational characteristics (for SRE)

- Default classifier: `TimeoutError`, `ConnectionError`, `OSError` → retryable.
  `ValueError`, `TypeError`, `KeyError`, `AttributeError`, and the sentinel
  `NonRetryableError` → non-retryable. `FatalError` → fatal.
- Backoff schedule: exponential with multiplier, capped at `max_interval_ms`,
  then full jitter in `[0, jitter * base]`.
- Budget: `min_floor` allows bootstrap retries before any success is recorded;
  increase it only if the service serves low-volume workloads.
- Primary symptom of pathology: `retry.refusals` rising with `reason="budget"`
  or `reason="non_idempotent"` — investigate upstream, do NOT raise the floor.
- Observability: `retry.attempts` (counter, `outcome` label), `retry.delay.ms`
  (histogram, `attempt` label), `retry.refusals` (counter, `reason` label).

## Security considerations

- The policy refuses to retry non-idempotent mutations without an explicit
  idempotency key; this stops double-charging, double-posting, and duplicate
  emails on transient errors.
- Because retry bodies are opaque callables, the policy MUST be used on the
  outbound side of an authenticated call — never retry a failed AuthN call.
- `FatalError` short-circuits the loop after one attempt; use it to signal
  irreversible conditions (credentials revoked, invalid signing key).

## Provenance

- Source agent: Agent #4 RESILIENCY
  (`docs/research/outputs/AGENT_4_RESILIENCY.json`).
- Primary sources:
  - Beyer et al., *Google SRE Workbook* (O'Reilly, 2018), Chapter 22
    "Addressing Cascading Failures" — retries section (amplification, budgets).
  - Brooker, "Exponential Backoff and Jitter", AWS Architecture Blog (2015) —
    Full Jitter and Decorrelated Jitter formulas.
  - Envoy proxy docs, `RetryPolicy` (`retry_on`, `num_retries`, `retry_budget`).

## Alternatives considered and rejected

- Transport-level retry only (HTTP client defaults) — lacks idempotency and
  budget awareness; amplifies failure across layers.
- Caller-written try/except loops — reinvent classification and NEVER
  coordinate across callers.
- Fire-and-forget retries via queue — shifts the problem and CANNOT enforce
  a wall-clock deadline.

## Extension contract

Adopters subclass or register a `RetryClassifier` that maps exceptions to
retryable / non_retryable / fatal; adopters may also bind a `BackoffStrategy`
provider (the reference policy implements exponential_with_jitter). The
retry budget enforcer is sealed: it reads from the shared trailing-window
success counter via `RetryBudget` and cannot be bypassed by subclassing.

## Schema of `RetryPolicy.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from RetryPolicy import ExponentialBackoffRetryPolicy, TimeoutBudget

policy = ExponentialBackoffRetryPolicy(
    max_attempts=3,
    initial_interval_ms=100,
    multiplier=2.0,
    max_interval_ms=30_000,
    jitter=1.0,
    budget_ratio=0.1,
    requires_idempotency=True,
)

async def post_charge() -> Receipt:
    return await policy.execute(
        lambda: _charge("idempotency-key-42"),
        idempotent=True,
        budget=TimeoutBudget(remaining_ms=5_000),
    )
```

## Compose with:

- **Safe retries** → `IdempotentConsumer` + `RequestShape`
  Retries reuse the request's idempotency key; the downstream consumer dedupes — at-least-once transport never causes double effects.

- **Bounded cost** → `TimeoutBudget` + `CircuitBreaker`
  Backoff respects the remaining budget; the breaker opens before retries become a feedback loop.

- **Jittered fan-out** → `OutboundBinding` + `RpcInterceptor`
  Policy mounts as an interceptor with per-vendor jitter; synchronized retries across pods are impossible by construction.

- **Bounded optimistic-concurrency retry** → `OptimisticConcurrency` + `AuditEvent`
  `RetryPolicy` wraps the CAS write with a budgeted exponential-backoff loop; each `ConcurrencyError` triggers a retry until budget exhaustion, at which point the audit trail records the lost update as an explicit failure. Invariant gained: lost-update bugs surface as budget exhaustions, not silent overwrites.
