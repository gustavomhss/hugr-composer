from __future__ import annotations
from datetime import datetime
from datetime import timezone


async def run_retention_cycle(session_factory: object) -> dict[str, int]:
    """Execute one retention purge cycle across compliance_events.

    Args:
        session_factory: An ``async_sessionmaker`` (or callable returning
            ``AsyncSession``) from ``app.core.session``.

    Returns:
        Dict with ``deleted_count`` and ``run_at`` timestamp string.
    """
    from app.crud.compliance import purge_old_events
    deleted = 0
    async with session_factory() as session:
        deleted = await purge_old_events(session, retention_days=settings.COMPLIANCE_RETENTION_DEFAULT_DAYS)
    logger.info('retention_cycle_complete', extra={'deleted_count': deleted, 'run_at': datetime.now(timezone.utc).isoformat()})
    return {'deleted_count': deleted, 'run_at': datetime.now(timezone.utc).isoformat()}
