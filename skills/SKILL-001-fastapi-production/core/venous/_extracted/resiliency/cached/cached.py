from __future__ import annotations
from collections.abc import Callable
from typing import Any
import asyncio
import functools


def cached(ttl: int=300, key_pattern: str | None=None, vary_on: list[str] | None=None) -> Callable:
    """Decorator that caches GET handler return values with anti-stampede."""

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get('request')
            if _should_skip_cache(request):
                return await func(*args, **kwargs)
            cache = get_cache()
            if cache is None:
                return await func(*args, **kwargs)
            key = build_key(func, key_pattern, vary_on, kwargs)
            cached_value = await cache.get(key)
            if cached_value is not None:
                return cached_value
            lock_acquired = await _acquire_stampede_lock(cache, key)
            if not lock_acquired:
                await asyncio.sleep(_STAMPEDE_RETRY_DELAY)
                cached_value = await cache.get(key)
                if cached_value is not None:
                    return cached_value
            try:
                result = await func(*args, **kwargs)
                if result is not None:
                    await cache.set(key, result, ttl=ttl)
                return result
            finally:
                if lock_acquired:
                    await _release_stampede_lock(cache, key)
        return wrapper
    return decorator
