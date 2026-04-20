# RetryBudget

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_retry_budget.py`

## Purpose

`RetryBudget` implements a sliding-window retry-ratio limiter so a caller
cannot amplify a partial-downstream outage into a full outage through
retry storms. Over a rolling window (`window_s`), it tracks total
requests and retries; once the window contains at least `min_requests`
samples, it blocks further retries when `retries / total > ratio`.

## Invariants

- **RETRY_BUDGET_INV_01** — Warm-up bypass: below `min_requests`,
  `can_retry()` is unconditionally True (prevents false positives on
  cold start).
- **RETRY_BUDGET_INV_02** — Ratio enforcement: after warm-up,
  `can_retry()` is False iff the retry fraction strictly exceeds the
  configured `ratio` over the current window.
- **RETRY_BUDGET_INV_03** — Window freshness: samples older than
  `window_s` MUST be evicted on every observation so decisions always
  reflect recent traffic, not cumulative lifetime counts.

Tests: see `test_RetryBudget.py`.

## Compose with:

- **Retry-storm prevention** → `RetryPolicy` + `CircuitBreaker`
  Sliding-window ratio gate ensures retries cannot exceed a fraction of the window; a partial outage does not amplify into a full outage.

- **Budget-aware policy** → `TimeoutBudget` + `RequestShape`
  Retry admission considers remaining request budget and priority class — low-priority retries yield first under pressure.

- **Observable retry health** → `MetricMeter` + `HealthProbe`
  Retry ratio is a first-class metric; a breaker-style readiness flip fires before customer impact.
