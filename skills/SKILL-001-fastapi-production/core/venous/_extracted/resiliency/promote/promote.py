from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession


async def promote(session: AsyncSession, name: str, version: str) -> MLModel | None:
    """Promote *version* to production; archive the previous production row.

    1. Set the current production row (if any) to ``archived``.
    2. Set the target version to ``production`` and stamp ``promoted_at``.

    Args:
        session: Active async database session.
        name: Logical model name.
        version: Version to promote.

    Returns:
        The promoted ``MLModel`` row, or ``None`` if *version* not found.
    """
    target = await get_by_version(session, name, version)
    if target is None:
        return None
    await session.execute(update(MLModel).where(MLModel.name == name, MLModel.status == 'production').values(status='archived'))
    target.status = 'production'
    target.promoted_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(target)
    logger.info('Promoted model %s to production (v%s)', name, version)
    return target
