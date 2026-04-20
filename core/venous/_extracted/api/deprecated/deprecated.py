from __future__ import annotations
from collections.abc import Callable
from typing import Any
import functools


def deprecated(sunset: str, replacement: str, method: str='GET', description: str='') -> Callable[[Any], Any]:
    """Decorator to mark a route handler as deprecated.

    Registers the endpoint in the module-level registry so
    DeprecationMiddleware can add response headers automatically.

    Args:
        sunset: ISO date string when the endpoint will be removed.
        replacement: URL of the replacement endpoint.
        method: HTTP method (default 'GET').
        description: Optional human-readable deprecation reason.

    Returns:
        Decorator that wraps the route handler unchanged.

    Example::

        @router.get("/items")
        @deprecated(sunset="2026-06-01", replacement="/api/v2/items")
        async def list_items():
            ...
    """

    def decorator(func: Any) -> Any:
        path = getattr(func, '__route_path__', f'/{func.__name__}')
        registry.register(path, method, sunset, replacement, description)
        func.__deprecated__ = True
        func.__sunset__ = sunset
        func.__replacement__ = replacement

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)
        wrapper.__deprecated__ = True
        wrapper.__sunset__ = sunset
        wrapper.__replacement__ = replacement
        return wrapper
    return decorator
