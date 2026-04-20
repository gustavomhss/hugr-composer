from __future__ import annotations
from uuid import UUID


async def check_rate_limit(key_id: UUID, *, limit: int | None=None) -> bool:
    """Return True if the key is under its rate limit, False if exceeded.

    Tries Redis first; falls back to an in-process counter when Redis is
    unavailable.  The fallback is per-worker and best-effort.

    Args:
        key_id: The UUID primary key of the APIKey record.
        limit: Requests-per-minute cap.  Uses ``_DEFAULT_LIMIT`` when None.

    Returns:
        ``True`` if the request may proceed, ``False`` if rate-limited.
    """
    effective_limit = limit if limit is not None else _DEFAULT_LIMIT
    redis = await _get_redis_or_none()
    if redis is not None:
        return await _check_redis(redis, key_id, effective_limit)
    return _check_in_process(key_id, effective_limit)
