# Example 16 — Exactly-once on a weak broker

**Tier:** adversarial · **Benchmark spec:**
`adversarial/01_rare_edge_exactly_once_weak_broker.md`

The broker guarantees at-least-once and may reorder. The app delivers
exactly-once, in causal order per aggregate. Demonstrates the
**`CausalReorderBuffer` + `IdempotentConsumer` + `DeadLetterRoute`** recipe
(the Phase-3 primitives built to close this spec).

## What this example shows

- 100× duplicate deliveries → downstream side effect runs once.
- Out-of-order events are buffered and handed over in causal order.
- A stuck predecessor times out and triggers a recorded gap.
- After offset-store corruption, replay does not re-trigger landed side effects.

## How to run

```bash
cd examples/16-exactly-once-weak-broker
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_idempotent_consumer`    | At-most-once per logical event key.             |
| `fastapi_add_causal_buffer`          | Per-aggregate reorder buffer with timeout.      |
| `fastapi_add_dead_letter_route`      | Gap events + failed-handler recovery.           |

## Primitives imported

| Primitive                | Role                                               |
| ------------------------ | -------------------------------------------------- |
| `CausalReorderBuffer`    | Per-(aggregate, seq) buffer; timed gap emit.       |
| `IdempotentConsumer`     | Dedup by `event_id`; replay-safe.                  |
| `InboxDeduplicator`      | DB-level dedup keyed by `event_id`.                |
| `DeadLetterRoute`        | Gap records + failed-handler recovery lane.        |
| `SignatureVerifier`      | Auth check on inbound broker messages.             |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
