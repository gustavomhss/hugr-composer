## Tool: `add_outbox_pattern`

### Overview parameters
- Tool name: `fastapi_add_outbox_pattern`
- Category: EXTEND > Infrastructure
- Complexity: High
- Dependencies: existing FastAPI project with SQLAlchemy, Alembic, ARQ (dispatcher worker)
- Signature: `add_outbox_pattern(project_dir: str, dispatcher_poll_seconds: float = 1.0, batch_size: int = 100, max_retries: int = 5, dispatch_targets: list[Literal["webhook","sse","kafka"]] = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `dispatcher_poll_seconds`: how often the background worker polls the outbox table
  - `batch_size`: max events dispatched per poll cycle
  - `max_retries`: retry attempts per failed event
  - `dispatch_targets`: which downstream targets to dispatch to (webhook, SSE, kafka)

### Purpose
Implement the transactional outbox pattern to guarantee at-least-once delivery of domain events. When business logic commits a DB transaction, it also writes an event row to the `outbox` table in the SAME transaction. A background dispatcher worker polls the outbox, dispatches each event to configured targets (webhook sender, SSE publisher, Kafka), and marks them as delivered. If dispatch fails, retries with exponential backoff until max_retries. This guarantees that business state changes and event emissions are atomic — either both happen or neither. Avoids the dual-write problem (DB commit succeeds but event bus call fails). The tool generates the `OutboxEvent` model, migration, dispatcher worker, helper `emit_event()` function, and integration hooks for existing CRUD.

### Performance SLOs
- Tool execution time < 5s
- Files modified ≤ 6
- Files created ≥ 9 (model, migration, dispatcher worker, emit helper, status tracker, admin routes, config, tests, startup hook)
- `emit_event()` overhead < 1 ms (single INSERT into outbox)
- Dispatcher poll cycle < 500 ms for batch_size=100
- Dispatcher dispatch latency p99 < 200 ms (per event, to target)
- Outbox table indexes: `(dispatched_at IS NULL, created_at)` for fast polling
- Retention: delivered events pruned after 7 days (configurable)

### Key technical decisions
1. **Outbox table:** `outbox_events` with columns `id, event_type, payload (JSONB), aggregate_id, aggregate_type, dispatched_at, attempts, last_error, created_at`.
2. **Transactional write:** `emit_event()` takes the current session and inserts into outbox. The event is committed atomically with the business change.
3. **Dispatcher worker:** separate ARQ worker that polls `SELECT * FROM outbox_events WHERE dispatched_at IS NULL ORDER BY created_at LIMIT batch_size FOR UPDATE SKIP LOCKED` — safe for multiple worker instances.
4. **Dispatch logic:** per event, call each configured target. Success → set `dispatched_at=now()`. Failure → increment attempts, set last_error, retry with backoff.
5. **Backoff:** 1s → 5s → 30s → 5min → 30min. After max_retries, event marked `dead` (permanent failure).
6. **Idempotency:** each event has a unique `event_id` (UUID) sent to targets so consumers can dedupe.
7. **Integration with webhook_sender:** dispatcher calls `send_webhook(event_type, payload)` if webhook target is configured.
8. **Integration with SSE:** dispatcher calls `publish_event(channel, event_type, payload)` if SSE target configured.
9. **Retention:** nightly cleanup job deletes `dispatched_at < now() - 7 days`.
10. **Admin endpoints:** `GET /outbox/stats` (count by status), `POST /outbox/{id}/retry` (force retry), `POST /outbox/{id}/dead` (mark dead).

### Key invariants
1. An event row is INSERTED in the SAME transaction as the business change — NEVER written separately.
2. A dispatched event NEVER dispatches twice (unless admin force-retries).
3. `SELECT ... FOR UPDATE SKIP LOCKED` prevents duplicate dispatch across multiple workers.
4. Failed events ALWAYS retry with exponential backoff until max_retries.
5. Dead events NEVER auto-retry (require admin intervention).
6. Event payloads are JSON-serializable and bounded (< 64 KB per event).
7. Dispatcher NEVER blocks the API request that called emit_event().
8. Outbox reads NEVER contend with business writes (separate connection pool).

### User story themes
- 9.1 Emit + dispatch (US-01..05): business code emits, dispatcher picks up, target receives, event marked delivered
- 9.2 Atomicity (US-06..10): DB rollback rolls back event, dual-write problem avoided, session-aware emit
- 9.3 Retry & failure (US-11..15): target fails, retry with backoff, max retries, mark dead
- 9.4 Admin & retention (US-16..20): stats endpoint, force retry, cleanup, dead letter queue
- 9.5 Integration & concurrency (US-21..25): webhook_sender, SSE, multi-worker SKIP LOCKED, tool idempotency

### Test plan categories
- 10.1 Emit atomicity (T-01..06): commit includes event, rollback excludes event, session binding
- 10.2 Dispatcher (T-07..12): single event, batch, SKIP LOCKED concurrency, idempotency
- 10.3 Retry (T-13..18): fail→retry→succeed, max retries→dead, backoff schedule
- 10.4 Admin (T-19..24): stats, force retry, dead mark, cleanup
- 10.5 Integration (T-25..30): webhook, SSE, multi-worker, tool idempotency

### Edge cases (15)
1. `emit_event()` called outside a transaction → tool errors (requires explicit session)
2. Payload larger than 64 KB → raises ValueError before INSERT
3. Payload not JSON-serializable → raises TypeError
4. Dispatcher worker down → events accumulate; API not affected
5. All targets fail for an event → retry with backoff, eventually dead
6. One target succeeds, another fails → event retried, first target called again (consumer dedupe required)
7. Multiple dispatcher instances → SKIP LOCKED ensures no duplicate dispatch
8. Outbox table grows > 1M rows → query uses index, still fast
9. Retention cleanup runs while dispatcher is working → uses separate WHERE clause, no conflict
10. emit_event() called with a closed session → raises InvalidRequestError
11. Event ordering matters → dispatcher uses `ORDER BY created_at` but parallelism breaks strict order
12. Target timeout > poll interval → event remains in "dispatching" state, reprocessed after heartbeat expires
13. Dispatcher process crashes mid-dispatch → event row unchanged; next poll picks it up
14. Network partition between API and DB during emit → transaction rolls back; event not written
15. Tool re-run idempotent

### Anti-patterns
- DO NOT call emit_event() in a background task (must be in the same transaction as the business change)
- DO NOT poll the outbox without SKIP LOCKED (causes duplicate dispatch)
- DO NOT return 200 to the client before committing the outbox write
- DO NOT store sensitive data in payload without encryption
- DO NOT retry indefinitely (max_retries bounds failure blast)
- DO NOT let the outbox table grow unbounded (retention cleanup required)
