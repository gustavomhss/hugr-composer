from __future__ import annotations


async def start_scheduler() -> None:
    """Start the scheduler and register declared cron jobs.

    If ``apscheduler`` is not installed OR ``SCHEDULER_ENABLED`` is
    false, this is a silent no-op — the application keeps booting.
    """
    if not getattr(settings, 'SCHEDULER_ENABLED', True):
        logger.info('scheduler.disabled')
        return
    try:
        sched = get_scheduler()
    except ImportError:
        logger.warning('scheduler.apscheduler_not_installed')
        return
    from app.workers.cron_jobs import register_jobs
    register_jobs(sched)
    sched.start()
    logger.info('scheduler.started', extra={'jobs': len(sched.get_jobs())})
