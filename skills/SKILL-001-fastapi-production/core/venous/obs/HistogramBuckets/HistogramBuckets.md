# HistogramBuckets

## What it does (plain language)

HistogramBuckets pins the latency and size boundaries for histogram
instruments. Shared buckets mean p99 latency means the same thing across every
service, every release, every dashboard. Product impact: apples-to-apples SLO
reporting; release regressions never hide behind inconsistent slicing.

## Purpose

Define explicit latency and size bucket boundaries for histogram instruments
so quantile estimation is accurate and comparable across services.

## When to use and when NOT to use

- USE: as the canonical preset registry for latency and payload-size
  histograms. Bind a preset to a histogram at instrument creation.
- DO NOT USE: for arbitrary gauges or counters — those are different instrument
  kinds with no bucket concept.
- DO NOT USE: as a runtime-tunable configuration. Boundaries are immutable
  because quantile history needs consistent bin edges.

## Invariants

| ID | Rule |
|---|---|
| HB_INV_01 | Boundaries MUST be strictly increasing, finite, non-negative, ≥5 below p99. |
| HB_INV_02 | Boundaries immutable once assigned; runtime changes FORBIDDEN. |
| HB_INV_03 | Latency MUST use UCUM unit 'ms'; NEVER mixed with 's' on the same instrument. |
| HB_INV_04 | Lowest boundary MUST be smaller than the realistic measurement floor. |
| HB_INV_05 | Bucket count SHALL NOT exceed 20 per instrument (storage cost bound). |
| HB_INV_06 | Default HTTP latency / payload buckets MUST follow OTel semconv. |

## API surface (catalog fidelity)

`HistogramBuckets` is a frozen dataclass with fields `name: str`, `unit: str`,
`boundaries: Sequence[float]`, and the two catalog-mandated classmethods
`latency_ms_default()` and `payload_bytes_default()` returning canonical
preset instances. The catalog entry is reproduced verbatim in
`HistogramBuckets.contract.json`.

## Thread safety

Instances are frozen dataclasses. All helpers are pure functions with no
shared mutable state. Safe to construct and share across threads and event
loops.

## Operational characteristics

- Cost at instrument creation: one-time O(n) validation, then free.
- Default preset exposes 12 buckets for HTTP latency covering
  1 ms → 10 000 ms.
- Default payload preset exposes 6 buckets covering 100 B → 10 MB.
- Self-observability: `histogrambuckets.built.count{unit}`,
  `histogrambuckets.rejections{reason}`.

## Error model

- Violating boundary order, finiteness, count cap, or unit discipline raises
  `HistogramBucketsInvariantError` with a message that names the invariant ID.
- Input fixtures that look correct but mix `bool` with numerics are rejected
  because `bool` is a subclass of `int` in Python and would silently drift the
  histogram shape.

## Security considerations

- Bucket boundaries are not PII; they are published in SemConv. No redaction
  required.
- The `name` field is injected into metric series names; callers must avoid
  putting tenant-specific data there (use attribute labels instead).

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- Prometheus documentation — Histograms and Summaries, bucket guidance.
- OpenTelemetry Semantic Conventions 1.27 — HTTP Metrics.
- Google SRE Book chapter 6 — Four Golden Signals.

## Alternatives considered and rejected

- Exponential histogram (HDR-style) — rejected: backend support uneven in 2026.
- Client-side summary quantiles — rejected: cannot be aggregated across instances.
- Per-service ad-hoc buckets — rejected: cross-service comparison is required.

## Extension contract

Tools extend defaults by registering a named bucket preset (e.g. `db.query.latency`,
`llm.completion.latency`) through a `HistogramProvider` adapter. Callers bind a
preset to an instrument at creation time; the preset carries version metadata
so dashboards can detect boundary changes across releases.

## Usage

```python
def checkout_latency(meter: MetricMeter) -> None:
    preset = HistogramBuckets.latency_ms_default()
    instrument = meter.histogram(
        preset.name, unit=preset.unit, description="checkout latency",
        boundaries=preset.boundaries,
    )
    instrument.record(34.5, {"checkout.step": "payment"})
    assert preset.unit == "ms"
```

## Compose with:

- **Stable quantiles** → `MetricMeter` + `SemanticAttributes`
  Fixed buckets let alerts on p99 compare like-for-like across deploys; a silent bucket change cannot invalidate the SLO.

- **Budgeted cardinality** → `CardinalityGuard` + `MetricMeter`
  Bucket count × label cardinality is bounded at registration — the metrics bill does not drift with the codebase.

- **Aligned sampling** → `SamplingPolicy` + `Tracer`
  Tail-based sampling uses the same buckets as histogram boundaries; retained traces line up with the outlier tail of the distribution.
