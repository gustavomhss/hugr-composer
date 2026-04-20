# Example 02 — Inbound webhook sink

**Tier:** baseline · **Benchmark spec:** `baseline/03_webhook_sink.md`

HMAC-signed webhook receiver with exactly-once processing. Demonstrates the
canonical **`SignatureVerifier` + `IdempotentConsumer`** recipe.

## What this example shows

- Signature + timestamp rejection **before** body parsing (reject fast).
- Deduplication by `event_id` across 10 parallel duplicate deliveries —
  exactly one succeeds, nine are short-circuited.
- Raw body is persisted alongside the `signature_verified` flag for audit.

## How to run

```bash
cd examples/02-webhook-sink
python3.12 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                             | Role                                              |
| -------------------------------- | ------------------------------------------------- |
| `fastapi_add_webhook_receiver`   | Emits route + signature check wiring.             |
| `fastapi_add_idempotency`        | Attaches `IdempotentConsumer` to the handler.     |
| `fastapi_add_audit_log`          | Persists every accepted delivery.                 |

## Primitives imported

| Primitive              | Role                                                         |
| ---------------------- | ------------------------------------------------------------ |
| `SignatureVerifier`    | HMAC check + ±5 min timestamp window.                        |
| `IdempotentConsumer`   | Dedupes on `event_id`; one side-effect per key.              |
| `InboxDeduplicator`    | Durable store of processed event ids.                        |
| `AuditEvent`           | Structured record of each accepted delivery.                 |
| `Redactor`             | Strips secrets from the raw body before logging.             |

Reference pages live at `docs.hugr.dev/primitive/<Name>`.
