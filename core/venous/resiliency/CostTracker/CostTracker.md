# CostTracker

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_cost_tracker.py`

## Purpose

`CostTracker` aggregates per-request cost estimates from a pluggable list
of component estimators (`db`, `s3`, `api`, …). Each estimator receives
a request context and returns a USD float; the tracker sums them into a
`CostEstimate` and retains a bounded FIFO history for later analysis.

## Invariants

- **COST_TRACKER_INV_01** — Fail-open cost observation: if an estimator
  raises, the error is caught and logged, NOT propagated; the request
  path is never broken by cost instrumentation.
- **COST_TRACKER_INV_02** — The history ring is bounded by
  `_max_history`; older entries evict FIFO.
- **COST_TRACKER_INV_03** — Conservation: `total_cost_usd` equals the
  sum of the per-component bucket totals on every returned estimate.

Tests: see `test_CostTracker.py`.

## Compose with:

- **Per-request cost attribution** → `RequestShape` + `MetricMeter`
  Tracker composes estimators keyed by component; results ride on the request shape, flushed to metrics — cost per endpoint/tenant is observable, not inferred.

- **Budget-enforced shedding** → `LoadShedder` + `TimeoutBudget`
  When a request exceeds its cost budget, the shedder can drop it before downstream calls fire — budget is a first-class admission signal.

- **LLM cost governance** → `LlmTrace` + `PromptTemplate`
  LLM spans carry template + token cost; tracker sums per template — A/B prompt costs are comparable across releases.
