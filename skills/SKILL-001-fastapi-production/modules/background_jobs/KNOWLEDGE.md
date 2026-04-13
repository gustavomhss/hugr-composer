# Module: Background Jobs — Production Task Processing for FastAPI

> The LLM generates: `BackgroundTasks` with fire-and-forget, no retry, no monitoring, no dead letter queue.
> The staff engineer knows: when to upgrade to ARQ, idempotency keys, exponential backoff with jitter, DLQ, task timeouts, priority queues.

---

## 1. When BackgroundTasks Is Enough vs When You Need a Real Queue

### WHY
FastAPI's built-in `BackgroundTasks` runs tasks in the same process as your web server. If the server crashes, the task is lost. If the task is CPU-intensive, it blocks your event loop. If you need to track completion, retry on failure, or survive restarts — it cannot do any of that. The LLM defaults to `BackgroundTasks` for everything. The staff engineer uses it only for trivial fire-and-forget work (logging, non-critical notifications) and reaches for ARQ the moment reliability matters.

### HOW
```python
# BackgroundTasks — OK for trivial, non-critical work
from fastapi import BackgroundTasks

@app.post("/users/")
async def create_user(user: UserCreate, bg: BackgroundTasks):
    db_user = await crud.create_user(user)
    bg.add_task(send_welcome_email, db_user.email)  # Fire-and-forget. Lost on crash.
    return db_user

# ARQ — when you need reliability
from arq import create_pool
from arq.connections import RedisSettings

async def send_welcome_email(ctx, email: str):
    """ARQ task: survives crashes, retries on failure, observable."""
    await email_service.send(template="welcome", to=email)

async def enqueue_welcome_email(email: str):
    redis = await create_pool(RedisSettings())
    await redis.enqueue_job("send_welcome_email", email)
```

### GOTCHA
`BackgroundTasks` runs AFTER the response is sent but INSIDE the same async event loop. A `time.sleep(60)` in a background task blocks your entire server for 60 seconds. Even with ARQ, never use sync blocking calls inside async tasks — use `await asyncio.sleep()` or run sync code in `run_in_executor()`.

---

## 2. ARQ — The Modern Async-Native Choice for FastAPI

### WHY
ARQ is built on asyncio from the ground up. No bridging between sync and async worlds like Celery requires. It uses Redis as its only backend (which you likely already have for caching/sessions). A single ARQ worker can run hundreds of concurrent I/O-bound jobs without forking processes. Celery is still the right choice for massive-scale enterprise systems needing complex workflows (chains, chords, canvas), RabbitMQ/SQS brokers, or when you already have Celery infrastructure. For greenfield FastAPI projects, ARQ is simpler, faster, and native.

### HOW
```python
# tasks.py
from arq import cron

async def process_payment(ctx, order_id: str, amount: int):
    """Process a payment. ctx contains the Redis pool and other dependencies."""
    redis = ctx["redis"]
    db = ctx["db"]
    await payment_gateway.charge(order_id, amount)

async def cleanup_expired_sessions(ctx):
    """Periodic cleanup task — runs every hour."""
    await ctx["db"].execute("DELETE FROM sessions WHERE expires_at < NOW()")

class WorkerSettings:
    """ARQ worker configuration — this is the entry point."""
    functions = [process_payment]
    cron_jobs = [cron(cleanup_expired_sessions, hour={0, 6, 12, 18})]
    redis_settings = RedisSettings(host="localhost", port=6379)
    max_jobs = 50           # Max concurrent jobs per worker
    job_timeout = 300       # 5 min default timeout
    max_tries = 3           # Retry up to 3 times
    health_check_interval = 30

    # Dependency injection via on_startup
    @staticmethod
    async def on_startup(ctx):
        ctx["db"] = await create_db_pool()

    @staticmethod
    async def on_shutdown(ctx):
        await ctx["db"].close()
```

```bash
# Run the worker
arq tasks.WorkerSettings
```

### GOTCHA
ARQ's `max_jobs` controls concurrency PER worker, not globally. If you run 4 workers with `max_jobs=50`, you can have 200 concurrent jobs. Size this based on your Redis connection pool and downstream service limits. Also: ARQ requires Redis 5.0+ for Streams support.

---

## 3. Task Idempotency — Idempotency Keys Prevent Double Processing

### WHY
Network retries, worker crashes during execution, and duplicate webhook deliveries all cause the same task to execute multiple times. Without idempotency, a payment gets charged twice, an email gets sent three times, or inventory gets decremented repeatedly. The idempotency key pattern ensures that re-executing a task with the same key produces the same result without side effects.

### HOW
```python
import hashlib

async def process_order(ctx, order_id: str, idempotency_key: str | None = None):
    """Process order with idempotency protection."""
    redis = ctx["redis"]

    # Generate deterministic key if not provided
    idem_key = idempotency_key or f"order:{order_id}"
    lock_key = f"idempotency:{idem_key}"

    # Check if already processed
    existing = await redis.get(lock_key)
    if existing:
        return {"status": "already_processed", "result": existing.decode()}

    # Mark as in-progress (SET NX with TTL to handle crashes)
    acquired = await redis.set(lock_key, "processing", nx=True, ex=3600)
    if not acquired:
        return {"status": "in_progress"}

    try:
        result = await _do_process_order(order_id)
        # Store result for future duplicate checks
        await redis.set(lock_key, f"completed:{result.id}", ex=86400)  # 24h TTL
        return {"status": "completed", "result": result.id}
    except Exception:
        # Remove lock so retry can proceed
        await redis.delete(lock_key)
        raise
```

### GOTCHA
The idempotency key MUST be deterministic — derived from business data (order_id, user_id + action), not random UUIDs. A random key defeats the purpose because retries generate new keys. TTL on the idempotency record must be long enough to cover the retry window but not infinite (Redis memory).

---

## 4. Retry with Exponential Backoff + Jitter

### WHY
Immediate retries after failure hammer the downstream service that just failed. Fixed-interval retries create thundering herds when many tasks fail simultaneously (e.g., database goes down, 1000 tasks fail, all retry at T+5s). Exponential backoff spreads retries over time. Jitter adds randomness so retries from different workers don't collide.

### HOW
```python
import random
from arq import Retry

async def call_external_api(ctx, url: str, payload: dict):
    """Call external API with exponential backoff on failure."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
        job_try = ctx.get("job_try", 1)
        max_retries = 5

        if job_try >= max_retries:
            # Move to dead letter queue instead of silent drop
            await _send_to_dlq(ctx, "call_external_api", {"url": url, "payload": payload},
                               error=str(exc), attempts=job_try)
            raise  # Final failure

        # Exponential backoff: 2^attempt * base + jitter
        base_delay = 2 ** job_try * 5  # 10s, 20s, 40s, 80s, 160s
        jitter = random.uniform(0, base_delay * 0.3)  # 0-30% jitter
        delay = base_delay + jitter

        raise Retry(defer=delay)


# For non-ARQ contexts, a standalone backoff calculator:
def backoff_delay(attempt: int, base: float = 1.0, cap: float = 300.0) -> float:
    """Calculate delay with exponential backoff + full jitter (AWS style).

    AWS recommends 'full jitter': random(0, min(cap, base * 2^attempt))
    This decorrelates retries better than equal/decorrelated jitter.
    """
    exp = min(cap, base * (2 ** attempt))
    return random.uniform(0, exp)
```

### GOTCHA
Always cap the maximum delay (`cap=300` means 5 minutes max). Without a cap, attempt 20 would wait 2^20 seconds = 12 days. And always use `job_try` from context, not a local counter — local state is lost on worker restart.

---

## 5. Dead Letter Queues — What to Do with Permanently Failed Tasks

### WHY
After max retries, a task has exhausted its retry budget. Silently dropping it means lost data, missed payments, or orphaned records that nobody knows about. A Dead Letter Queue (DLQ) captures permanently failed tasks with full context (arguments, error, attempt count, timestamps) for human inspection, automated alerting, and potential replay.

### HOW
```python
import json
from datetime import datetime, timezone

async def _send_to_dlq(
    ctx, task_name: str, args: dict, error: str, attempts: int,
):
    """Move a permanently failed task to the dead letter queue."""
    redis = ctx["redis"]
    dlq_entry = {
        "task": task_name,
        "args": json.dumps(args, default=str),
        "error": error,
        "attempts": attempts,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "worker_id": ctx.get("worker_id", "unknown"),
    }
    # Use Redis Stream for ordered, persistent DLQ
    await redis.xadd("dlq:tasks", dlq_entry, maxlen=10000)

async def inspect_dlq(ctx, count: int = 10) -> list[dict]:
    """Read recent DLQ entries for inspection."""
    redis = ctx["redis"]
    entries = await redis.xrevrange("dlq:tasks", count=count)
    return [{"id": eid, **data} for eid, data in entries]

async def replay_dlq_entry(ctx, entry_id: str):
    """Replay a specific DLQ entry by re-enqueueing the original task."""
    redis = ctx["redis"]
    entries = await redis.xrange("dlq:tasks", min=entry_id, max=entry_id)
    if not entries:
        raise ValueError(f"DLQ entry {entry_id} not found")
    _, data = entries[0]
    task_name = data["task"]
    args = json.loads(data["args"])
    # Re-enqueue with fresh retry budget
    await redis.enqueue_job(task_name, **args)
    # Mark as replayed (don't delete — keep audit trail)
    await redis.xadd("dlq:replayed", {"original_id": entry_id, "replayed_at": datetime.now(timezone.utc).isoformat()})
```

### GOTCHA
Use Redis Streams (`XADD`) for DLQ, not Lists (`LPUSH`). Streams support consumer groups, ID-based reads, and `MAXLEN` trimming. Set `maxlen=10000` to prevent unbounded growth. Monitor DLQ depth — a growing DLQ means a systemic issue, not a one-off failure.

---

## 6. Task Timeout and Cancellation

### WHY
A task that hangs forever ties up a worker slot, accumulates Redis connections, and can cascade into backpressure on the entire queue. ARQ defaults to `job_timeout=300` (5 minutes), but you should set explicit timeouts per task based on expected duration. Tasks that exceed the timeout are cancelled and requeued (if retries remain).

### HOW
```python
from arq import func

async def generate_report(ctx, report_id: str):
    """Generate a large report — allow more time than default."""
    # This task gets 15 minutes instead of the default 5
    await _build_report(report_id)

async def send_notification(ctx, user_id: str, message: str):
    """Send a push notification — should be fast."""
    # This task gets only 30 seconds
    await _push(user_id, message)

class WorkerSettings:
    functions = [
        func(generate_report, timeout=900),     # 15 min
        func(send_notification, timeout=30),     # 30 sec
    ]
    job_timeout = 300  # Default for tasks without explicit timeout

    # Graceful shutdown: finish current tasks, don't accept new ones
    allow_abort_jobs = True  # Allow SIGTERM to abort long-running jobs
```

### GOTCHA
ARQ's timeout kills the task via `asyncio.CancelledError`. If your task has cleanup logic (closing DB connections, releasing locks), wrap it in `try/finally`. And `allow_abort_jobs=True` means SIGTERM during a deploy will cancel in-progress tasks — make sure they are idempotent so re-execution on restart is safe.

---

## 7. Task Result Storage and Polling

### WHY
Fire-and-forget is fine for side effects (send email, update cache), but many tasks produce results that the client needs (report generation, data export, AI inference). ARQ stores results in Redis with configurable TTL. The client can poll for completion or use WebSocket notifications.

### HOW
```python
from arq.connections import ArqRedis
from fastapi import HTTPException

# Enqueue and return job ID for polling
@app.post("/reports/", status_code=202)
async def create_report(body: ReportRequest, redis: ArqRedis = Depends(get_redis)):
    job = await redis.enqueue_job("generate_report", body.report_id)
    return {"job_id": job.job_id, "status": "queued", "poll_url": f"/jobs/{job.job_id}"}

# Poll for result
@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str, redis: ArqRedis = Depends(get_redis)):
    job = await redis.job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    info = await job.info()
    if info is None:
        return {"job_id": job_id, "status": "unknown"}

    status = info.status  # queued, in_progress, complete, not_found
    result = info.result if info.status == "complete" else None

    return {
        "job_id": job_id,
        "status": info.status,
        "result": result,
        "enqueue_time": info.enqueue_time.isoformat() if info.enqueue_time else None,
    }

# ARQ worker config: keep results for 1 hour
class WorkerSettings:
    keep_result = 3600      # Result TTL in seconds
    keep_result_forever = False
```

### GOTCHA
`keep_result` uses Redis memory. A task that returns a 10MB report stored for 1 hour across 1000 jobs = 10GB Redis memory. For large results, store the output in S3/filesystem and return only the URL in the task result. Also: `job.info()` returns `None` if the result TTL has expired.

---

## 8. Periodic/Scheduled Tasks (Cron-Like)

### WHY
Many production systems need recurring work: cleanup expired sessions, sync data from external APIs, generate daily reports, check SLA compliance. ARQ has native cron job support — no need for external cron, APScheduler, or Celery Beat. Jobs run in the same worker with the same dependency injection, retry logic, and observability.

### HOW
```python
from arq import cron

async def daily_report(ctx):
    """Generate and email daily report. Runs at 6 AM UTC."""
    report = await build_daily_report(ctx["db"])
    await send_email(to="team@company.com", subject="Daily Report", body=report)

async def cleanup_stale_jobs(ctx):
    """Remove old DLQ entries and expired temp files. Every 6 hours."""
    redis = ctx["redis"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    await redis.xtrim("dlq:tasks", maxlen=5000)
    await cleanup_temp_files(older_than=cutoff)

async def health_check_external(ctx):
    """Ping external dependencies every 5 minutes."""
    for service in ["payments", "email", "storage"]:
        healthy = await check_service(service)
        if not healthy:
            await alert_ops(f"{service} is down")

class WorkerSettings:
    cron_jobs = [
        cron(daily_report, hour=6, minute=0),                    # 6:00 AM UTC daily
        cron(cleanup_stale_jobs, hour={0, 6, 12, 18}),          # Every 6 hours
        cron(health_check_external, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),  # Every 5 min
    ]
```

### GOTCHA
ARQ cron jobs run on ALL workers by default. If you have 4 workers, `daily_report` runs 4 times at 6 AM. Use `unique=True` (default in ARQ) or a distributed lock to ensure single execution. Also: cron jobs don't retry by default — wrap critical cron tasks in try/except with explicit error handling.

---

## 9. Task Priority Queues

### WHY
Not all tasks are equal. A payment confirmation must execute before a marketing email. Without priority, a flood of low-priority tasks (bulk emails, report generation) can starve high-priority tasks (payment processing, security alerts). ARQ supports named queues that can be prioritized by running dedicated workers per queue.

### HOW
```python
# Enqueue with queue name for priority routing
async def enqueue_with_priority(redis: ArqRedis, task: str, *args, priority: str = "default"):
    queue_map = {
        "critical": "arq:queue:critical",    # Payment, security
        "default": "arq:queue:default",      # Normal operations
        "bulk": "arq:queue:bulk",            # Reports, emails, exports
    }
    queue_name = queue_map.get(priority, "arq:queue:default")
    await redis.enqueue_job(task, *args, _queue_name=queue_name)

# Usage
await enqueue_with_priority(redis, "process_payment", order_id, priority="critical")
await enqueue_with_priority(redis, "send_marketing_email", user_id, priority="bulk")

# Run separate workers per priority
# Worker 1 (critical) — dedicated resources, fast polling
# arq tasks.CriticalWorkerSettings
# Worker 2 (default + bulk) — shared, normal polling
# arq tasks.DefaultWorkerSettings
```

### GOTCHA
Running separate workers per queue means separate processes and separate Redis connections. Size your Redis `maxclients` accordingly. An alternative for simple priority is a single queue with `_defer_by=0` for urgent tasks (skip to front) — but this is not true priority, just schedule manipulation.

---

## 10. Monitoring Task Queues (Queue Depth, Processing Time, Failure Rate)

### WHY
A production task queue without monitoring is a black box. You need to know: how deep is the queue (backpressure indicator), how long tasks take (SLA compliance), how many fail (reliability indicator), and how many are in the DLQ (systemic issues). Without this, you discover problems when users complain, not when metrics spike.

### HOW
```python
from arq.connections import ArqRedis

async def get_queue_metrics(redis: ArqRedis) -> dict:
    """Collect queue health metrics for monitoring/alerting."""
    # Queue depth — how many jobs are waiting
    queue_len = await redis.zcard("arq:queue")
    # In-progress jobs
    in_progress = await redis.zcard("arq:in-progress")
    # DLQ depth
    dlq_len = await redis.xlen("dlq:tasks")
    # Results (completed recently)
    result_keys = await redis.keys("arq:result:*")

    return {
        "queue_depth": queue_len,
        "in_progress": in_progress,
        "dlq_depth": dlq_len,
        "completed_cached": len(result_keys),
        "healthy": queue_len < 1000 and dlq_len < 100,
    }

# Expose as health endpoint
@app.get("/health/queue")
async def queue_health(redis: ArqRedis = Depends(get_redis)):
    metrics = await get_queue_metrics(redis)
    status_code = 200 if metrics["healthy"] else 503
    return JSONResponse(metrics, status_code=status_code)

# For Prometheus/StatsD integration
async def emit_queue_metrics(ctx):
    """Cron job: emit metrics every minute to your monitoring stack."""
    metrics = await get_queue_metrics(ctx["redis"])
    statsd.gauge("queue.depth", metrics["queue_depth"])
    statsd.gauge("queue.in_progress", metrics["in_progress"])
    statsd.gauge("queue.dlq_depth", metrics["dlq_depth"])
```

### GOTCHA
`redis.keys("arq:result:*")` is O(N) and blocks Redis on large datasets. In production, use `SCAN` instead or maintain a counter. Alert on queue depth > threshold (e.g., > 500 for 5 minutes = tasks accumulating faster than processing). Alert on DLQ depth > 0 — any DLQ entry means a task permanently failed.
