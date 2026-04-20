from __future__ import annotations


def create_celery_app() -> 'Celery':
    """Build and return a configured Celery application instance.

    Reads broker URL from ``settings.CELERY_BROKER_URL`` (falls back to
    ``settings.REDIS_URL``) and result backend from
    ``settings.CELERY_RESULT_BACKEND``.

    Task modules are discovered via ``autodiscover_tasks`` pointing at
    ``app.workers.celery_tasks`` so adding new task modules does not
    require editing this factory.

    Returns:
        A fully configured ``Celery`` application instance.
    """
    from celery import Celery
    from app.core.config import settings
    from app.workers.celery_beat_schedule import BEAT_SCHEDULE
    broker = getattr(settings, 'CELERY_BROKER_URL', None) or str(settings.REDIS_URL)
    backend = getattr(settings, 'CELERY_RESULT_BACKEND', None) or str(settings.REDIS_URL)
    always_eager = bool(getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False))
    app = Celery('app', broker=broker, backend=backend, include=['app.workers.celery_tasks'])
    app.config_from_object({'task_always_eager': always_eager, 'task_eager_propagates': always_eager, 'beat_schedule': BEAT_SCHEDULE, 'timezone': 'UTC', 'task_serializer': 'json', 'result_serializer': 'json', 'accept_content': ['json']})
    app.autodiscover_tasks(['app.workers.celery_tasks'])
    return app
