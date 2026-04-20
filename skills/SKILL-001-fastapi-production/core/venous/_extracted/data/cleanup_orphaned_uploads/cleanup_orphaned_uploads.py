from __future__ import annotations
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def cleanup_orphaned_uploads(session: AsyncSession) -> dict[str, int]:
    """Delete storage objects and DB rows for all uploads stuck in 'pending' past TTL.

    Processes rows in batches of ``BATCH_SIZE`` to avoid unbounded memory use.
    Uses ``WITH FOR UPDATE SKIP LOCKED`` to allow safe concurrent cleanup workers.

    Args:
        session: Async SQLAlchemy session (caller manages commit/rollback).

    Returns:
        Dict with ``deleted_storage`` (storage objects deleted) and
        ``deleted_db`` (DB rows deleted).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_TTL_MINUTES)
    deleted_storage = 0
    deleted_db = 0
    storage = get_storage()
    while True:
        stmt = select(FileMetadata).where(FileMetadata.status == 'pending').where(FileMetadata.created_at < cutoff).limit(BATCH_SIZE).with_for_update(skip_locked=True)
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            break
        for row in rows:
            try:
                await storage.delete(row.stored_key)
                deleted_storage += 1
            except Exception as exc:
                logger.warning('cleanup: storage delete failed for %s: %s', row.stored_key, exc)
        ids = [row.id for row in rows]
        await session.execute(delete(FileMetadata).where(FileMetadata.id.in_(ids)))
        await session.commit()
        deleted_db += len(ids)
        logger.info('cleanup: purged %d orphaned uploads (batch)', len(ids))
    logger.info('cleanup complete: storage=%d db=%d', deleted_storage, deleted_db)
    return {'deleted_storage': deleted_storage, 'deleted_db': deleted_db}
