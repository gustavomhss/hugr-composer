from __future__ import annotations
from typing import Any


class QueryBus:
    """Dispatch Queries to their registered async handlers."""

    def __init__(self) -> None:
        """Initialise with an empty handler registry."""
        self._registry: dict[str, Handler] = {}

    def register(self, query_name: str, handler: Handler) -> None:
        """Register *handler* for *query_name*.

        Args:
            query_name: Fully-qualified query class name (e.g. ``'GetItem'``).
            handler: Async callable that accepts the query and returns a result.
        """
        self._registry[query_name] = handler

    async def query(self, q: object, **kwargs: Any) -> Any:
        """Dispatch *q* to its registered handler.

        Args:
            q: A Query instance — its class name is used as lookup key.
            **kwargs: Extra keyword arguments forwarded to the handler.

        Returns:
            Whatever the handler returns.

        Raises:
            KeyError: When no handler is registered for the query type.
        """
        name = type(q).__name__
        handler = self._registry.get(name)
        if handler is None:
            raise KeyError(f'No handler registered for query: {name!r}')
        logger.debug('QueryBus dispatching %r', name)
        return await handler(q, **kwargs)
