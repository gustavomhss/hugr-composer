from __future__ import annotations
from dataclasses import asdict
import json


async def store_state(redis, state_obj: OAuthState) -> bool:
    """Store a state object in Redis using SET NX EX (write-once).

    Uses NX to prevent a second write with the same state key.
    This should never collide in practice (32-byte random state) but
    the guard makes the invariant explicit.

    Args:
        redis: Async Redis client.
        state_obj: State to persist.

    Returns:
        ``True`` if stored successfully, ``False`` if key already existed.
    """
    key = f'oauth:state:{state_obj.state}'
    result = await redis.set(key, json.dumps(asdict(state_obj)), nx=True, ex=_STATE_TTL)
    return result is not None
