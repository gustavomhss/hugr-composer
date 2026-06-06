# Example 09 — Event-sourced order service

**Tier:** mid · **Benchmark spec:** `mid/03_event_sourced_orders.md`

Order lifecycle as an append-only event log with pure-fold state derivation.
Demonstrates the **`EventSourcedStore` + `TransactionalOutbox` +
`IdempotentConsumer`** recipe.

## What this example shows

- Folding the event log twice produces the exact same state (pure fold).
- Consumers that crash mid-handler see the event redelivered on restart.
- A publisher that crashes between append + publish still delivers —
  the outbox relay catches up.
- Replay from offset 0 reconstructs the same state as was computed live.

## How to run

```bash
cd examples/09-event-sourced-orders
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Tools used

| Tool                                 | Role                                            |
| ------------------------------------ | ----------------------------------------------- |
| `fastapi_add_event_sourcing`         | Append-only log + fold projection.              |
| `fastapi_add_transactional_outbox`   | Write + publish in one transaction.             |
| `fastapi_add_dead_letter_queue`      | Recovery lane for failed handlers.              |

## Primitives imported

| Primitive              | Role                                                  |
| ---------------------- | ----------------------------------------------------- |
| `EventSourcedStore`    | Append-only, ordered per-aggregate event log.         |
| `EventStream`          | Replayable log; any consumer picks an offset.         |
| `TransactionalOutbox`  | Atomic write-and-enqueue (no lost events).           |
| `IdempotentConsumer`   | Crash-safe handlers (redelivery-safe).                |
| `DeadLetterRoute`      | Failed handler lands in a recovery queue.             |

Reference pages at `docs.hugr.dev/primitive/<Name>`.
