# MetricMeter

## What it does (plain language)

MetricMeter is the single factory for counters, histograms, and gauges. Shared
naming + shared units means dashboards stay portable, unit drifts ("is it ms
or s?") are impossible, and tail-latency reporting is credible. Product impact:
cross-service SLO math works.

## Purpose

Record numeric measurements through four instrument shapes — counter,
up-down counter, histogram, asynchronous gauge — under OpenTelemetry metric
semantics.

## When to use and when NOT to use

- USE: request rates, error counts, latency histograms, queue depth, resource
  utilisation.
- DO NOT USE: high-cardinality dimensions (route with user_id) — let
  `CardinalityGuard` screen attributes first.
- DO NOT USE: audit trails — those are `AuditEvent`.

## Invariants

| ID | Rule |
|---|---|
| METRIC_INV_01 | Counter MUST reject negative values; silent clamping FORBIDDEN. |
| METRIC_INV_02 | Histogram boundaries MUST be finite, strictly increasing, immutable. |
| METRIC_INV_03 | Names MUST match OTel regex; CANNOT collide across instrument kinds. |
| METRIC_INV_04 | Every instrument MUST carry a UCUM unit string. |
| METRIC_INV_05 | Observable gauge callbacks MUST be idempotent and SHALL NEVER raise observably. |
| METRIC_INV_06 | Attribute sets NEVER include unbounded-cardinality keys. |

## Thread safety

All instruments' mutating calls (`add`, `record`) are lock-protected. The
`observable_gauge` callback is invoked from the collection thread; callbacks
MUST be thread-safe.

## Operational characteristics

- Call cost: O(1) per `add`/`record`.
- Gauge exceptions are swallowed and reported via a counter
  (`meter.gauge.dropped`).
- Name collisions across kinds raise at construction, surfacing drift at CI.

## Security considerations

- The forbidden-cardinality-keys list blocks accidental PII paths
  (`user.id`, `request.id`, `trace_id`). This is belt-and-braces with
  `CardinalityGuard`.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Specification 1.32 — Metrics API.
- Prometheus documentation — Histograms and Summaries.
- OpenTelemetry Semantic Conventions 1.27 — Metric Naming.

## Alternatives considered and rejected

- StatsD client per tool — rejected: no unit metadata, no bucket control.
- Prometheus client library directly — rejected: binds to pull-only collection.
- Pure log-derived metrics — rejected: aggregation at ingest is costly.

## Extension contract

Downstream tools register a `MetricReader` adapter (Prometheus scrape or OTLP
push) and extend instrumentation by subclassing the meter provider to add a
`View` that renames, filters, or re-aggregates instruments without mutating
existing instrument contracts.

## Usage

```python
def record_checkout(meter: MetricMeter, duration_ms: float, status: str) -> None:
    latency = meter.histogram("http.server.duration", unit="ms", description="HTTP server latency")
    errors = meter.counter("checkout.failures", unit="1", description="Failed checkouts")
    latency.record(duration_ms, {"http.route": "/checkout", "http.response.status_code": status})
    if status.startswith("5"):
        errors.add(1, {"http.route": "/checkout"})
```

## Compose with:

- **Safe instruments** → `HistogramBuckets` + `CardinalityGuard`
  Every instrument declares buckets and bounded labels; stability across deploys is mechanical, not cultural.

- **Conventional attribute schema** → `SemanticAttributes` + `TelemetryExporter`
  Labels use OTel semconv keys; exports land in dashboards without a per-service mapping layer.

- **SLO-grade signal** → `HealthProbe` + `SamplingPolicy`
  The same histograms drive readiness thresholds and tail sampling; SLO math is one query.

- **Hot-key counter observability** → `ShardedCounter` + `CorrelationContext`
  Every `ShardedCounter.increment` emits a metric tagged with the shard id and the correlation id from `CorrelationContext`; shard skew lights up a dashboard heatmap before it degrades latency. Invariant gained: routing regressions surface as metrics, not as oncall pages.
