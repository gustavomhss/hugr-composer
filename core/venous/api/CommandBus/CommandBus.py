from __future__ import annotations
from typing import Any


class CommandBus:
    """Dispatch Commands to their registered async handlers."""

    def __init__(self) -> None:
        """Initialise with an empty handler registry."""
        self._registry: dict[str, Handler] = {}

    def register(self, command_name: str, handler: Handler) -> None:
        """Register *handler* for *command_name*.

        Args:
            command_name: Fully-qualified command class name (e.g. ``'CreateItem'``).
            handler: Async callable that accepts the command and returns a result.
        """
        self._registry[command_name] = handler

    async def dispatch(self, command: object, **kwargs: Any) -> Any:
        """Dispatch *command* to its registered handler.

        Args:
            command: A Command instance — its class name is used as lookup key.
            **kwargs: Extra keyword arguments forwarded to the handler.

        Returns:
            Whatever the handler returns.

        Raises:
            KeyError: When no handler is registered for the command type.
        """
        name = type(command).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f'No handler registered for command: {name!r}')
        logger.debug('CommandBus dispatching %r', name)
        return await handler(command, **kwargs)
