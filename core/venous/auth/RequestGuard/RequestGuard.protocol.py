"""Protocol for RequestGuard — generated from RequestGuard.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Awaitable

@runtime_checkable
class RequestGuard(Protocol):
    """Predicate invoked before a handler to allow or deny a request."""

    async def allow(self, ctx: _RequestContextLike, principal: _PrincipalLike) -> bool: ...

@runtime_checkable
class HandlerFn(Protocol):
    """RequestGuard primitive — allow/deny predicate that short-circuits the pipeline."""

    ...
