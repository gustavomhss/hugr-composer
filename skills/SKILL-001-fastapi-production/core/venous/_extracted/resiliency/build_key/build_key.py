from __future__ import annotations
from collections.abc import Callable


def build_key(func: Callable, key_pattern: str | None, vary_on: list[str] | None, kwargs: dict) -> str:
    """Build a namespaced cache key.

    Pattern: ``cache:{tenant}:{func_module}.{func_name}[:{formatted_pattern}]``

    Args:
        func: The decorated function (used for module + name).
        key_pattern: Optional format string (e.g. ``"items:{item_id}"``).
        vary_on: List of kwarg names to append to the key.
        kwargs: The function's keyword arguments at call time.

    Returns:
        String cache key.
    """
    tenant = get_tenant()
    base = f'cache:{tenant}:{func.__module__}.{func.__name__}'
    if key_pattern:
        try:
            return f'{base}:{key_pattern.format(**kwargs)}'
        except KeyError:
            logger.warning('Cache key pattern formatting failed: %s', key_pattern)
    if vary_on:
        parts = [f'{k}:{kwargs.get(k)}' for k in vary_on if k in kwargs]
        return f"{base}:{'|'.join(parts)}"
    return base
