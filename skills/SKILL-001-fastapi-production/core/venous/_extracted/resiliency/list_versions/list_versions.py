from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_versions(session: AsyncSession, name: str, limit: int=50) -> list[MLModel]:
    """List all versions of a named model, newest first.

    Args:
        session: Active async database session.
        name: Logical model name.
        limit: Maximum number of rows to return (default 50).

    Returns:
        List of ``MLModel`` rows ordered by ``created_at`` descending.
    """
    result = await session.execute(select(MLModel).where(MLModel.name == name).order_by(MLModel.created_at.desc()).limit(limit))
    return list(result.scalars().all())
