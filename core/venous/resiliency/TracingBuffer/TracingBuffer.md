# TracingBuffer

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_request_tracing_ui.py`

## Purpose

`TracingBuffer` is a thread-safe in-memory ring buffer of the last N
request trace records. It supports newest-first iteration, lookup by
request id, and a p99-latency "slow requests" query. It is a diagnostic
aid, NOT durable storage — entries vanish on process restart.

## Invariants

- **TRACING_BUFFER_INV_01** — Ring bound: buffer length ≤ `maxlen`;
  overflow evicts the oldest entry (FIFO, `deque(maxlen=...)` semantics).
- **TRACING_BUFFER_INV_02** — Newest-first iteration: `get_all()`
  returns entries in reverse-insertion order.
- **TRACING_BUFFER_INV_03** — Safe id lookup: `get_by_id(id)` returns
  the entry if still in the ring, else `None` — never raises.

Tests: see `test_TracingBuffer.py`.

## Compose with:

- **Dev-time trace inspector** → `Tracer` + `StructuredLogger`
  Ring buffer of the last N traces drives a local UI; developers reproduce issues without spinning up the full OTel stack.

- **Bounded memory** → `CardinalityGuard` + `MetricMeter`
  Fixed-size ring + bounded per-record size prevents a buggy loop from OOMing the process through trace capture.

- **Error-triage bridge** → `ErrorSink` + `CorrelationContext`
  Exception capture attaches the latest traces for the same correlation id — 'what was happening just before this error' is one click.
