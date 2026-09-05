"""Pure Python primitive: SchedulerFactory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class SchedulerFactory:
    """Build and return an ``AsyncIOScheduler`` instance.

    APScheduler is imported lazily so the module can be loaded even
    when the SDK is not installed — the error surfaces only when
    ``start_scheduler`` is actually called.
    """

    @staticmethod
    def build() -> Any:
        """Return a scheduler configured from settings.

        Returns:
            A new ``AsyncIOScheduler`` with job store + timezone.

        Raises:
            ImportError: If ``apscheduler`` is not installed.
        """
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        jobstore_url = getattr(settings, 'SCHEDULER_JOBSTORE_URL', '') or ''
        jobstores: dict[str, Any] = {}
        if jobstore_url.startswith('redis://'):
            try:
                from apscheduler.jobstores.redis import RedisJobStore
                jobstores['default'] = RedisJobStore(jobs_key='apscheduler.jobs', run_times_key='apscheduler.run_times', host='localhost')
            except ImportError:
                logger.warning('apscheduler redis jobstore unavailable; falling back to memory')
        timezone = getattr(settings, 'SCHEDULER_TIMEZONE', 'UTC')
        return AsyncIOScheduler(jobstores=jobstores or None, timezone=timezone)
