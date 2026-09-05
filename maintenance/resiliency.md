# Resiliency Domain — Maintenance Skill

> **Crates**: 18 | **Status**: Production-ready | **Owner**: Platform Team | **Last Updated**: 2026-09-04

> **Purpose**: Resilience patterns — circuit breaker, retry, timeout, bulkhead, rate limiting, and graceful degradation.

---

## Crate Inventory

| Crate | Purpose | Complexity | Maturity |
|-------|---------|------------|----------|
| `Bulkhead` | Resource isolation and concurrency limiting | High | Production |
| `CircuitBreaker` | Failure detection and fast-fail | High | Production |
| `CostTracker` | Cost tracking and budgeting | Medium | Production |
| `ExcelExporter` | Excel report generation | Low | Production |
| `GracefulShutdown` | Graceful shutdown with drain | Medium | Production |
| `HeterogeneousWorkerPool` | Heterogeneous worker pool management | High | Production |
| `LoadShedder` | Load shedding under pressure | High | Production |
| `ModelRegistry` | ML model registry | Medium | Production |
| `RateLimiter` | Rate limiting with multiple algorithms | High | Production |
| `Redactor` | PII redaction | Medium | Production |
| `RetryBudget` | Retry budget management | High | Production |
| `RetryPolicy` | Configurable retry policies | Medium | Production |
| `TimeoutBudget` | Timeout budget management | High | Production |
| `TracingBuffer` | Trace buffering for debugging | Medium | Production |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      RESILIENCY LAYER                       │
├─────────────────────────────────────────────────────────────┤
│  Request → RateLimiter → CircuitBreaker → TimeoutBudget    │
│       ↓                                                      │
│  Bulkhead → RetryPolicy → RetryBudget → Your Service       │
│       ↓                                                      │
│  LoadShedder → GracefulShutdown → CostTracker              │
└─────────────────────────────────────────────────────────────┘
```

---

## Common Operations

### 1. Circuit Breaker Usage

```python
from generators.resiliency.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

config = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=30,
    excluded_exceptions=(ValidationError,),
)

breaker = CircuitBreaker(config)

async def call_external_service(data: dict) -> Result:
    async with breaker:
        return await external_api.call(data)
```

### 2. Retry with Budget

```python
from generators.resiliency.retry_budget import RetryBudget, RetryPolicy

budget = RetryBudget(
    max_retries=3,
    budget_ratio=0.1,
    window=timedelta(minutes=1),
)

policy = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=(TimeoutError, ConnectionError),
)

async def call_with_retry(operation: Callable) -> Result:
    async with budget:
        return await retry_with_policy(operation, policy)
```

### 3. Timeout Budget

```python
from generators.resiliency.timeout_budget import TimeoutBudget

budget = TimeoutBudget(
    total_timeout=30.0,
    per_attempt_timeout=10.0,
)

async def call_with_timeout(operation: Callable) -> Result:
    async with budget:
        return await asyncio.wait_for(operation(), timeout=budget.remaining)
```

### 4. Bulkhead

```python
from generators.resiliency.bulkhead import Bulkhead

bulkhead = Bulkhead(
    max_concurrent=100,
    max_queue=50,
    timeout=30.0,
)

async def call_with_bulkhead(operation: Callable) -> Result:
    async with bulkhead:
        return await operation()
```

### 5. Rate Limiter

```python
from generators.resiliency.rate_limiter import RateLimiter, RateLimitConfig

limiter = RateLimiter(
    config=RateLimitConfig(
        algorithm="token_bucket",
        rate=1000,
        window=timedelta(seconds=60),
        burst=200,
    )
)

async def rate_limited_operation(key: str, operation: Callable) -> Result:
    allowed = await limiter.acquire(key, amount=1)
    if not allowed:
        raise RateLimitExceeded("Rate limit exceeded")
    return await operation()
```

### 6. Load Shedding

```python
from generators.resiliency.load_shedder import LoadShedder, SheddingPolicy

shedder = LoadShedder(
    policy=SheddingPolicy(
        max_concurrent=1000,
        queue_size=10000,
        shed_strategy="priority",
        priority_key=lambda req: req.priority,
    )
)

async def handle_request(request: Request) -> Response:
    if not await shedder.try_acquire(request):
        raise HTTPException(503, "Service overloaded")
    return await handle_request(request)
```

### 7. Graceful Shutdown

```python
from generators.resiliency.graceful_shutdown import GracefulShutdown

shutdown = GracefulShutdown(
    drain_timeout=30.0,
    force_timeout=60.0,
    health_check_interval=5.0,
)

@app.on_event("shutdown")
async def shutdown():
    await shutdown.graceful_shutdown()
```

---

## Key Patterns

### 1. Circuit Breaker

```python
from generators.resiliency.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

config = CircuitBreakerConfig(
    failure_threshold=5,        # Open after 5 failures
    success_threshold=2,        # Close after 2 successes
    timeout=30,                 # Try again after 30s
    excluded_exceptions=(ValidationError,),  # Don't count these
)

breaker = CircuitBreaker(config)

async def call_external_service(data: dict) -> Result:
    async with breaker:
        return await external_api.call(data)
```

**States**: `CLOSED` (normal) → `OPEN` (failing fast) → `HALF_OPEN` (testing recovery)

---

### 2. Retry with Budget

```python
from generators.resiliency.retry_budget import RetryBudget, RetryPolicy

budget = RetryBudget(
    max_retries=3,
    budget_ratio=0.1,  # Max 10% of requests can be retries
    window=timedelta(minutes=1),
)

policy = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=(TimeoutError, ConnectionError),
)

async def call_with_retry(operation: Callable) -> Any:
    async with budget:
        return await retry_with_policy(operation, policy)
```

---

### 3. Timeout Budget

```python
from generators.resiliency.timeout_budget import TimeoutBudget

budget = TimeoutBudget(
    total_timeout=30.0,       # Total budget for operation
    per_attempt_timeout=10.0, # Per-attempt timeout
)

async def call_with_timeout(operation: Callable) -> Result:
    async with budget:
        return await asyncio.wait_for(operation(), timeout=budget.remaining)
```

---

### 4. Bulkhead

```python
from generators.resiliency.bulkhead import Bulkhead

bulkhead = Bulkhead(
    max_concurrent=100,       # Max concurrent requests
    max_queue=50,             # Max queued requests
    timeout=30.0,             # Queue timeout
)

async def call_with_bulkhead(operation: Callable) -> Result:
    async with bulkhead:
        return await operation()
```

---

### 5. Rate Limiter

```python
from generators.resiliency.rate_limiter import RateLimiter, RateLimitConfig

limiter = RateLimiter(
    config=RateLimitConfig(
        algorithm="token_bucket",  # or "sliding_window", "fixed_window"
        rate=1000,                 # requests per window
        window=timedelta(seconds=60),
        burst=200,                 # burst allowance
    )
)

async def rate_limited_operation(key: str, operation: Callable) -> Result:
    allowed = await limiter.acquire(key, amount=1)
    if not allowed:
        raise RateLimitExceeded("Rate limit exceeded")
    return await operation()
```

---

### 5. Load Shedder

```python
from generators.resiliency.load_shedder import LoadShedder, SheddingPolicy

shedder = LoadShedder(
    policy=SheddingPolicy(
        max_concurrent=1000,
        queue_size=10000,
        shed_strategy="priority",  # or "random", "fifo"
        priority_key=lambda req: req.priority,
    )
)

async def handle_request(request: Request) -> Response:
    if not await shedder.try_acquire(request):
        raise HTTPException(503, "Service overloaded")
    return await handle_request(request)
```

---

### 6. Graceful Shutdown

```python
from generators.resiliency.graceful_shutdown import GracefulShutdown

shutdown = GracefulShutdown(
    drain_timeout=30.0,      # Time to drain connections
    force_timeout=60.0,      # Force kill after
    health_check_interval=5.0,
)

# In your app lifespan
@app.on_event("shutdown")
async def shutdown():
    await shutdown.graceful_shutdown()
```

---

## Common Patterns

### 1. Composed Resilience

```python
# Compose multiple resilience patterns
class ResilientClient:
    def __init__(self):
        self.circuit_breaker = CircuitBreaker(config)
        self.retry_budget = RetryBudget(...)
        self.timeout_budget = TimeoutBudget(...)
        self.bulkhead = Bulkhead(...)
    
    async def call(self, operation: Callable) -> Result:
        async with self.bulkhead:
            async with self.circuit_breaker:
                async with self.timeout_budget:
                    async with self.retry_budget:
                        return await operation()
```

---

### 2. Priority-Based Load Shedding

```python
class PriorityLoadShedder:
    def __init__(self, max_concurrent: int):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.priority_queues = {Priority.HIGH: [], Priority.NORMAL: [], Priority.LOW: []}
    
    async def acquire(self, priority: Priority = Priority.NORMAL) -> bool:
        if len(self.waiting) >= self.max_queue:
            if priority == Priority.LOW:
                return False  # Shed low priority
            # High/Normal: queue
        await self.semaphore.acquire()
        return True
```

---

## Common Pitfalls / Armadilhas

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Circuit breaker too sensitive** | Opens on transient errors | Increase failure_threshold; exclude expected errors |
| **Retry storm** | Cascading failures | Use RetryBudget; limit retry ratio |
| **Timeout too short** | False timeouts | Set realistic timeouts; use TimeoutBudget |
| **Bulkhead too small** | Underutilization | Tune based on load testing |
| **Rate limiter too strict** | False positives | Tune rate/window; use burst allowance |
| **Load shedding too aggressive** | Dropped valid requests | Tune thresholds; add priority |
| **Circuit breaker flapping** | Rapid open/close | Increase thresholds; add hysteresis |
| **Retry budget exhausted** | Legitimate retries blocked | Increase budget; tune window |

---

## Evolution Without Breaking Contracts

### Changing Circuit Breaker Thresholds

```python
# Non-breaking: adjust thresholds
config = CircuitBreakerConfig(
    failure_threshold=10,  # Was 5
    success_threshold=3,   # Was 2
)
```

### Adding New Retryable Exception

```python
# Non-breaking: add to retryable list
policy = RetryPolicy(
    retryable_exceptions=(
        TimeoutError,
        ConnectionError,
        NewTransientError,  # ADD HERE
    ),
)
```

---

## When to Ask for Human Review

| Scenario | Action |
|----------|--------|
| Changing circuit breaker thresholds | **REVIEW** — Affects failure detection |
| Changing retry budget | **REVIEW** — Affects retry behavior |
| Changing timeout budget | **REVIEW** — Affects latency |
| Adding new shedding strategy | **REVIEW** — May drop requests |
| Changing bulkhead size | **REVIEW** — Affects throughput |

---

## Health Checks & Monitoring

```python
@app.get("/health/resiliency")
async def resiliency_health():
    return {
        "status": "healthy",
        "checks": {
            "circuit_breakers": await check_all_circuit_breakers(),
            "retry_budget": await check_retry_budget(),
            "timeout_budget": await check_timeout_budget(),
            "bulkhead": await check_bulkhead(),
            "rate_limiters": await check_rate_limiters(),
            "load_shedder": await check_load_shedder(),
        }
    }

# Metrics:
# - circuit_breaker.state (closed/open/half_open)
# - retry_budget.used_ratio
# - timeout_budget.remaining
# - bulkhead.utilization
# - rate_limiter.rejection_rate
# - load_shedder.shed_rate
```

---

## Debugging Quick Reference

```bash
# Check circuit breaker state
python -c "
from app.resiliency import get_all_circuit_breakers
for cb in get_all_circuit_breakers():
    print(f'{cb.name}: {cb.state} (failures={cb.failure_count})')
"

# Check retry budget
python -c "
from app.resiliency import get_retry_budget
budget = get_retry_budget()
print(f'Used: {budget.used}/{budget.max} in window')
"

# Check bulkhead
python -c "
from app.resiliency import get_bulkhead
bh = get_bulkhead()
print(f'Concurrent: {bh.current}/{bh.max} | Queue: {bh.queue_size}/{bh.max_queue}')
"
```

---

## Performance Tuning

| Component | Tuning Knob | Typical Value |
|-----------|-------------|---------------|
| Circuit breaker | failure_threshold | 5-10 |
| Circuit breaker | success_threshold | 2-5 |
| Circuit breaker | timeout | 30-60s |
| Retry budget | budget_ratio | 0.1 (10%) |
| Retry budget | window | 60s |
| Timeout budget | total_timeout | 30s |
| Bulkhead | max_concurrent | 100-500 |
| Rate limiter | rate | 1000/min |
| Load shedder | max_concurrent | 1000 |

---

## Security Checklist

- [ ] Circuit breaker excludes validation errors
- [ ] Retry budget prevents retry storms
- [ ] Timeout budget prevents cascading timeouts
- [ ] Bulkhead prevents resource exhaustion
- [ ] Rate limiter prevents abuse
- [ ] Load shedder preserves high-priority traffic
- [ ] Graceful shutdown drains connections
- [ ] Cost tracker alerts on budget exceedance
- [ ] All resiliency patterns have metrics

---

*Resiliency Domain Maintenance Skill v1.0 | Maintained by Platform Team | Next review: 2026-12-04*