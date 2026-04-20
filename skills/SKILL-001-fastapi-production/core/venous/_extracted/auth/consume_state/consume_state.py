from __future__ import annotations
import json


async def consume_state(redis, state: str) -> OAuthState | None:
    """Atomically read and delete a state token (single-use guarantee).

    Uses a Redis pipeline for GET + DEL so the token cannot be replayed
    even under concurrent requests.

    Args:
        redis: Async Redis client.
        state: CSRF state string from the callback query parameter.

    Returns:
        ``OAuthState`` if found and consumed, ``None`` if missing or expired.
    """
    key = f'oauth:state:{state}'
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    if raw is None:
        return None
    return OAuthState(**json.loads(raw))
