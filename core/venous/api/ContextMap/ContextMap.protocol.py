"""Protocol for ContextMap — generated from ContextMap.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class ContextMap(Protocol):
    """ContextMap primitive — catalog of BoundedContexts and their relationships."""

    def contexts(self) -> Iterable[str]: ...
    def relationship(self, upstream: str, downstream: str) -> str: ...
    def add_relationship(self, upstream: str, downstream: str, kind: str) -> None: ...
    def integrations(self) -> Iterable[tuple[str, str, str]]: ...
