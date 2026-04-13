## Tool: `add_event_driven`

### Overview parameters
- Tool name: `fastapi_add_event_driven`
- Category: EVOLVE
- Complexity: Very High
- Dependencies: existing FastAPI project, Redis Streams or Kafka, Pydantic
- Signature: `add_event_driven(project_dir: str, broker: str = "redis_streams", events: list[str] | None = None, schema_registry_path: str = "events/schemas", generate_consumer: bool = True, generate_producer: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root
  - `broker`: `redis_streams`, `kafka`, or `nats`
  - `events`: list of event type names to scaffold (e.g., `OrderCreated`, `UserDeleted`)
  - `schema_registry_path`: directory where Pydantic event schemas live
  - `generate_consumer`: scaffold consumer workers
  - `generate_producer`: scaffold producer helpers

### Purpose
Convert a synchronous request/response flow into an event-driven one. Scaffolds a Pydantic-typed event schema registry, producer helpers (with outbox pattern for transactional guarantees), consumer workers (with retry, DLQ, and idempotency), and observability hooks. Lets the FastAPI monolith decompose its internal workflows into events without adopting Kafka prematurely — Redis Streams is the default for small teams, with Kafka/NATS as upgrade paths. Essential for moving from tight coupling to eventual consistency.

### Performance SLOs
- Tool execution time < 5s (generation)
- Files modified ≤ 4 (main.py, config.py, pyproject.toml, docker-compose.yml)
- Files created ≥ 12 (event base, schemas dir, producer, consumer, retry, DLQ, idempotency, outbox, tests, docs, Makefile, alerts)
- Consumer startup < 1s
- Event publish latency < 5 ms (producer side)
- Event processing latency < 50 ms (idle consumer)

### Key technical decisions
1. **Event base class:** `BaseEvent(BaseModel)` with `event_id`, `event_type`, `occurred_at`, `correlation_id`
2. **Schema registry:** `events/schemas/{event_type}.py` — one file per event
3. **Outbox pattern:** producer writes to outbox table inside the same DB transaction as the business write; background worker publishes to broker
4. **Consumer worker:** separate process with `asyncio.run()` + graceful shutdown
5. **Retry policy:** exponential backoff, 5 attempts default, configurable per event type
6. **Dead-letter queue:** rejected events written to DLQ stream with error metadata
7. **Idempotency:** consumer keeps seen `event_id` in Redis (TTL 7d) to handle duplicate deliveries
8. **Observability:** structured log per event with trace/span ID correlation
9. **Dashboards:** Grafana JSON template for throughput + backlog + DLQ size
10. **Schema evolution:** versioned events (`v1`, `v2`) with migration hooks

### Key invariants
1. Events are ALWAYS Pydantic-validated before publish.
2. Outbox writes are ALWAYS in the same transaction as the business write.
3. Consumers are ALWAYS idempotent — duplicate delivery is safe.
4. Retries ALWAYS use exponential backoff (never fixed interval).
5. DLQ entries ALWAYS include error type, traceback, original event.
6. Event IDs are ALWAYS UUID v7 (time-ordered) for observability.
7. Schema evolution is EXPLICIT (version field mandatory).

### User story themes
- 9.1 Basic pub/sub (US-01..05): event defined, producer publishes, consumer receives, handler runs, log
- 9.2 Outbox (US-06..10): transactional guarantee, atomic, recovery, idempotent
- 9.3 Retry + DLQ (US-11..15): retry on fail, exponential, DLQ after max, manual replay
- 9.4 Idempotency (US-16..20): duplicate handled, TTL expires, per-consumer, per-event
- 9.5 Edge cases (US-21..25): broker down, consumer crash, tool idempotency, schema evolution

### Test plan categories
- 10.1 Pub/sub basics (T-01..06): publish, consume, validate, handle, log, shutdown
- 10.2 Outbox (T-07..12): atomic, recovery, worker, ack
- 10.3 Retry + DLQ (T-13..18): retry, backoff, DLQ, replay, max attempts
- 10.4 Idempotency (T-19..24): dup, TTL, per-consumer, per-event
- 10.5 Edge cases (T-25..30): broker down, tool idempotency, schema v2

### Edge cases (15)
1. Broker unreachable → producer buffers to outbox, eventually catches up
2. Consumer crashes mid-handler → event re-delivered, idempotency protects
3. Duplicate event (broker at-least-once) → skipped via seen cache
4. Event schema v1 → v2 with new field → consumer handles both
5. Event schema v1 → v2 with removed field → explicit migration required
6. DLQ filled → alert fires, operator replays manually
7. Outbox table growing → background cleanup after publish confirmed
8. Consumer lag > 1000 events → warning metric
9. Handler raises on poisoned message → retries then DLQ
10. Tool re-run idempotent
11. Multiple consumers for same stream → consumer group
12. Event older than TTL arrives late → skipped, logged
13. Schema validation fails on consume → DLQ immediately
14. Graceful shutdown on SIGTERM → acks in-flight, flushes outbox
15. Broker latency spike → backlog visible on dashboard

### Anti-patterns
- DO NOT publish events directly (outbox pattern required for consistency)
- DO NOT retry without exponential backoff
- DO NOT skip idempotency (duplicates happen)
- DO NOT forget DLQ (poisoned messages will block the stream)
- DO NOT hardcode broker choice (abstraction layer)
