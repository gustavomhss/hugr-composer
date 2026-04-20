from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def create_user_for_social(session: AsyncSession, email: str | None, name: str | None) -> uuid.UUID:
    """Create a minimal user row for a social-only account.

    Args:
        session: Active async database session.
        email: Email from the provider (may be None for Apple).
        name: Display name from the provider (may be None).

    Returns:
        UUID of the newly created user.
    """
    from sqlalchemy import text
    new_id = uuid.uuid4()
    await session.execute(text("INSERT INTO users (id, email, full_name, hashed_password, is_active) VALUES (:id, :email, :name, '', true)"), {'id': str(new_id), 'email': email or '', 'name': name or ''})
    await session.flush()
    return new_id
