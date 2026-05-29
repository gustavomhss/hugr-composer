# ruff: noqa: N999 — module name `CommandBus` mirrors the primitive's PascalCase
# directory name (`core/venous/api/CommandBus/`); intentional, not a typo.
"""Formal port (hand-authored) for the ``CommandBus`` primitive.

WP-15 exemplar #1. Supersedes the auto-inferred stub at
``core/venous/api/CommandBus/CommandBus.protocol.py`` as the source of
truth for the protocol surface. The auto-inferred stub stays in place as
catalog-derivation evidence; the compat shim in
``core/venous/api/CommandBus/__init__.py`` re-exports
:class:`CommandBusProtocol` from this module so legacy import paths
continue to resolve.

Signatures here are **verbatim** from the auto-inferred stub — per
WP-15 §9 F-03, tightening the surface is out of scope for phase 1 and
requires a separate tech-lead decision.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

#: Async callable handler signature. A broad ``Callable`` keeps the port
#: framework-free — adapters pass any async function.
Handler = Callable[..., Awaitable[Any]]


@runtime_checkable
class CommandBusProtocol(Protocol):
    """Hexagonal port for command-dispatch buses.

    Adapters implementing this port satisfy ``isinstance(impl,
    CommandBusProtocol)`` at runtime (the Protocol is decorated
    ``@runtime_checkable``).

    Methods mirror the auto-inferred stub at
    ``core/venous/api/CommandBus/CommandBus.protocol.py``:

    * :meth:`register` — bind a handler to a command name.
    * :meth:`dispatch` — async-invoke the handler registered for the
      incoming command's class name.
    """

    def register(self, command_name: str, handler: Handler) -> None: ...

    async def dispatch(self, command: object, **kwargs: Any) -> Any: ...
