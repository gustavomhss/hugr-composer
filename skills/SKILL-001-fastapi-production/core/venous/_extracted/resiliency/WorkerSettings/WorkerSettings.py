from __future__ import annotations


class WorkerSettings:
    """arq worker configuration.

    Attributes:
        functions: Task functions registered for execution.
        redis_settings: Redis connection parameters (derived from
            ``settings.REDIS_URL``).
        max_jobs: Maximum concurrent jobs per worker process.
        job_timeout: Per-job hard wall-clock timeout in seconds.
        max_tries: Maximum retry attempts before permanent failure.
        keep_result: How long to retain completed job results in Redis.
        on_startup: Async callable invoked once when the worker boots.
        on_shutdown: Async callable invoked once when the worker exits.
    """
    functions = TASK_REGISTRY
    redis_settings = RedisSettings.from_dsn(str(settings.REDIS_URL))
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = settings.ARQ_JOB_TIMEOUT_SECONDS
    max_tries = settings.ARQ_MAX_TRIES
    keep_result = settings.ARQ_KEEP_RESULTS_SECONDS
    on_startup = startup
    on_shutdown = shutdown
