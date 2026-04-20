from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio


async def is_enabled(session: AsyncSession, key: str, context: FlagContext, default: bool=False) -> bool:
    """Evaluate a boolean feature flag. Never raises; returns *default* on error.

    Args:
        session: Async SQLAlchemy session for DB fallback.
        key: Flag key string.
        context: Evaluation context (user, tenant, environment).
        default: Value returned when flag is missing or evaluation fails.

    Returns:
        True if the flag is enabled for this context, False otherwise.
    """
    try:
        return await asyncio.wait_for(_evaluate_boolean(session, key, context, default), timeout=EVAL_TIMEOUT_S)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning('flag.eval_failed key=%s err=%r default=%s', key, exc, default)
        return default
