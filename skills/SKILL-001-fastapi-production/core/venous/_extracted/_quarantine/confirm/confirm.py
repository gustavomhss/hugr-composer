from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def confirm(session: AsyncSession, *, file_id: uuid.UUID, size_bytes: int, confirmed_at: datetime) -> FileMetadata | None:
    """Transition a pending file to confirmed status.

    Args:
        session: Async SQLAlchemy session.
        file_id: UUID of the pending file to confirm.
        size_bytes: Actual size confirmed from storage (e.g. S3 HEAD).
        confirmed_at: UTC timestamp of confirmation.

    Returns:
        Updated FileMetadata instance, or ``None`` if not found.
    """
    stmt = select(FileMetadata).where(FileMetadata.id == file_id, FileMetadata.status == 'pending')
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.status = 'confirmed'
    row.size_bytes = size_bytes
    row.confirmed_at = confirmed_at
    await session.flush()
    return row
