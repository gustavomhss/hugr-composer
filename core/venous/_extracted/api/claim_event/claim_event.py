from __future__ import annotations


async def claim_event(provider: str, event_id: str) -> bool:
    """Attempt to claim an inbound event id.

    Uses Redis ``SET NX EX`` for atomic first-write-wins semantics.
    The key expires after ``_TTL`` seconds so long-lived processes do
    not accumulate unbounded Redis memory.

    Args:
        provider: Provider name (used as part of the Redis key).
        event_id: Provider-assigned event identifier.

    Returns:
        ``True`` if this is the first time the event id has been seen
        (the claim was granted).  ``False`` if it is a duplicate.
    """
    redis = await get_redis()
    key = f'inbound:webhook:{provider}:{event_id}'
    return bool(await redis.set(key, '1', nx=True, ex=_TTL))
