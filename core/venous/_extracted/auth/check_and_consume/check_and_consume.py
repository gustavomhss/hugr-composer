from __future__ import annotations
from uuid import UUID
import time


async def check_and_consume(user_id: UUID | str, *, _limit: int | None=None) -> bool:
    """Increment the attempt counter for *user_id* and check the limit.

    Uses a fixed 15-minute bucket keyed by ``mfa:attempts:{user_id}:{bucket}``.
    The bucket ID is ``floor(unix_time / WINDOW)`` so it rotates every 15 min.

    Args:
        user_id: The user whose attempt counter to check/increment.
        _limit: Override the configured limit (for tests).

    Returns:
        ``True`` if the attempt is within the rate limit, ``False`` if exceeded.
    """
    from app.core.redis import get_redis
    limit = _limit if _limit is not None else _LIMIT
    redis = await get_redis()
    bucket = int(time.time() // _WINDOW)
    key = f'mfa:attempts:{user_id}:{bucket}'
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, _WINDOW * 2)
    count, _ = await pipe.execute()
    return int(count) <= limit
