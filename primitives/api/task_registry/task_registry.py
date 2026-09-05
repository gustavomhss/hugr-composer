"""Pure Python primitive: TaskRegistry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class TaskRegistry:
    """Thread-safe registry mapping task_type strings to async handlers.

    Attributes:
        _handlers: Mapping from task_type to async callable.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

    def register(self, task_type: str) -> Callable:
        """Decorator that registers an async handler under *task_type*.

        Args:
            task_type: Unique task type identifier string.

        Returns:
            The original handler function, unmodified.

        Raises:
            ValueError: If *task_type* is already registered.
            TypeError: If the decorated function is not a coroutine function.
        """

        def decorator(func: Callable) -> Callable:
            """Register the decorated coroutine under *task_type*.

            Args:
                func: Async handler to register.

            Returns:
                The original function, unmodified.

            Raises:
                ValueError: If *task_type* is already registered.
                TypeError: If *func* is not a coroutine function.
            """
            if task_type in self._handlers:
                raise ValueError(f"Task type '{task_type}' is already registered.")
            if not inspect.iscoroutinefunction(func):
                raise TypeError(f"Task handler '{func.__name__}' must be an async function.")
            self._handlers[task_type] = func
            return func
        return decorator

    def get(self, task_type: str) -> Callable[..., Awaitable[Any]]:
        """Return the registered handler for *task_type*.

        Args:
            task_type: Task type identifier.

        Returns:
            Registered async callable.

        Raises:
            KeyError: If *task_type* is not registered.
        """
        if task_type not in self._handlers:
            raise KeyError(f"Unknown task type: '{task_type}'. Registered: {sorted(self._handlers.keys())}")
        return self._handlers[task_type]

    def registered_types(self) -> list[str]:
        """Return all registered task type strings.

        Returns:
            Sorted list of registered type identifiers.
        """
        return sorted(self._handlers.keys())
