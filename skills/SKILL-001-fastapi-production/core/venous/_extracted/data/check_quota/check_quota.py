from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def check_quota(session: AsyncSession, user_id: uuid.UUID, incoming_bytes: int) -> None:
    """Raise HTTP 413 if confirmed storage + incoming_bytes exceeds quota.

    Must be called inside a ``quota_lock`` context to prevent race conditions.

    Args:
        session: Async SQLAlchemy session.
        user_id: UUID of the uploading user.
        incoming_bytes: Size of the file about to be uploaded.

    Raises:
        HTTPException: 413 if the user would exceed their quota.
    """
    from fastapi import HTTPException
    from app.core.config import settings
    stmt = select(func.coalesce(func.sum(FileMetadata.size_bytes), 0)).where(FileMetadata.uploaded_by == user_id).where(FileMetadata.status == 'confirmed')
    used_bytes: int = (await session.execute(stmt)).scalar_one()
    quota_bytes = getattr(settings, 'QUOTA_MB_PER_USER', 500) * 1024 * 1024
    if used_bytes + incoming_bytes > quota_bytes:
        used_mb = used_bytes / (1024 * 1024)
        quota_mb = getattr(settings, 'QUOTA_MB_PER_USER', 500)
        raise HTTPException(status_code=413, detail=f'Quota exceeded: {used_mb:.1f} MB used of {quota_mb} MB limit')
