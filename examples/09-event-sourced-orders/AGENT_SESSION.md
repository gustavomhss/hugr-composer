# agent session — 09-event-sourced-orders

Plan-level transcript for `mid/03_event_sourced_orders.md`.

## Requirement → kit mapping

1. **Order state derived by pure fold.**
   → `EventSourcedStore.fold(events)` is a pure function of the log.
2. **Crashed consumer sees redelivery.**
   → `IdempotentConsumer` keyed on `event_id`; unacked events replayed.
3. **No lost events on publisher crash.**
   → `TransactionalOutbox`: append + enqueue in one tx; a relay drains.
4. **Replay from offset 0 = live state.**
   → The fold is deterministic; no out-of-band writes.
5. **Failed handlers → recovery queue.**
   → `DeadLetterRoute` named "order-recovery".

## Tool call sequence

```
1. fastapi_generate_project(name="orders_svc")
2. fastapi_add_event_sourcing(aggregate="order")
3. fastapi_add_transactional_outbox(topic="order.events")
4. fastapi_add_dead_letter_queue(route="order-recovery")
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
