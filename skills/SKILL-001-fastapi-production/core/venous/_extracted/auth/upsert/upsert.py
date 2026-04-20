from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def upsert(session: AsyncSession, *, provider: str, provider_user_id: str, provider_email: str | None, user_id: uuid.UUID, tokens: OAuthTokens) -> OAuthAccount:
    """Create or update an OAuthAccount, storing freshly encrypted tokens.

    If a record with (provider, provider_user_id) already exists its tokens
    and email are updated in-place.  Otherwise a new record is created.
    Provider tokens are ALWAYS encrypted before storage.

    Args:
        session: Async SQLAlchemy session.
        provider: Provider name.
        provider_user_id: Stable provider user identifier.
        provider_email: Email reported by provider at this login.
        user_id: Application user UUID to link to.
        tokens: Fresh ``OAuthTokens`` from the token exchange.

    Returns:
        The created or updated ``OAuthAccount`` ORM instance.
    """
    existing = await get(session, provider=provider, provider_user_id=provider_user_id)
    if existing is not None:
        existing.access_token_enc = encrypt_token(tokens.access_token)
        existing.refresh_token_enc = encrypt_token(tokens.refresh_token)
        existing.provider_email = provider_email
        await session.flush()
        return existing
    new_account = OAuthAccount(provider=provider, provider_user_id=provider_user_id, provider_email=provider_email, user_id=user_id, access_token_enc=encrypt_token(tokens.access_token), refresh_token_enc=encrypt_token(tokens.refresh_token))
    session.add(new_account)
    await session.flush()
    return new_account
