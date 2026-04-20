from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get(session: AsyncSession, *, provider: str, provider_user_id: str) -> OAuthAccount | None:
    """Look up a linked OAuth account by provider and provider user ID.

    Args:
        session: Async SQLAlchemy session.
        provider: Provider name (google | github | facebook | microsoft).
        provider_user_id: Stable ID from the provider's userinfo endpoint.

    Returns:
        Matching ``OAuthAccount``, or ``None`` if not found.
    """
    stmt = select(OAuthAccount).where(OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id)
    return (await session.execute(stmt)).scalar_one_or_none()
