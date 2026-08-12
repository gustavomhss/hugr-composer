"""Protocol for DiContainer — generated from DiContainer.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable

@runtime_checkable
class DiContainer(Protocol):
    """DiContainer primitive — typed dependency registry with lifetime scoping."""

    def register(self, iface: type[T], impl: type[T] | Callable[..., T]) -> None: ...
    def resolve(self, iface: type[T]) -> T: ...
    def create_scope(self) -> DiContainer: ...
