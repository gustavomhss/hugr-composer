# ruff: noqa: N999 — module name `QueryBus` mirrors the primitive's PascalCase
# directory name (`core/venous/api/QueryBus/`); intentional, not a typo.
"""Formal port (hand-authored) for the ``QueryBus`` primitive.

WP-15 exemplar #2. Supersedes the auto-inferred stub at
``core/venous/api/QueryBus/QueryBus.protocol.py`` as the source of truth.
The auto-inferred stub stays in place as catalog-derivation evidence;
the compat shim in ``core/venous/api/QueryBus/__init__.py`` re-exports
:class:`QueryBusProtocol` from this module so legacy import paths
continue to resolve.

Signatures here are **verbatim** from the auto-inferred stub — per
WP-15 §9 F-03, tightening the surface is out of scope for phase 1.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

#: Async callable handler signature; identical shape to
#: :data:`core.venous._ports.api.CommandBus.Handler` by design — bus-style
#: ports share this consumed surface.
Handler = Callable[..., Awaitable[Any]]


@runtime_checkable
class QueryBusProtocol(Protocol):
    """Hexagonal port for query-dispatch buses.

    Adapters implementing this port satisfy ``isinstance(impl,
    QueryBusProtocol)`` at runtime.

    Methods mirror the auto-inferred stub at
    ``core/venous/api/QueryBus/QueryBus.protocol.py``:

    * :meth:`register` — bind a handler to a query name.
    * :meth:`query` — async-invoke the handler registered for the
      incoming query's class name.

    Read-only semantics are a caller contract (QB_INV_04), not enforced
    by the port surface.
    """

    def register(self, query_name: str, handler: Handler) -> None: ...

    async def query(self, q: object, **kwargs: Any) -> Any: ...
