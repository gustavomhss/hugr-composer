from __future__ import annotations
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession


async def purge_expired_audit_logs(session: AsyncSession, retain_days: int) -> int:
    """Delete audit log entries older than *retain_days* days.

    NEVER deletes rows newer than the computed cutoff timestamp.
    The cutoff is ``now() - retain_days`` so only rows strictly older
    than the retention window are removed.

    Args:
        session: Async SQLAlchemy session (caller must commit).
        retain_days: Number of days to retain.  Rows with
            ``created_at < now() - interval '{retain_days} days'``
            are deleted.

    Returns:
        Number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    result = await session.execute(text('DELETE FROM audit_logs WHERE created_at < :cutoff'), {'cutoff': cutoff})
    return result.rowcount
