# CardinalityGuard

## What it does (plain language)

CardinalityGuard is the circuit breaker that prevents a single unbounded label
(user id, raw URL) from exploding the time-series database. It is the difference
between a 10x cost overnight and a bounded bill. Product impact: dashboards stay
queryable, on-call is not paged at 3am for ingestion back-pressure.

## Purpose

Bound the unique attribute-value combinations attached to a metric or log stream
to prevent label explosion from breaking time-series databases.

## When to use and when NOT to use

- USE: at the metric instrument boundary, before values are recorded.
- DO NOT USE: for high-cardinality keys that are *intentionally* unbounded
  (store those in logs, not metrics).
- DO NOT USE: after the emit step — the damage is done at admit time.

## Invariants

| ID | Rule |
|---|---|
| CARD_INV_01 | Per-metric limit reached → new combinations MUST collapse to a single 'overflow' series. |
| CARD_INV_02 | Per-key limit reached → new values for that key MUST collapse. |
| CARD_INV_03 | Default deny-list FORBIDS user.id, url.full, email, freeform query strings. |
| CARD_INV_04 | Admission SHALL be deterministic for (metric, attributes) in a window. |
| CARD_INV_05 | Guard NEVER mutates caller's mapping; ALWAYS returns a new mapping. |
| CARD_INV_06 | Overflow events MUST be observable via a dedicated counter. |
| CARD_INV_07 | configure CANNOT be called after the first admit. |

## Thread safety

All mutating methods hold an internal lock; safe under concurrent callers.

## Operational characteristics

- Overflow counter: `cardinality.overflow.count{metric, reason}` — alert on
  sustained non-zero rate. Scale the limits or narrow the attribute set.
- Typical call cost: O(1) hash lookups per attribute key, amortized.
- Memory: O(per_metric_limit × per_key_limit × num_metrics) bounded.

## Security considerations

- Email addresses in any attribute value are automatically redacted to avoid
  PII leakage into the TSDB.
- The deny-list is a safe default; it does not replace a data-classification
  policy at the producer layer.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- Prometheus documentation — instrumentation, "Do not overuse labels".
- *Observability Engineering* (2022), chapter 1 on cardinality costs.
- OpenTelemetry Specification 1.32 — Metrics SDK Views.

## Alternatives considered and rejected

- Relying on operators to audit dashboards — rejected: blast radius lands in
  production before review.
- Per-metric hardcoded allowlists — rejected: coverage drifts as new instruments
  are added.
- Downstream TSDB-side label limits — rejected: by the time the TSDB refuses,
  agent buffer and network already paid the cost.

## Extension contract

Teams extend the guard by registering a domain-specific key classifier
(e.g. an adapter that maps user_id → 'uid_redacted'), by composing a deny-list
plugin that supplements the default patterns, and by subclassing the guard to
emit overflow events to a custom TelemetrySink.

## Usage

```python
def record_request(meter: MetricMeter, guard: CardinalityGuard, route: str, user_id: str, status: int) -> None:
    hist = meter.histogram("http.server.duration", unit="ms", description="HTTP latency")
    safe_attrs = guard.admit("http.server.duration", {
        "http.route": route,
        "user.id": user_id,
        "http.response.status_code": str(status),
    })
    hist.record(12.4, safe_attrs)
    assert "user.id" not in safe_attrs or safe_attrs["user.id"] == "overflow"
```

## Compose with:

- **Safe labeling** → `MetricMeter` + `SemanticAttributes`
  High-cardinality labels (user id, trace id) are rejected at registration; developers cannot accidentally 10x the metrics bill.

- **Bounded log dimensions** → `StructuredLogger` + `SemanticAttributes`
  Structured log fields are capped to a declared set; 'just add one more dimension' goes through review, not PR auto-merge.

- **Quantile integrity** → `HistogramBuckets` + `MetricMeter`
  Fixed buckets + bounded cardinality keep p99 estimation honest; a hot label does not collapse bucket fidelity.
