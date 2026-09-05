# Jobs Domain — Maintenance Skill

> **Crates**: 3 | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Background job processing, durable timers, and workflow execution.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `ActivityCall` | Durable activity invocation with retries | Medium | Production |
| `DurableTimer` | Persistent timers with crash recovery | High | Production |
| `WorkflowRun` | Durable workflow execution | High | Production |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       JOBS DOMAIN                           │
├─────────────────────────────────────────────────────────────┤
│  WorkflowRun → ActivityCall → DurableTimer                  │
│       ↓                                                         │
│  Persistent State Store (PostgreSQL)                         │
│       ↓                                                      │
│  Recovery on Restart                                         │
└─────────────────────────────────────────────────────────────┘
```

```
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Activity Invocation

```python
result = await activity.execute(
    "charge_payment",
    {"amount": 100.00, "currency": "USD"},
    timeout=60,
    heartbeat=30,
    retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0),
)
```

### 2. Timer Scheduling

```python
timer_id = await timer.schedule(
    name="send_reminder",
    fire_at=datetime.now() + timedelta(hours=24),
    payload={"user_id": "user_123", "type": "reminder"},
    callback_url="https://api.example.com/webhooks/timer",
)
```

### 3. Workflow Execution

```python
run_id = await workflow_run.start(
    "order_fulfillment",
    {"order_id": "123", "items": [...]},
    version="1.0",
)
```

### 4. Workflow Monitoring

```python
status = await workflow_run.get_status(run_id)
# Returns: status, current_step, progress, error_info
```

### 5. Workflow Compensation

```python
# Automatic on failure, or manual:
await workflow_run.cancel(run_id)
```

---

## Crate Details

### 1. `ActivityCall`

**Purpose**: Durable activity invocation with automatic retries, timeouts, and heartbeats.

**Key Features**:
- Automatic retries with exponential backoff
- Heartbeat support for long-running activities
- Timeout enforcement
- Activity versioning for schema evolution
- Cancellation support

**Interface**:
```python
class ActivityCall(Protocol):
    async def execute(
        self,
        activity_name: str,
        input_data: dict,
        timeout: int = 300,
        heartbeat_interval: int = 30,
        retry_policy: RetryPolicy | None = None,
    ) -> Any
```

---

### 2. `DurableTimer`

**Purpose**: Persistent timers that survive process restarts, with exact-once firing guarantees.

**Key Features**:
- Persistent storage (PostgreSQL)
- Exact-once firing guarantee
- Cancel/reschedule support
- Timezone-aware scheduling
- Catch-up on restart (missed timers fire immediately)

**Interface**:
```python
class DurableTimer(Protocol):
    async def schedule(
        self,
        name: str,
        fire_at: datetime,
        payload: dict,
        callback_url: str | None = None,
    ) -> TimerId
    
    async def cancel(self, timer_id: TimerId) -> bool
    async def reschedule(self, timer_id: TimerId, fire_at: datetime) -> bool
    async def get(self, timer_id: TimerId) -> TimerInfo | None
```

---

### 3. `WorkflowRun`

**Purpose**: Durable workflow execution with state persistence, checkpointing, and replay.

**Key Features**:
- State persistence at each step
- Automatic checkpointing
- Deterministic replay on failure
- Human-in-the-loop support
- Versioned workflow definitions
- Compensation/rollback support

**Interface**:
```python
class WorkflowRun(Protocol):
    async def start(
        self,
        workflow_name: str,
        input_data: dict,
        version: str = "1.0",
    ) -> WorkflowRunId
    
    async def signal(self, run_id: WorkflowRunId, signal_name: str, payload: dict) -> None
    async def cancel(self, run_id: WorkflowRunId) -> None
    async def get_status(self, run_id: WorkflowRunId) -> WorkflowStatus
```

---

## Common Patterns

### 1. Durable Activity with Retries

```python
# Activity definition
@activity(name="charge_payment", timeout=60, heartbeat=30)
async def charge_payment(payment_data: dict) -> PaymentResult:
    # This runs in a separate worker process
    # Automatic retries with exponential backoff
    # Heartbeat every 30s to prevent timeout
    result = await payment_gateway.charge(
        amount=payment_data["amount"],
        currency=payment_data["currency"],
        payment_method=payment_data["payment_method_id"],
    )
    return PaymentResult(success=True, transaction_id=result.id)

# Called from workflow:
result = await workflow.execute_activity(
    "charge_payment",
    payment_data,
    timeout=60,
    heartbeat=30,
)
```

### 2. Durable Timer for Scheduling

```python
# Schedule a future action
timer_id = await durable_timer.schedule(
    name="send_reminder",
    fire_at=datetime.now() + timedelta(hours=24),
    payload={"user_id": user_id, "type": "appointment_reminder"},
    callback_url="https://api.example.com/webhooks/timer",
)

# Timer fires exactly once, even if process crashes
# On restart, missed timers fire immediately
```

### 3. Workflow Definition

```python
@workflow(name="order_fulfillment", version="1.0")
class OrderFulfillmentWorkflow:
    @step
    async def reserve_inventory(self, order_id: str) -> ReservationResult:
        return await self.call_activity("reserve_inventory", {"order_id": self.input["order_id"]})
    
    @step
    async def charge_payment(self, reservation: ReservationResult) -> PaymentResult:
        return await self.call_activity("charge_payment", {"reservation_id": reservation.id})
    
    @step
    async def create_shipment(self, payment: PaymentResult) -> Shipment:
        return await self.call_activity("create_shipment", {"payment_id": payment.id})
    
    @compensate
    async def compensate(self, step: str, error: Exception):
        if step == "charge_payment":
            await self.call_activity("refund_payment", {"payment_id": ...})
        elif step == "reserve_inventory":
            await self.call_activity("release_inventory", {"reservation_id": ...})

# Execute
run_id = await workflow_run.start("order_fulfillment", {"order_id": "123"})
```

---

## Common Patterns

### 1. Retry Policies

```python
from dataclasses import dataclass

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0      # seconds
    max_delay: float = 60.0      # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)

# Usage in ActivityCall
await activity.execute(
    "risky_operation",
    input_data,
    retry_policy=RetryPolicy(
        max_attempts=5,
        base_delay=2.0,
        max_delay=120.0,
        retryable_exceptions=(TransientError, TimeoutError),
    ),
)
```

### 2. Durable Timer with Idempotency

```python
# Schedule idempotent timer
timer_id = await timer.schedule(
    name="send_invoice",
    fire_at=invoice_due_date,
    payload={
        "invoice_id": invoice_id,
        "idempotency_key": f"invoice_{invoice_id}_send",
    },
    callback_url=f"{BASE_URL}/webhooks/timer",
)

# Callback handler (idempotent):
@app.post("/webhooks/timer")
async def handle_timer(payload: TimerPayload):
    # Check idempotency key
    if await idempotency_store.exists(payload.idempotency_key):
        return {"status": "already_processed"}
    
    async with idempotency_lock(payload.idempotency_key):
        if await idempotency_store.exists(payload.idempotency_key):
            return {"status": "duplicate"}
        
        await send_invoice(payload.invoice_id)
        await idempotency_store.set(payload.idempotency_key, "done")
        return {"status": "sent"}
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Activity timeout** | Activity killed mid-execution | Set appropriate timeout; use heartbeats |
| **Timer drift** | Timers fire late | Use `DurableTimer` (not `asyncio.sleep`) |
| **Workflow non-determinism** | Replay produces different results | No random, no `datetime.now()`, no external calls in workflow body |
| **Timer drift** | Timers fire late/early | Use `DurableTimer` with persistent storage |
| **Workflow non-determinism** | Replay fails | No random, no `datetime.now()`, no I/O in workflow body |
| **Timer not firing** | Missed timers after restart | `DurableTimer` catches up on restart |
| **Activity timeout** | Work stuck | Set appropriate timeouts; use heartbeats |
| **Race conditions** | Race conditions in timer scheduling | Use database constraints for timer uniqueness |

---

## Evolution Without Breaking Contracts

### Adding a New Workflow Step

```python
# Non-breaking: add new step at end
class OrderWorkflow:
    @step
    async def new_step(self, ...) -> NewResult:
        ...

# For compensation, add new compensate method
@compensate
async def compensate_new_step(self, error: Exception):
    ...
```

### Changing Activity Interface

```python
# Non-breaking: add optional field
@dataclass
class PaymentInput:
    amount: Decimal
    currency: str
    metadata: dict = field(default_factory=dict)  # NEW
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Non-deterministic workflow** | Replay fails | No `random`, `datetime.now()`, I/O in workflow body |
| **Activity timeout too short** | Activities killed prematurely | Set realistic timeouts; use heartbeats |
| **Timer not firing** | Missed deadlines | Use `DurableTimer` (not `asyncio.sleep`) |
| **Workflow replay fails** | Non-deterministic logic | No `random`, `datetime.now()`, I/O in workflow body |
| **Activity heartbeat missing** | Activity killed prematurely | Call `activity.heartbeat()` periodically |
| **Timer not firing after restart** | Missed timers | Use `DurableTimer` (persistent) |
| **Race condition in timer scheduling** | Duplicate timers | DB unique constraint on timer name + fire_at |

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing workflow logic | **REVIEW** — Affects all in-flight workflows |
| Changing activity signature | **REVIEW** — Affects all callers |
| Changing retry policy | **REVIEW** — Affects reliability |
| Adding new workflow | **REVIEW** — New failure modes |
| Changing timer behavior | **REVIEW** — Affects scheduling |

---

## Health Checks & Monitoring

```python
@app.get("/health/jobs")
async def jobs_health():
    return {
        "status": "healthy",
        "checks": {
            "activity_workers": await check_activity_workers(),
            "timer_scheduler": await check_timer_scheduler(),
            "workflow_executor": await check_workflow_executor(),
            "pending_activities": await count_pending_activities(),
            "pending_timers": await count_pending_timers(),
        }
    }

# Metrics:
# - jobs.activity.duration.p99
# - jobs.timer.accuracy_ms
# - jobs.workflow.duration.p99
# - jobs.failed.rate
# - jobs.heartbeat.missed
```

---

## Debugging Quick Reference

```bash
# List running workflows
python -m app.jobs list-workflows --status running

# Inspect workflow state
python -m app.jobs inspect <workflow_run_id>

# Replay workflow from checkpoint
python -m app.jobs replay <run_id> --from-step=3

# Inspect timer
python -m app.jobs inspect-timer <timer_id>

# Trigger timer manually
python -m app.jobs trigger-timer <timer_id>

# View activity history
python -m app.jobs activity-history <activity_name> --limit 100
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Activity workers | `max_concurrent` | 10-50 per worker |
| Timer precision | `tick_interval` | 1s (default) |
| Workflow checkpoint | `checkpoint_interval` | Every step |
| History retention | `retention_days` | 30-90 days |
| Event history | `max_history_size` | 1000 events |

---

## Security Checklist

- [ ] Workflow inputs validated
- [ ] Activity inputs validated
- [ ] No sensitive data in workflow history
- [ ] Activity timeouts enforced
- [ ] Workflow cancellation respected
- [ ] Signal handling validated
- [ ] No sensitive data in workflow history
- [ ] Compensation actions tested
- [ ] Timeout enforcement verified

---

*Jobs Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*