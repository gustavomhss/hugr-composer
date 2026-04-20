from __future__ import annotations
from collections.abc import Callable
from typing import Any
import functools


def sensitive(level: str='pii') -> Callable[[Any], Any]:
    """Mark a route function with a DLP sensitivity level.

    The ``DLPMiddleware`` reads this attribute to apply stricter redaction
    for elevated sensitivity levels (e.g. ``'pci'`` forces ``full`` mode).

    Args:
        level: Sensitivity level string — ``'pii'``, ``'phi'``, ``'pci'``,
            or ``'custom'``.

    Returns:
        Decorator that attaches ``_dlp_sensitivity_level`` to the function.
    """

    def decorator(func: Any) -> Any:
        """Attach the DLP sensitivity level to *func*.

        Args:
            func: The route handler to decorate.

        Returns:
            The same *func* with ``_dlp_sensitivity_level`` attribute set.
        """

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Async wrapper preserving the sensitivity attribute.

            Args:
                *args: Positional arguments forwarded to *func*.
                **kwargs: Keyword arguments forwarded to *func*.

            Returns:
                Result of *func*.
            """
            return await func(*args, **kwargs)
        setattr(wrapper, _SENSITIVITY_ATTR, level)
        return wrapper
    return decorator
