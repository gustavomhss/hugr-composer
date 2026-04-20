# TelemetryExporter

## What it does (plain language)

TelemetryExporter moves spans, metrics, and logs off the hot path and onto a
backend over OTLP. Batching, retry, and backpressure are concentrated here so
each service does not reinvent them. Product impact: stable tail latency even
when the observability collector has hiccups, and fan-out to multiple backends
without code changes.

## Purpose

Serialize batched spans, metrics, or log records into an OTLP-compatible
envelope and deliver them to a configured endpoint with retry and backpressure.

## When to use and when NOT to use

- USE: telemetry outbound transport only.
- DO NOT USE: for non-telemetry workloads (user-visible API calls, database
  writes).
- DO NOT USE: directly on the hot path — always enqueue via a batch processor
  such as OpenTelemetry's `BatchSpanProcessor` or `PeriodicExportingMetricReader`.

## API surface (catalog fidelity)

The Protocol mirrors the catalog verbatim:

```python
class TelemetryExporter(Protocol):
    signal: Signal
    def export(self, batch: Sequence[object], *, timeout_s: float) -> ExportResult: ...
    def force_flush(self, *, timeout_s: float) -> bool: ...
    def shutdown(self, *, timeout_s: float) -> bool: ...
```

`Signal` is `{TRACES, METRICS, LOGS}`; `ExportResult` is
`{SUCCESS, FAILURE, TIMEOUT}`. See `TelemetryExporter.contract.json`.

## Invariants

| ID | Rule |
|---|---|
| TEX_INV_01 | export() is non-blocking on the hot path; callers enqueue via a BatchSpanProcessor. |
| TEX_INV_02 | Transient failures MUST retry with bounded exponential backoff capped at 30 s. |
| TEX_INV_03 | shutdown() MUST flush; CANNOT accept new exports afterwards. |
| TEX_INV_04 | Wire format MUST conform to OTLP/HTTP protobuf or OTLP/gRPC per spec 1.32. |
| TEX_INV_05 | Authentication headers NEVER appear in logs/spans/errors emitted by exporter. |
| TEX_INV_06 | Export results observable via counter keyed by (signal, result). |

## Retry schedule

`RetrySchedule(max_retries=3, initial_backoff_s=0.1, max_backoff_s=30.0)` —
exponential backoff, capped at 30 seconds. The cap is a non-negotiable upper
bound; if retries exhaust, the batch is dropped and
`exporter.export.count{result="failure"}` increments.

## Thread safety

Export state (counters, batches, logs) is guarded by a lock. Multiple writer
threads are supported; the reference implementation serializes accounting.
Real adapters must preserve the same thread-safety guarantee.

## Operational characteristics

- Latency budget: export returns in `timeout_s` or less. TIMEOUT is returned
  only when the retry loop exceeds the caller's budget; otherwise the result
  is SUCCESS or FAILURE.
- Queue: the exporter has no internal queue; callers wrap it in
  `BatchSpanProcessor` which implements bounded-queue drop-oldest policy.
- Self-observability: `exporter.export.count{signal, result}`,
  `exporter.retry.count{signal}`, `exporter.batch.size{signal}`.
- Alerting: sustained `exporter.export.count{result="failure"}` > 0 paired
  with `exporter.retry.count` rising is the primary signal of collector
  saturation.

## Error model

- `export()` after `shutdown()` raises `TelemetryExporterInvariantError`.
- Construction with `fail_rate` out of `[0, 1]` raises the same error.
- Retry exhaustion returns `ExportResult.FAILURE`; timeout returns
  `ExportResult.TIMEOUT`.

## Security considerations

- Authentication headers (`Authorization`, `x-api-key`, `x-auth-token`,
  `bearer`, `proxy-authorization`) are redacted before any log the exporter
  itself emits. Tests assert redaction for case variants.
- Endpoint credentials must be sourced from a secret store; this primitive
  handles redaction but not credential management.
- The exporter does not log span or metric attribute values verbatim —
  application-level scrubbing happens at the producer.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Specification 1.32 — OTLP Protocol and SDK Exporters.
- Google SRE Book chapter 6 section on exporter reliability.

## Alternatives considered and rejected

- Direct synchronous writes — rejected: network hiccups become tail latency.
- Vendor-native SDKs only — rejected: couples code to one backend.
- File-based sidecar export — rejected: disk-queue management belongs in infra.

## Extension contract

A backend adapter implements the `TelemetryExporter` Protocol for its wire
format, registers with the signal-specific provider, and is composed behind a
`BatchSpanProcessor` / `PeriodicExportingMetricReader` so batching and retry
semantics are preserved independently of the adapter.

## Usage

```python
def flush_on_shutdown(exporter: TelemetryExporter) -> None:
    ok = exporter.force_flush(timeout_s=5.0)
    if not ok:
        raise RuntimeError("telemetry flush timed out")
    exporter.shutdown(timeout_s=2.0)
```

## Compose with:

- **OTLP contract** → `Tracer` + `MetricMeter`
  All signal types share a serializer; swapping backends is a collector-config change, not a code change.

- **Backpressure-aware** → `CircuitBreaker` + `LoadShedder`
  Exporter fails fast when the collector is unavailable; telemetry loss is bounded instead of causing request-path slowdowns.

- **Self-describing batches** → `ResourceDescriptor` + `SemanticAttributes`
  Every batch carries the resource descriptor; the collector attributes data to the right service without extra metadata.
