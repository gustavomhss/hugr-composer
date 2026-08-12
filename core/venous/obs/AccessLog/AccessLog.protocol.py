"""Protocol for AccessLog — generated from AccessLog.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class AccessLog(Protocol):
    """Catalog-defined Protocol."""

    def record_read(self, actor: str, record_id: str, data_class: str, purpose_of_use: str, at: datetime) -> None: ...
    def query(self, record_id: str | None, actor: str | None) -> list[dict[str, object]]: ...
    def count_by_actor(self, actor: str, since: datetime) -> int: ...
