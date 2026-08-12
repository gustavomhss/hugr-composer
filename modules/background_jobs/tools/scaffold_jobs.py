"""
SKILL-001 Background Jobs Tool: Generate production background job infrastructure.

Creates a complete ARQ-based async task queue setup with dead letter queues,
retry with exponential backoff, idempotency keys, task result storage,
periodic tasks, and queue health monitoring. All generated code follows
KNOWLEDGE.md patterns.

Generated files:
    jobs/__init__.py        -- package marker with re-exports
    jobs/tasks.py           -- task definitions with retry, timeout, idempotency
    jobs/worker.py          -- ARQ WorkerSettings with cron jobs and lifecycle hooks
    jobs/dlq.py             -- dead letter queue: capture, inspect, replay
    jobs/health.py          -- queue health metrics endpoint
    jobs/dependencies.py    -- FastAPI dependency for ArqRedis pool
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_resiliency_generate_jobs',
    'description': 'Generate production ARQ-based async task queue: DLQ, retry with backoff, idempotency keys, periodic tasks, health monitoring.',
    'tags': ['jobs', 'resiliency', 'generator'],
    'entry': 'generate_background_jobs',
    'annotations': {'readOnlyHint': False, 'destructiveHint': False},
}

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _init_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Background jobs module — ARQ-based async task processing.\"\"\"

        from .tasks import process_order, send_notification, call_external_api
        from .dlq import send_to_dlq, inspect_dlq, replay_dlq_entry
        from .health import get_queue_metrics

        __all__ = [
            "process_order",
            "send_notification",
            "call_external_api",
            "send_to_dlq",
            "inspect_dlq",
            "replay_dlq_entry",
            "get_queue_metrics",
        ]
    """)


def _dependencies_py() -> str:
    return textwrap.dedent("""\
        \"\"\"FastAPI dependencies for ARQ Redis pool.\"\"\"

        from __future__ import annotations

        from arq import create_pool
        from arq.connections import ArqRedis, RedisSettings

        _pool: ArqRedis | None = None


        async def init_arq_pool(redis_url: str = "redis://localhost:6379") -> ArqRedis:
            \"\"\"Initialize the ARQ Redis pool. Call from lifespan startup.\"\"\"
            global _pool
            parts = redis_url.replace("redis://", "").split(":")
            host = parts[0] if parts else "localhost"
            port = int(parts[1].split("/")[0]) if len(parts) > 1 else 6379
            _pool = await create_pool(RedisSettings(host=host, port=port))
            return _pool


        async def close_arq_pool() -> None:
            \"\"\"Close the ARQ Redis pool. Call from lifespan shutdown.\"\"\"
            global _pool
            if _pool:
                await _pool.close()
                _pool = None


        async def get_arq_redis() -> ArqRedis:
            \"\"\"FastAPI dependency that returns the ARQ Redis pool.\"\"\"
            if _pool is None:
                raise RuntimeError(
                    "ARQ pool not initialized. Call init_arq_pool() in lifespan."
                )
            return _pool
    """)


def _tasks_py(with_dlq: bool) -> str:
    dlq_import = "\nfrom .dlq import send_to_dlq" if with_dlq else ""

    if with_dlq:
        dlq_block = (
            "\n            # Move to dead letter queue instead of silent drop"
            "\n            await send_to_dlq("
            '\n                ctx, "call_external_api",'
            '\n                {"url": url, "payload": payload},'
            "\n                error=str(exc), attempts=job_try,"
            "\n            )"
        )
    else:
        dlq_block = "\n            # Max retries exceeded — task permanently failed"

    template = textwrap.dedent("""\
        \"\"\"Task definitions for ARQ workers.

        Each task receives a context dict (ctx) with dependencies injected
        by WorkerSettings.on_startup. Tasks must be idempotent — they may
        be executed more than once due to worker restarts or retries.
        \"\"\"

        from __future__ import annotations

        import json
        import random
        import logging

        import httpx
        from arq import Retry
        __DLQ_IMPORT__

        logger = logging.getLogger("jobs.tasks")


        # -------------------------------------------------------------------
        # Idempotency helper
        # -------------------------------------------------------------------

        async def _check_idempotency(ctx: dict, key: str) -> str | None:
            \"\"\"Check if a task was already processed. Returns result if yes.\"\"\"
            redis = ctx["redis"]
            existing = await redis.get(f"idempotency:{key}")
            if existing:
                return existing.decode()
            return None


        async def _mark_idempotent(ctx: dict, key: str, result: str, ttl: int = 86400):
            \"\"\"Mark a task as processed for idempotency.\"\"\"
            redis = ctx["redis"]
            await redis.set(f"idempotency:{key}", result, ex=ttl)


        # -------------------------------------------------------------------
        # Tasks
        # -------------------------------------------------------------------

        async def process_order(ctx: dict, order_id: str, amount: int):
            \"\"\"Process an order payment. Idempotent via order_id.\"\"\"
            idem_key = f"order:{order_id}"
            existing = await _check_idempotency(ctx, idem_key)
            if existing:
                logger.info(f"Order {order_id} already processed: {existing}")
                return {"status": "already_processed", "result": existing}

            # Acquire processing lock (SET NX with TTL)
            redis = ctx["redis"]
            lock_acquired = await redis.set(
                f"lock:order:{order_id}", "processing", nx=True, ex=300,
            )
            if not lock_acquired:
                logger.info(f"Order {order_id} is being processed by another worker")
                return {"status": "in_progress"}

            try:
                # TODO: Replace with actual payment processing
                logger.info(f"Processing order {order_id} for {amount} cents")
                result_id = f"payment_{order_id}"
                await _mark_idempotent(ctx, idem_key, result_id)
                return {"status": "completed", "result": result_id}
            finally:
                await redis.delete(f"lock:order:{order_id}")


        async def send_notification(ctx: dict, user_id: str, message: str):
            \"\"\"Send a push notification — fast, low-priority task.\"\"\"
            logger.info(f"Sending notification to {user_id}: {message[:50]}")
            # TODO: Replace with actual push notification service
            return {"status": "sent", "user_id": user_id}


        async def call_external_api(ctx: dict, url: str, payload: dict):
            \"\"\"Call external API with exponential backoff on failure.

            Retries up to 5 times with exponential backoff + jitter.
            After max retries, sends to dead letter queue.
            \"\"\"
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                job_try = ctx.get("job_try", 1)
                max_retries = 5

                if job_try >= max_retries:
                    logger.error(
                        f"Task call_external_api permanently failed after "
                        f"{job_try} attempts: {exc}"
                    )__DLQ_CALL__
                    raise  # Final failure

                # Exponential backoff: 2^attempt * base + jitter
                base_delay = 2 ** job_try * 5  # 10s, 20s, 40s, 80s, 160s
                jitter = random.uniform(0, base_delay * 0.3)
                delay = base_delay + jitter
                logger.warning(
                    f"Task call_external_api attempt {job_try} failed, "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                raise Retry(defer=delay)
    """)
    result = template.replace("__DLQ_IMPORT__", dlq_import)
    result = result.replace("__DLQ_CALL__", dlq_block)
    # Clean up empty import line if no DLQ
    if not dlq_import:
        result = result.replace("\n\n\nlogger", "\n\nlogger")
    return result


def _dlq_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Dead Letter Queue — capture, inspect, and replay permanently failed tasks.

        Uses Redis Streams for ordered, persistent storage with bounded growth.
        Failed tasks are stored with full context for debugging and replay.
        \"\"\"

        from __future__ import annotations

        import json
        import logging
        from datetime import datetime, timezone

        logger = logging.getLogger("jobs.dlq")

        DLQ_STREAM = "dlq:tasks"
        DLQ_REPLAYED_STREAM = "dlq:replayed"
        DLQ_MAX_LEN = 10000


        async def send_to_dlq(
            ctx: dict,
            task_name: str,
            args: dict,
            error: str,
            attempts: int,
        ) -> str:
            \"\"\"Move a permanently failed task to the dead letter queue.

            Args:
                ctx: ARQ context with Redis pool.
                task_name: Name of the failed task function.
                args: Original task arguments.
                error: Error message from the final failure.
                attempts: Total number of attempts made.

            Returns:
                The Redis Stream entry ID of the DLQ record.
            \"\"\"
            redis = ctx["redis"]
            dlq_entry = {
                "task": task_name,
                "args": json.dumps(args, default=str),
                "error": error[:2000],  # Truncate to prevent huge entries
                "attempts": str(attempts),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }
            entry_id = await redis.xadd(DLQ_STREAM, dlq_entry, maxlen=DLQ_MAX_LEN)
            logger.error(
                f"Task {task_name} moved to DLQ after {attempts} attempts: {error[:200]}"
            )
            return entry_id


        async def inspect_dlq(ctx: dict, count: int = 20) -> list[dict]:
            \"\"\"Read recent DLQ entries for inspection (newest first).

            Args:
                ctx: ARQ context with Redis pool.
                count: Number of entries to return (default 20, max 100).

            Returns:
                List of DLQ entries with id, task, args, error, attempts, failed_at.
            \"\"\"
            redis = ctx["redis"]
            count = min(count, 100)
            entries = await redis.xrevrange(DLQ_STREAM, count=count)
            result = []
            for entry_id, data in entries:
                item = {"id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id}
                for k, v in data.items():
                    key = k.decode() if isinstance(k, bytes) else k
                    val = v.decode() if isinstance(v, bytes) else v
                    item[key] = val
                result.append(item)
            return result


        async def replay_dlq_entry(ctx: dict, entry_id: str) -> dict:
            \"\"\"Replay a specific DLQ entry by re-enqueueing the original task.

            The original DLQ entry is NOT deleted — kept for audit trail.
            A record of the replay is added to dlq:replayed.

            Args:
                ctx: ARQ context with Redis pool.
                entry_id: The Redis Stream entry ID to replay.

            Returns:
                Dict with replay status and new job info.
            \"\"\"
            redis = ctx["redis"]
            entries = await redis.xrange(DLQ_STREAM, min=entry_id, max=entry_id)
            if not entries:
                raise ValueError(f"DLQ entry {entry_id} not found")

            _, data = entries[0]
            task_name = data.get(b"task", data.get("task", b"")).decode() \\
                if isinstance(data.get(b"task", data.get("task", b"")), bytes) \\
                else data.get("task", "")
            args_raw = data.get(b"args", data.get("args", b"{}")).decode() \\
                if isinstance(data.get(b"args", data.get("args", b"{}")), bytes) \\
                else data.get("args", "{}")
            args = json.loads(args_raw)

            # Re-enqueue with fresh retry budget
            job = await redis.enqueue_job(task_name, **args)

            # Record the replay (audit trail)
            await redis.xadd(DLQ_REPLAYED_STREAM, {
                "original_id": entry_id,
                "task": task_name,
                "replayed_at": datetime.now(timezone.utc).isoformat(),
                "new_job_id": job.job_id if job else "unknown",
            }, maxlen=DLQ_MAX_LEN)

            logger.info(f"Replayed DLQ entry {entry_id} -> job {job.job_id if job else 'N/A'}")
            return {
                "status": "replayed",
                "original_entry": entry_id,
                "new_job_id": job.job_id if job else None,
                "task": task_name,
            }
    """)


def _worker_py() -> str:
    return textwrap.dedent("""\
        \"\"\"ARQ Worker configuration — entry point for background task processing.

        Run with: arq jobs.worker.WorkerSettings
        \"\"\"

        from __future__ import annotations

        import logging

        from arq import cron, func
        from arq.connections import RedisSettings

        from .tasks import call_external_api, process_order, send_notification

        logger = logging.getLogger("jobs.worker")


        async def cleanup_expired_data(ctx: dict):
            \"\"\"Periodic cleanup of expired idempotency keys and temp data.\"\"\"
            redis = ctx["redis"]
            # Redis handles TTL expiry automatically for idempotency keys.
            # This cron job handles any application-level cleanup.
            logger.info("Running periodic cleanup")
            # TODO: Add application-specific cleanup logic


        class WorkerSettings:
            \"\"\"ARQ worker settings — configure functions, cron, and lifecycle.\"\"\"

            # Task functions with per-task timeout overrides
            functions = [
                func(process_order, timeout=120),        # 2 min
                func(send_notification, timeout=30),     # 30 sec
                func(call_external_api, timeout=60),     # 1 min
            ]

            # Periodic / scheduled tasks
            cron_jobs = [
                cron(cleanup_expired_data, hour={0, 6, 12, 18}, minute=0),
            ]

            # Redis connection
            redis_settings = RedisSettings(host="localhost", port=6379)

            # Worker behavior
            max_jobs = 50               # Max concurrent jobs per worker
            job_timeout = 300           # Default timeout (5 min)
            max_tries = 3              # Default retry count
            health_check_interval = 30  # Health check every 30s
            keep_result = 3600         # Keep results for 1 hour
            allow_abort_jobs = True    # Allow graceful abort on SIGTERM

            @staticmethod
            async def on_startup(ctx: dict) -> None:
                \"\"\"Called when the worker starts. Initialize dependencies.\"\"\"
                logger.info("ARQ worker starting up")
                # TODO: Initialize DB pool, HTTP clients, etc.
                # ctx["db"] = await create_db_pool()
                # ctx["http"] = httpx.AsyncClient()

            @staticmethod
            async def on_shutdown(ctx: dict) -> None:
                \"\"\"Called when the worker shuts down. Cleanup dependencies.\"\"\"
                logger.info("ARQ worker shutting down")
                # TODO: Close DB pool, HTTP clients, etc.
                # await ctx["db"].close()
                # await ctx["http"].aclose()
    """)


def _health_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Queue health metrics — monitor depth, in-progress, DLQ, and results.\"\"\"

        from __future__ import annotations

        from arq.connections import ArqRedis


        async def get_queue_metrics(redis: ArqRedis) -> dict:
            \"\"\"Collect queue health metrics for monitoring and alerting.

            Returns:
                Dict with queue_depth, in_progress, dlq_depth, completed_cached,
                and a boolean healthy flag.
            \"\"\"
            # Queue depth — jobs waiting to be processed
            queue_depth = await redis.zcard("arq:queue") or 0
            # In-progress — jobs currently being processed
            in_progress = await redis.zcard("arq:in-progress") or 0
            # DLQ depth — permanently failed tasks
            dlq_depth = 0
            try:
                dlq_depth = await redis.xlen("dlq:tasks") or 0
            except Exception:
                pass  # DLQ stream may not exist yet
            # Completed recently (cached results)
            result_count = 0
            async for _ in redis.scan_iter(match="arq:result:*", count=100):
                result_count += 1
                if result_count >= 10000:
                    break  # Cap scan to avoid blocking

            return {
                "queue_depth": queue_depth,
                "in_progress": in_progress,
                "dlq_depth": dlq_depth,
                "completed_cached": result_count,
                "healthy": queue_depth < 1000 and dlq_depth < 100,
            }
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_background_jobs(
    output_dir: str,
    backend: str = "arq",
    with_dlq: bool = True,
) -> dict:
    """
    Generate a production-ready background jobs module for a FastAPI project.

    Creates an ARQ-based async task queue with idempotency, retry logic,
    dead letter queues, periodic tasks, and health monitoring inside a
    ``jobs/`` subdirectory of *output_dir*.

    Args:
        output_dir: Parent directory where the ``jobs/`` package will be created.
        backend: Task queue backend. Currently only "arq" is supported.
        with_dlq: Include dead letter queue for permanently failed tasks.

    Returns:
        Dict with ``created_files`` (list of paths) and ``jobs_path`` (str).

    Example::

        result = generate_background_jobs("/tmp/myproject", with_dlq=True)
        print(result["created_files"])
        # ['jobs/__init__.py', 'jobs/dependencies.py', 'jobs/tasks.py',
        #  'jobs/worker.py', 'jobs/dlq.py', 'jobs/health.py']
    """
    if backend != "arq":
        raise ValueError(f"Unsupported backend: {backend}. Only 'arq' is supported.")

    jobs_dir = Path(output_dir) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "dependencies.py": _dependencies_py(),
        "tasks.py": _tasks_py(with_dlq),
        "worker.py": _worker_py(),
        "health.py": _health_py(),
    }

    if with_dlq:
        files["dlq.py"] = _dlq_py()

    created: list[str] = []
    for filename, content in files.items():
        filepath = jobs_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"jobs/{filename}")

    return {
        "created_files": created,
        "jobs_path": str(jobs_dir),
        "backend": backend,
        "with_dlq": with_dlq,
    }
