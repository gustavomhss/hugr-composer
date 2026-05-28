from __future__ import annotations
import os


class WorkerSettings:
    """ARQ WorkerSettings — configure Redis URL and job functions here.

    Attributes:
        functions: List of job functions the worker can execute.
        redis_settings: arq.connections.RedisSettings from REDIS_URL env var.
        max_jobs: Concurrency limit (10 by default).
        job_timeout: Hard timeout per job in seconds.
    """
    functions = [execute_task]
    redis_settings = arq.connections.RedisSettings.from_dsn(os.getenv('REDIS_URL', 'redis://localhost:6379'))
    max_jobs: int = 10
    job_timeout: int = int(os.getenv('TASK_MAX_DURATION_SECONDS', '3600'))
