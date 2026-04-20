# StructuredLogger

## What it does (plain language)

StructuredLogger writes JSON log records with guaranteed shape, automatic trace
correlation, and built-in redaction of secrets. Support engineers query with
one SQL-like pipeline; nobody grep-parses unstructured lines; bearer tokens
never reach the ingest pipe. Product impact: debugging is a query, not a
scavenger hunt.

## Purpose

Emit machine-parseable key/value log records with a fixed level taxonomy,
attached trace and span identifiers, and no positional string formatting.

## When to use and when NOT to use

- USE: general-purpose structured logging from application code.
- DO NOT USE: audit trails (use `AuditEvent`).
- DO NOT USE: metrics aggregation (use `MetricMeter`).

## Invariants

| ID | Rule |
|---|---|
| LOG_INV_01 | Every record MUST be one line of UTF-8 JSON with ts/level/event plus caller fields. |
| LOG_INV_02 | Log level SHALL be one of DEBUG/INFO/WARN/ERROR; TRACE/FATAL FORBIDDEN. |
| LOG_INV_03 | Active span → record MUST include trace_id/span_id in hex. |
| LOG_INV_04 | Formatting placeholders (%-format / f-string) in event message FORBIDDEN. |
| LOG_INV_05 | Registered redaction patterns MUST replace secrets with [REDACTED]. |
| LOG_INV_06 | bind() NEVER mutates parent; returns new immutable child. |

## Thread safety

Emission acquires a lock around the internal buffer; safe under concurrent callers.
`bind()` creates a new logger; no shared mutable state between parent and child.

## Operational characteristics

- Per-record cost: serialisation + regex redaction is microseconds.
- Back-pressure: the reference implementation buffers in memory; real
  deployments pair with a `WriteAdapter` that fans out to stderr + shipper.
- SLIs: `logger.records.emitted{level}`, `logger.validation.rejections{reason}`,
  `logger.emit.duration`.

## Security considerations

- Redaction patterns cover bearer tokens, authorization headers, card PANs.
  Custom patterns are registered at construction.
- Binary fields are stringified as `<N-byte-blob>`; no accidental serialisation
  of raw bytes that could include credentials.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Specification 1.32 — Logs Data Model.
- *Observability Engineering* (2022), chapter 3.
- Google SRE Book — Monitoring Distributed Systems, chapter 6.

## Alternatives considered and rejected

- Python stdlib logging with JSON formatter — rejected: encourages positional
  formatting; loses types.
- Per-service print statements + shipper — rejected: regex parsing fragile.
- Binary structured logging (protobuf) — rejected: human debuggability matters.

## Extension contract

A downstream tool plugs in a redaction filter via the register-processor hook,
adds custom severity-to-sink routing by composing a `WriteAdapter`, or injects
static fields through a bound child logger that decorators and middleware
receive as dependency.

## Usage

```python
def handle_webhook(logger: StructuredLogger, event_id: str, payload_size: int) -> None:
    scoped = logger.bind(event_id=event_id, integration="stripe")
    scoped.info("webhook.received", payload_size=payload_size)
    try:
        _process(event_id)
    except ValueError as exc:
        scoped.error("webhook.rejected", reason="invalid_signature", exc=exc)
        raise
    scoped.info("webhook.processed")
```

## Compose with:

- **Queryable logs** → `SemanticAttributes` + `CardinalityGuard`
  Fields are typed and bounded; log aggregation scales without a cardinality-cliff incident.

- **Trace-bound context** → `Tracer` + `CorrelationContext`
  Each record carries trace + correlation ids; a slow span's logs are one join away.

- **Error forensics** → `ErrorSink` + `StructuredLogger`
  Errors are captured with their log trail; reproducing a failure is a matter of filtering the stream, not ssh'ing to a pod.
