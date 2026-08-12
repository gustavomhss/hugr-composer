"""Protocol for ValueObject — generated from ValueObject.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Mapping

@runtime_checkable
class ValueObject(Protocol):
    """ValueObject primitive — immutable, equality-by-value, frozen-dataclass-backed."""

    def with_changes(self) -> ValueObject: ...
