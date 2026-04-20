from __future__ import annotations
from contextlib import asynccontextmanager
import uuid


@asynccontextmanager
async def quota_lock(user_id: uuid.UUID):
    """Async context manager: acquire a Redis advisory lock for ``user_id``.

    Args:
        user_id: UUID of the uploading user.

    Raises:
        HTTPException: 429 if another upload is already in progress for this user.

    Yields:
        Nothing — the lock is released on exit regardless of outcome.
    """
    from fastapi import HTTPException
    redis = await _get_redis()
    lock_key = f'quota_lock:{user_id}'
    acquired = False
    try:
        acquired = bool(await redis.set(lock_key, '1', nx=True, ex=QUOTA_LOCK_TTL_SECONDS))
        if not acquired:
            raise HTTPException(status_code=429, detail='Upload in progress for this user. Retry shortly.')
        yield
    finally:
        if acquired:
            await redis.delete(lock_key)
        await redis.aclose()
