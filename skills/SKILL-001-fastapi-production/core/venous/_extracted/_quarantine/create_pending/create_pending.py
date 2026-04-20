from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def create_pending(session: AsyncSession, *, id: uuid.UUID, original_filename: str, stored_key: str, content_type: str, size_bytes: int, uploaded_by: uuid.UUID | None=None, resource_type: str | None=None, resource_id: uuid.UUID | None=None) -> FileMetadata:
    """Insert a pending FileMetadata row before the upload completes.

    Args:
        session: Async SQLAlchemy session.
        id: Pre-generated UUID for the file.
        original_filename: Original client filename (display only).
        stored_key: UUID-based storage key.
        content_type: MIME type detected from magic bytes.
        size_bytes: Declared size (confirmed later via HEAD).
        uploaded_by: UUID of the uploading user.
        resource_type: Optional polymorphic resource type.
        resource_id: Optional polymorphic resource ID.

    Returns:
        The inserted FileMetadata ORM instance.
    """
    row = FileMetadata(id=id, original_filename=original_filename, stored_key=stored_key, content_type=content_type, size_bytes=size_bytes, status='pending', uploaded_by=uploaded_by, resource_type=resource_type, resource_id=resource_id)
    session.add(row)
    await session.flush()
    return row
