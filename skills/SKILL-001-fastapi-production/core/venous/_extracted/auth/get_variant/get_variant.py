from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio


async def get_variant(session: AsyncSession, key: str, context: FlagContext, default: str='control') -> str:
    """Evaluate a multi-variant flag. Never raises; returns *default* on error.

    Args:
        session: Async SQLAlchemy session for DB fallback.
        key: Flag key string.
        context: Evaluation context (user, tenant, environment).
        default: Variant name returned when flag is missing or evaluation fails.

    Returns:
        Variant name string (e.g. 'A', 'B', 'control').
    """
    try:
        return await asyncio.wait_for(_evaluate_variant(session, key, context, default), timeout=EVAL_TIMEOUT_S)
    except Exception as exc:
        logger.warning('flag.variant_failed key=%s err=%r default=%s', key, exc, default)
        return default
