"""Protocol for RequestContext — generated from RequestContext.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterator, Mapping

@runtime_checkable
class RequestContext(Protocol):
    """The catalog-declared request-context surface."""

    def put(self, key: str, value: Any) -> RequestContext: ...
    def halt(self) -> RequestContext: ...

@runtime_checkable
class RequestContextProvider(Protocol):
    """Extension point for framework adapters that build a RequestContext."""

    def bind(self) -> RequestContext: ...
