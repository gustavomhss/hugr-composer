from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def find_social_account(session: AsyncSession, provider: str, provider_user_id: str) -> SocialAccount | None:
    """Return an existing SocialAccount row or None.

    Args:
        session: Active async database session.
        provider: Provider name string.
        provider_user_id: Provider's stable user identifier.

    Returns:
        ``SocialAccount`` row if found, else ``None``.
    """
    stmt = select(SocialAccount).where(SocialAccount.provider == provider, SocialAccount.provider_user_id == provider_user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
