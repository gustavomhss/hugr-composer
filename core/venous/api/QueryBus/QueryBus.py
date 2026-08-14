"""QueryBus — dispatch Queries to registered async handlers.

Invariants cited here:

- QB_INV_01 — register-then-query: after `register(name, h)`, a query
  whose class name matches ``name`` invokes ``h`` (and only ``h``)
  with the query + any forwarded kwargs.
- QB_INV_02 — last-registrant-wins: re-registering the same query
  name replaces the prior handler.
- QB_INV_03 — unknown-name rejection: querying with no registered
  handler raises ``KeyError`` carrying the class name.
- QB_INV_04 — read-only semantics: handlers are expected to perform
  side-effect-free reads. The bus does not enforce this at the
  transport layer; it's a contract callers honour.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[..., Awaitable[Any]]

_logger = logging.getLogger(__name__)


class QueryBus:
    """Dispatch Queries to their registered async handlers."""

    __slots__ = ("_registry",)

    def __init__(self) -> None:
        self._registry: dict[str, Handler] = {}

    def register(self, query_name: str, handler: Handler) -> None:
        """Register *handler* for *query_name*."""
        self._registry[query_name] = handler

    async def query(self, q: object, **kwargs: Any) -> Any:
        """Dispatch *q* to its registered handler.

        Raises:
            KeyError: When no handler is registered for the query type.
        """
        name = type(q).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f"No handler registered for query: {name!r}")
        _logger.debug("QueryBus dispatching %r", name)
        return await handler(q, **kwargs)


__all__ = ["Handler", "QueryBus"]
