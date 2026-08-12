"""Protocol for IdentityMap — generated from IdentityMap.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterator

@runtime_checkable
class IdentityMap(Protocol):
    """IdentityMap primitive — Fowler PEAA session-scoped aggregate identity cache."""

    def get(self, type_: type, id: object) -> Any | None: ...
    def add(self, obj: Any) -> None: ...
    def remove(self, type_: type, id: object) -> None: ...
    def contains(self, type_: type, id: object) -> bool: ...
