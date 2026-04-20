# Redactor

**Namespace:** `resiliency`
**Maturity:** `emerging`
**Source tool:** `adapt/extend/infrastructure/add_dlp_shield.py`

## Purpose

`Redactor` is a structlog-compatible processor callable: it receives
`(logger, method, event_dict)` and returns an `event_dict` with every
string value rewritten to mask PII patterns (emails, card numbers,
tokens). It is on the hot path of every log emission and therefore MUST
be cheap and exception-safe.

## Invariants

- **REDACTOR_INV_01** — In-place contract: the returned dict is the SAME
  object that was passed in, with string values mutated in-place — no
  copy is made.
- **REDACTOR_INV_02** — Non-string pass-through: values that aren't `str`
  (ints, lists, bytes, nested dicts) are returned unchanged.
- **REDACTOR_INV_03** — Exception-safe: the call NEVER raises, no matter
  how malformed the event_dict is; a logging processor that throws would
  break the whole pipeline.

Tests: see `test_Redactor.py`.

## Compose with:

- **Log-path PII hygiene** → `StructuredLogger` + `PiiClassification`
  Structlog processor consumes classification tags; every emitted record is masked before any sink sees it — PII cannot escape via the log stream.

- **Audit-compatible masking** → `AuditEvent` + `AccessLog`
  Audit and access records share the same redactor; the tamper-evident chain records masked values, never raw PII.

- **Error-path safety** → `ErrorSink` + `StructuredLogger`
  Exception captures route through the redactor; stack traces containing request bodies are sanitized before Sentry or the local sink.
