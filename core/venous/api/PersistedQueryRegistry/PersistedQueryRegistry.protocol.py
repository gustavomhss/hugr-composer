"""PersistedQueryRegistry — Protocol-only declaration."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PersistedQueryRegistry(Protocol):
    def register(self, query: str) -> str: ...
    def get(self, id: str) -> str | None: ...
    def contains(self, id: str) -> bool: ...
