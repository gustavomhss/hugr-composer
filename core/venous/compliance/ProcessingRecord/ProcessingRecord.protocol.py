"""Protocol for ProcessingRecord — generated from ProcessingRecord.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class RetentionResolver(Protocol):
    """Resolves retention_ref → RetentionPolicy (duck-typed)."""

    def has(self, retention_ref: str) -> bool: ...

@runtime_checkable
class ProcessingRegistry(Protocol):
    """Catalog-defined Protocol."""

    def register(self, record: ProcessingRecord) -> None: ...
    def export_ropa(self) -> bytes: ...
