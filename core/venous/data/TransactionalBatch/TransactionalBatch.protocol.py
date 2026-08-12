"""Protocol for TransactionalBatch — generated from TransactionalBatch.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class StateStore(Protocol):
    """TransactionalBatch primitive — atomic multi-key upsert/delete unit."""

    def get_with_etag(self, key: str) -> tuple[bytes | None, str | None]: ...
    def apply_transaction(self, ops: list[_Op]) -> None: ...

@runtime_checkable
class TransactionalBatch(Protocol):
    """TransactionalBatch primitive — atomic multi-key upsert/delete unit."""

    def upsert(self, key: str, value: bytes, etag: str | None) -> TransactionalBatch: ...
    def delete(self, key: str, etag: str | None) -> TransactionalBatch: ...
    async def commit(self) -> None: ...
