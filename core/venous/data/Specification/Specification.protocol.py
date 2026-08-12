"""Protocol for Specification — generated from Specification.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class Specification(Protocol):
    """Specification primitive — Evans/Fowler DDD composable predicate pattern."""

    def is_satisfied_by(self, candidate: T) -> bool: ...
    def and_(self, other: Specification[T]) -> Specification[T]: ...
    def or_(self, other: Specification[T]) -> Specification[T]: ...
    def not_(self) -> Specification[T]: ...
