# Tracer

## What it does (plain language)

Tracer records a named "work unit" called a *span* for every request that flows
through the system, captures how long it took, and attaches metadata. Those
spans are joined across services so engineers can see the full path of a user
request end-to-end, diagnose incidents faster, and report on SLA-level metrics.
Operators get per-request visibility; the product gets predictable latency
reporting.

## Purpose

Create spans that represent a unit of work, attach attributes and events, link
related spans, and propagate context across process and network boundaries.

## When to use and when NOT to use

- USE: request lifecycles, outbound RPC, database calls, message produce/consume,
  long-running background jobs.
- DO NOT USE: high-frequency, per-iteration instrumentation inside a hot loop
  (record a single span around the loop and attributes for the counts).
- DO NOT USE: append-only audit records — those belong to `AuditEvent`.

## API surface

The catalog `api_signature` is the sole authority; see `Tracer.contract.json`
for the verbatim Protocol declaration. The implementation `Tracer.py` re-declares
the Protocol and provides `InMemoryTracer` as a reference. A span is a context
manager exposing `set_attribute`, `add_event`, `record_exception`, and
`set_status`. `inject` and `extract` move W3C trace context onto / off of
serialisable carriers (HTTP headers, queue attributes). `start_as_current_span`
opens a new span and makes it "current" for context-aware consumers such as
`StructuredLogger`.

## Invariants

| ID | Rule |
|---|---|
| TRACER_INV_01 | Every span MUST have a non-empty name, a start timestamp, and an end timestamp in that causal order. |
| TRACER_INV_02 | A span CANNOT be ended twice; a second end call SHALL be a no-op with a recorded internal warning. |
| TRACER_INV_03 | The tracer MUST honor W3C Trace Context headers on inject and extract without mutation of unknown tracestate entries. |
| TRACER_INV_04 | Recording an exception MUST set the span status code to ERROR unless the caller explicitly overrides with OK. |
| TRACER_INV_05 | Attribute values MUST be str, bool, int, float, or a homogeneous sequence; nested structures are FORBIDDEN. |
| TRACER_INV_06 | The tracer SHALL NEVER block the caller waiting for exporter acknowledgement; export is asynchronous. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- All `Span` mutating methods (`set_attribute`, `add_event`, `record_exception`,
  `set_status`, `end`) are thread-safe via an internal lock.
- `InMemoryTracer.start_as_current_span` is safe under concurrent callers; each
  call returns an independent span.
- Context propagation across async tasks is delegated to `CorrelationContext`
  (contextvars-based). The Tracer itself does not hold per-loop state.

## Operational characteristics (for SRE)

- Export is non-blocking by contract (TRACER_INV_06). Real deployments back the
  in-process tracer with a bounded `BatchSpanProcessor`; overflow policy is
  **drop-oldest-on-full** with an `tracer.spans.dropped` counter surfaced.
- Self-observability: `tracer.spans.created`, `tracer.span.duration`,
  `tracer.export.calls`. A sustained increase in `dropped` or `export.calls` with
  `result="error"` label is the primary symptom of collector saturation.
- Export failure policy: retry with exponential backoff, capped at 30s; after
  the cap the batch is dropped and a structured log is emitted with the
  aggregate count.
- Attribute cardinality: follow `CardinalityGuard` guidance; the tracer itself
  neither enforces nor flags cardinality.

## Security considerations

- Tracer MUST NOT be used for audit trails. `AuditEvent` is the tamper-evident
  primitive; spans are lossy and best-effort.
- Attribute scrubbing: the tracer does not automatically redact attribute
  values. Callers are responsible for not attaching PII (`enduser.id` is
  acceptable; full email addresses, PAN, or session tokens are FORBIDDEN).
- Incoming traceparent / tracestate headers MUST be validated (TRACER_INV_03);
  the tracer caps tracestate at the W3C-specified 32 entries to prevent
  amplification via oversized headers. Invalid traceparent values do not
  poison the downstream context; they are dropped and a fresh trace_id
  is generated.
- Credential leak: the tracer refuses attribute values that contain nested
  structures, which eliminates a common accidental-credential-leak vector
  (logging an entire request dict).

## Provenance

- Source agent: Agent #7 OBSERVABILITY
  (`docs/research/outputs/AGENT_7_OBSERVABILITY.json`).
- Primary sources:
  - OpenTelemetry Specification 1.32 — Trace API
    (`specification/trace/api.md` sections Tracer / Span / SpanKind / Span.End).
  - W3C Trace Context Recommendation Level 1 (traceparent + tracestate).
  - Majors, Fong-Jones, Miranda — *Observability Engineering* (2022), chapter 6.

## Alternatives considered and rejected

- Per-framework tracer (FastAPI-specific decorator) — rejected because
  propagation breaks at the first out-of-framework hop (worker, CLI, cron).
- OpenTracing API — rejected as archived in 2022; OpenTelemetry supersedes it.
- Log-only correlation with request_id — rejected because it loses parent/child
  causality and span timing.

## Extension contract

A downstream tool extends tracing by registering a `SpanProcessor` adapter
against the `TracerProvider`. Custom attribute semantics are added via a
semantic-convention plugin (`SemanticAttributes` subclass) that maps domain
keys to OTel attribute names. Context propagation formats are added by
registering a `TextMapPropagator` implementation. Extensions must preserve
the six invariants above. Semver: the Protocol surface is v1; additive
processors may be registered without breaking callers.

## Schema of `Tracer.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the full
standards governing each field.

## Usage

```python
def charge_card(tracer: Tracer, amount_cents: int, customer_id: str) -> str:
    # Open a CLIENT span for the gateway round-trip; attributes become
    # queryable in the backend for p99 latency and error-rate reporting.
    with tracer.start_as_current_span(
        "payment.charge",
        kind="CLIENT",
        attributes={"payment.amount_cents": amount_cents, "enduser.id": customer_id},
    ) as span:
        try:
            receipt_id = _call_gateway(amount_cents)
        except Exception as exc:
            # INV-04: record_exception auto-sets ERROR unless overridden.
            span.record_exception(exc)
            raise
        span.set_attribute("payment.receipt_id", receipt_id)
        return receipt_id
```

## Compose with:

- **End-to-end traces** → `CorrelationContext` + `SemanticAttributes`
  Spans inherit context across threads, tasks, and RPCs; attribute keys come from semconv — distributed traces line up without per-service wiring.

- **Budgeted observability** → `SamplingPolicy` + `TelemetryExporter`
  Sampling controls volume; exporter handles delivery; the product gets a representative, bounded trace stream.

- **Debuggable errors** → `ErrorSink` + `StructuredLogger`
  Uncaught exceptions attach to the active span; the error triage UI links to the full trace and log trail.
