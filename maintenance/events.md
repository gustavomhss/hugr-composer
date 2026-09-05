# Events Domain — Maintenance Skill

> **Crates**: 13 | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Event-driven architecture primitives — event sourcing, CQRS, saga orchestration, and message delivery guarantees.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `CausalReorderBuffer` | Out-of-order event reordering by causality | High | Production |
| `DeadLetterRoute` | Failed message routing with retry/DLQ | High | Production |
| `DomainEvent` | Base event class with metadata | Low | Production |
| `EventEnvelope` | Event wrapper with metadata/headers | Low | Production |
| `EventSourcedStore` | Event store with snapshotting | High | Production |
| `EventStream` | Append-only event stream | Medium | Production |
| `IdempotentConsumer` | Exactly-once processing guarantee | High | Production |
| `InboxDeduplicator` | Deduplication for at-least-once delivery | High | Production |
| `PubSub` | In-memory pub/sub with persistence option | Medium | Production |
| `SagaOrchestrator` | Long-running transaction orchestration | High | Production |
| `StreamSubject` | Subject-based routing | Medium | Production |
| `TopicBus` | Topic-based pub/sub with persistence | Medium | Production |
| `TransactionalOutbox` | Transactional outbox pattern | High | Production |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    EVENTS DOMAIN                            │
├─────────────────────────────────────────────────────────────┤
│  Commands → Aggregate → Events → EventStore                 │
│       ↓                                                      │
│  TransactionalOutbox → MessageBroker → Consumers            │
│       ↓                                                      │
│  IdempotentConsumer ← Deduplicator ← Broker                 │
│       ↓                                                      │
│  SagaOrchestrator → Compensating Transactions               │
│       ↓                                                      │
│  CausalReorderBuffer → OrderedDelivery                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Event Publishing

```python
# Using TransactionalOutbox
async def create_order(self, order: Order) -> OrderId:
    async with uow:
        order = await self._create_order(order)
        await self.outbox.add(
            event_type="OrderCreated",
            payload=OrderCreated(order_id=order.id, ...),
            correlation_id=order.id,
        )
        await uow.commit()
        return order.id
```

### 2. Idempotent Consumption

```python
async def handle_with_idempotency(
    message: Message,
    handler: Callable,
    store: IdempotencyStore,
) -> Result:
    key = f"{message.topic}:{message.partition}:{message.offset}"
    
    if await store.exists(key):
        return Result.duplicate()
    
    async with lock(message.key):
        if await store.exists(key):
            return Result.duplicate()
        
        try:
            result = await handler(message)
            await store.set(key, Result.success())
            return Result.success()
        except Exception as e:
            await store.set(key, Result.failure(e))
            raise
```

### 3. Saga Orchestration

```python
class OrderSaga(Saga):
    def __init__(self):
        self.steps = [
            SagaStep(
                name="reserve_inventory",
                execute=self._reserve_inventory,
                compensate=self._release_inventory,
            ),
            SagaStep(
                name="charge_payment",
                execute=self._charge_payment,
                compensate=self._refund_payment,
            ),
        ]
    
    async def execute(self, order_id: OrderId) -> SagaResult:
        return await self.run(order_id)
```

---

## Key Patterns

### 1. Transactional Outbox Pattern

```python
# Never publish directly from transaction!
# Instead: write to outbox table in SAME transaction

class OrderService:
    async def create_order(self, order: Order) -> OrderId:
        async with uow:
            order = await self._create_order(order)
            # Write to outbox in SAME transaction
            await self.outbox.add(
                event_type="OrderCreated",
                payload=OrderCreated(order_id=order.id, ...),
                correlation_id=order.id,
            )
            await uow.commit()
            return order.id

# Separate process (or same process, different thread) publishes:
async def publish_outbox():
    while True:
        batch = await outbox.fetch_unpublished(limit=100)
        for entry in batch:
            try:
                await message_bus.publish(entry.event)
                await outbox.mark_published(entry.id)
            except Exception:
                await outbox.increment_retry(entry.id)
                if entry.retry_count > MAX_RETRIES:
                    await dead_letter(entry)
```

---

### 2. Idempotent Consumer

```python
class IdempotentConsumer:
    def __init__(self, store: IdempotencyStore):
        self.store = store
    
    async def process(self, message: Message, handler: Callable) -> Result:
        # 1. Generate idempotency key
        key = f"{message.topic}:{message.partition}:{message.offset}"
        
        # 2. Check if already processed
        if await self.store.exists(key):
            return Result.duplicate()
        
        # 2. Process with lock
        async with self._lock(message.key):
            # Double-check after acquiring lock
            if await self.store.exists(key):
                return Result.duplicate()
            
            try:
                result = await handler(message)
                await self.store.set(key, Result.success())
                return Result.success()
            except Exception as e:
                await self.store.set(key, Result.failure(e))
                raise
```

---

### 3. Saga Orchestrator

```python
# For long-running distributed transactions
class OrderSaga(Saga):
    def __init__(self):
        self.steps = [
            SagaStep(
                name="reserve_inventory",
                execute=self._reserve_inventory,
                compensate=self._release_inventory,
            ),
            SagaStep(
                name="charge_payment",
                execute=self._charge_payment,
                compensate=self._refund_payment,
            ),
            SagaStep(
                name="create_shipment",
                execute=self._create_shipment,
                compensate=self._cancel_shipment,
            ),
        ]
    
    async def execute(self, order_id: OrderId) -> SagaResult:
        return await self.run(order_id)
```

---

## Common Patterns

### 1. Event Envelope

```python
@dataclass
class EventEnvelope:
    event_id: str           # UUID
    event_type: str         # "OrderCreated"
    timestamp: datetime     # UTC
    correlation_id: str     # Trace ID
    causation_id: str       # Causation ID
    payload: dict           # Event payload
    metadata: dict          # Headers, tracing, etc.
```

### 2. Idempotent Consumer

```python
async def handle_with_idempotency(
    message: Message,
    handler: Callable,
    store: IdempotencyStore,
) -> Result:
    key = f"{message.topic}:{message.partition}:{message.offset}"
    
    if await store.exists(key):
        return Result.duplicate()
    
    async with lock(message.key):
        if await store.exists(key):
            return Result.duplicate()
        
        try:
            result = await handler(message)
            await store.set(key, Result.success())
            return Result.success()
        except Exception as e:
            await store.set(key, Result.failure(e))
            raise
```

### 3. Transactional Outbox

```python
# In your service:
async def create_order(self, order: Order) -> OrderId:
    async with uow:
        order = await self._create(order)
        await self.outbox.add(
            event_type="OrderCreated",
            payload={"order_id": order.id, ...},
            correlation_id=order.id,
        )
        await uow.commit()
        return order.id

# Separate publisher process:
async def publish_outbox():
    while True:
        batch = await outbox.fetch_unpublished(limit=100)
        for entry in batch:
            try:
                await message_bus.publish(entry.event)
                await outbox.mark_published(entry.id)
            except Exception:
                await outbox.increment_retry(entry.id)
                if entry.retry_count > MAX_RETRIES:
                    await dead_letter(entry)
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Duplicate processing** | Duplicate orders/charges | IdempotentConsumer with deduplication |
| **Message loss** | Events lost on crash | TransactionalOutbox + persistent broker |
| **Duplicate processing** | Double charges | IdempotentConsumer with deduplication |
| **Out-of-order delivery** | State corruption | CausalReorderBuffer |
| **Message loss on crash** | Events lost | TransactionalOutbox + persistent broker |
| **Poison messages** | Consumer crashes repeatedly | DeadLetterRoute with retry limit |
| **Saga stuck** | Saga stuck in intermediate state | Timeout + compensation triggers |
| **Event ordering** | State corruption | CausalReorderBuffer |
| **Duplicate webhook processing** | Double charges | Idempotency keys on webhooks |

---

## Evolution Without Breaking Contracts

### Adding a New Event Field

```python
# Non-breaking: add optional field
@dataclass
class OrderCreated(Event):
    order_id: OrderId
    customer_id: CustomerId
    # New optional field
    source: str | None = None  # NEW
```

### Adding a New Event Type

```python
# 1. Define new event
@dataclass
class OrderShipped(Event):
    order_id: OrderId
    tracking_number: str
    carrier: str

# 2. Handle in consumers (non-breaking)
async def handle(event: Event):
    if isinstance(event, OrderShipped):
        await handle_shipped(event)
    elif isinstance(event, OrderCreated):
        await handle_created(event)
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing event schema | **STOP** — Schema evolution review |
| Changing message ordering | **STOP** — Affects consistency |
| Changing delivery guarantees | **REVIEW** — Affects contracts |
| Changing retry policy | **REVIEW** — Affects reliability |
| Adding new event type | **REVIEW** — Consumer impact |

---

## Health Checks & Monitoring

```python
@app.get("/health/events")
async def events_health():
    return {
        "status": "healthy",
        "checks": {
            "outbox_lag": await check_outbox_lag(),
            "consumer_lag": await check_consumer_lag(),
            "dlq_size": await check_dlq_size(),
            "saga_stuck": await check_stuck_sagas(),
        }
    }

# Metrics:
# - events.published.rate
# - events.consumed.latency.p99
# - events.dlq.size
# - saga.active.count
# - saga.stuck.count
```

---

## Debugging Quick Reference

```bash
# Check outbox lag
sql "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL"

# Check consumer lag
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group my-group --describe

# Check DLQ
sql "SELECT * FROM dead_letter_queue ORDER BY created_at DESC LIMIT 10"

# Replay failed message
python -m app.replay --event-id <event-id>

# Check saga status
sql "SELECT * FROM saga_log WHERE status = 'running' ORDER BY created_at"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Consumer prefetch | `prefetch_count` | 100-500 |
| Batch size | `batch_size` | 100-500 |
| Poll interval | `poll_interval_ms` | 100-500ms |
| Retry backoff | Exponential | 1s, 2s, 4s, 8s, 30s, 60s |
| Max retries | `max_retries` | 5-10 |

---

## Security Checklist

- [ ] All messages signed/verified
- [ ] Encryption at rest for sensitive payloads
- [ ] Encryption in transit (TLS)
- [ ] Message authentication (HMAC/signature)
- [ ] No sensitive data in headers
- [ ] Access control on topics
- [ ] Audit logging for all events
- [ ] PII not in event payloads (or encrypted)

---

*Events Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*