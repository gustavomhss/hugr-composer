"""CommandBus — dispatch Commands to registered async handlers.

Invariants cited here:

- CB_INV_01 — register-then-dispatch: after `register(name, h)`, a
  dispatched command whose class name matches ``name`` invokes ``h``
  (and only ``h``) with the command + any forwarded kwargs.
- CB_INV_02 — last-registrant-wins: re-registering the same command
  name replaces the prior handler; there is no chain or broadcast.
- CB_INV_03 — unknown-name rejection: dispatching a command with no
  registered handler raises ``KeyError`` carrying the class name —
  silent-no-op is a correctness bug (commands must either run or
  fail loud).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

# Async callable handler signature. Using a broad Callable keeps the
# primitive framework-free — callers pass any async function.
Handler = Callable[..., Awaitable[Any]]

_logger = logging.getLogger(__name__)


class CommandBus:
    """Dispatch Commands to their registered async handlers."""

    __slots__ = ("_registry",)

    def __init__(self) -> None:
        self._registry: dict[str, Handler] = {}

    def register(self, command_name: str, handler: Handler) -> None:
        """Register *handler* for *command_name*.

        Args:
            command_name: Fully-qualified command class name
                (e.g. ``'CreateItem'``).
            handler: Async callable that accepts the command and
                returns a result.
        """
        self._registry[command_name] = handler

    async def dispatch(self, command: object, **kwargs: Any) -> Any:
        """Dispatch *command* to its registered handler.

        Args:
            command: A Command instance — its class name is used as
                lookup key.
            **kwargs: Extra keyword arguments forwarded to the handler.

        Returns:
            Whatever the handler returns.

        Raises:
            KeyError: When no handler is registered for the command type.
        """
        name = type(command).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f"No handler registered for command: {name!r}")
        _logger.debug("CommandBus dispatching %r", name)
        return await handler(command, **kwargs)


__all__ = ["CommandBus", "Handler"]
