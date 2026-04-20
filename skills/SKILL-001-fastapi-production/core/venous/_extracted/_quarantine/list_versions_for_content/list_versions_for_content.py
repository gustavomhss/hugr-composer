from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_versions_for_content(session: AsyncSession, content_id: str, status: str | None=None, limit: int=50) -> list[ContentVersion]:
    """List versions for a content item, optionally filtered by status.

    Args:
        session: Async SQLAlchemy session.
        content_id: Opaque content item identifier.
        status: Optional lifecycle status filter.
        limit: Maximum rows to return.

    Returns:
        List of ContentVersion instances ordered by version_number desc.
    """
    stmt = select(ContentVersion).where(ContentVersion.content_id == content_id)
    if status is not None:
        stmt = stmt.where(ContentVersion.status == status)
    stmt = stmt.order_by(ContentVersion.version_number.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
