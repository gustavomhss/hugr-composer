from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def get_pending(session: AsyncSession, file_id: uuid.UUID, owner_id: uuid.UUID | None=None) -> FileMetadata | None:
    """Fetch a pending FileMetadata row, optionally scoped to an owner.

    Args:
        session: Async SQLAlchemy session.
        file_id: UUID to look up.
        owner_id: If provided, must match ``uploaded_by``.

    Returns:
        FileMetadata instance or ``None``.
    """
    stmt = select(FileMetadata).where(FileMetadata.id == file_id, FileMetadata.status == 'pending')
    if owner_id is not None:
        stmt = stmt.where(FileMetadata.uploaded_by == owner_id)
    return (await session.execute(stmt)).scalar_one_or_none()
