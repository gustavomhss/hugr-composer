# ErrorSink

## What it does (plain language)

ErrorSink captures every uncaught exception, groups them by stable fingerprint,
attaches request context, and forwards to the error backend without blocking
the request. Support knows when incidents are new vs repeat; on-call is not
paged 50 times for the same bug. Product impact: faster MTTD and lower alert
fatigue.

## Purpose

Capture uncaught exceptions with fingerprint grouping, attach current trace
and correlation context, apply sampling, and forward to an error-tracking
backend.

## When to use and when NOT to use

- USE: exceptions the service did not recover from, including business
  exceptions explicitly flagged for capture.
- DO NOT USE: expected validation failures (return to caller; do not capture).
- DO NOT USE: for audit trails (use `AuditEvent`).

## Invariants

| ID | Rule |
|---|---|
| ERR_INV_01 | Captured event MUST include active trace_id/span_id/request_id when set. |
| ERR_INV_02 | Fingerprint MUST be deterministic per (exception type, top-3 frames). |
| ERR_INV_03 | capture_exception MUST redact registered PII fields before transport. |
| ERR_INV_04 | Sink CANNOT block caller; transmission SHALL run on background worker. |
| ERR_INV_05 | before_send returning None MUST drop; NEVER partial transmit. |
| ERR_INV_06 | Sampling SHALL apply AFTER fingerprinting; rare variants not head-dropped. |

## Thread safety

Captures are thread-safe via an internal queue. The background worker drains
with a 5ms tick; `flush()` synchronously awaits drain for tests and shutdown.

## Operational characteristics

- Capture latency: O(1) queue enqueue; no network on the hot path.
- Queue overflow: unbounded in the reference implementation; deployments wrap
  with a bounded-queue `TransportAdapter`.
- Self-observability: `errorsink.events.captured{level}`,
  `errorsink.events.dropped{reason}`, `errorsink.queue.depth`.

## Security considerations

- Default PII deny-list covers `email`, `password`, `authorization`, `ssn`,
  `cpf`, `pan`, `bearer`, `cookie`, `api_key`, `credit_card`. Custom filters
  are registered via `before_send`.
- Redaction runs before any transport hook, so even malicious `before_send`
  implementations cannot observe raw PII.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- *Observability Engineering* (2022), chapter 5.
- OpenTelemetry Specification 1.32 — Exceptions.
- Google SRE Book chapter 6 — Four Golden Signals.

## Alternatives considered and rejected

- Relying on log aggregation for errors — rejected: no fingerprint grouping.
- Per-framework exception middleware — rejected: background jobs fall outside.
- Raw stacktrace hashing only — rejected: line-number drift splits issues.

## Extension contract

Tools extend the sink by registering a fingerprinter callable, registering a
before_send filter that redacts or drops events, and implementing a
`TransportAdapter` that speaks the target vendor's envelope while preserving
the neutral event payload.

## Usage

```python
def process_order(sink: ErrorSink, order_id: str) -> None:
    try:
        _settle(order_id)
    except PaymentDeclined as exc:
        event_id = sink.capture_exception(
            exc,
            level="warning",
            tags={"order.id": order_id, "payment.gateway": "stripe"},
            extras={"retry_count": 2},
        )
        _notify_ops(event_id)
        raise
```

## Compose with:

- **Grouped triage** → `StructuredLogger` + `Tracer`
  Exceptions are fingerprinted, deduped, and linked to the active span — one incident produces one issue, not one per request.

- **Context-rich capture** → `CorrelationContext` + `CurrentPrincipal`
  Each captured error carries principal, correlation, and request context — reproducing the bug does not require the customer's cooperation.

- **Health integration** → `HealthProbe` + `MetricMeter`
  Spike-based probes turn red on sudden exception rates; pages fire before synthetic checks notice.
