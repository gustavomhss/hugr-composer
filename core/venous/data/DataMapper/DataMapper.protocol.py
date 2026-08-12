"""Protocol for DataMapper — generated from DataMapper.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class DataMapper(Protocol):
    """DataMapper primitive — Fowler PEAA bidirectional domain ↔ row translator."""

    def load(self, row: dict[str, Any]) -> T: ...
    def insert(self, entity: T) -> dict[str, Any]: ...
    def update(self, entity: T) -> dict[str, Any]: ...
    def delete(self, entity: T) -> dict[str, Any]: ...

@runtime_checkable
class StorageAdapter(Protocol):
    """Encodes/decodes one column value for a specific storage backend."""

    def encode(self, value: Any) -> Any: ...
    def decode(self, value: Any) -> Any: ...
