from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def create_social_account(session: AsyncSession, provider: str, provider_user_id: str, provider_email: str | None, user_id: uuid.UUID) -> SocialAccount:
    """Insert a new SocialAccount row and flush.

    Args:
        session: Active async database session.
        provider: Provider name string.
        provider_user_id: Provider's stable user identifier.
        provider_email: Email address from the provider (may be None).
        user_id: UUID of the user to link to.

    Returns:
        The newly created ``SocialAccount`` instance.
    """
    account = SocialAccount(provider=provider, provider_user_id=provider_user_id, provider_email=provider_email, user_id=user_id)
    session.add(account)
    await session.flush()
    return account
