# agent session — 16-exactly-once-weak-broker

Plan-level transcript for
`adversarial/01_rare_edge_exactly_once_weak_broker.md`.

## Requirement → kit mapping

1. **100× duplicates → single side effect.**
   → `IdempotentConsumer` keyed by `event_id`; `InboxDeduplicator` stores
     the key in the same tx as the side-effect.
2. **Out-of-order → causal order.**
   → `CausalReorderBuffer` waits for `seq-1` before releasing `seq`.
3. **Stuck predecessor → recorded gap.**
   → Per-slot `gap_timeout_s`; on expiry emit a gap `DeadLetterRoute` entry.
4. **Offset-store corruption does not replay landed effects.**
   → Dedup state lives in the application DB, not the broker's offsets.

## Tool call sequence

```
1. fastapi_generate_project(name="broker_svc")
2. fastapi_add_idempotent_consumer(key_field="event_id")
3. fastapi_add_causal_buffer(gap_timeout_s=5)
4. fastapi_add_dead_letter_route(name="gaps")
```

## Benchmark outcome

Scaffold: 25 · Tests: 25 · Primitive gate: 25 · Hand-edit: 25 — **100**
