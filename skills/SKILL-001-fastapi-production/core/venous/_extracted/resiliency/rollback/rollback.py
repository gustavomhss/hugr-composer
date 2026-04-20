from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def rollback(session: AsyncSession, name: str) -> MLModel | None:
    """Roll back the current production version; restore the previous one.

    Sets the current production row to ``rolled_back``, then sets the
    most-recently archived row back to ``production``.

    Args:
        session: Active async database session.
        name: Logical model name.

    Returns:
        The restored ``MLModel`` row, or ``None`` if rollback is not possible.
    """
    current = await get_active(session, name)
    if current is None:
        return None
    current.status = 'rolled_back'
    result = await session.execute(select(MLModel).where(MLModel.name == name, MLModel.status == 'archived').order_by(MLModel.promoted_at.desc()).limit(1))
    previous = result.scalars().first()
    if previous is None:
        return None
    previous.status = 'production'
    previous.promoted_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(previous)
    logger.info('Rolled back model %s to v%s', name, previous.version)
    return previous
