"""Protocol for ConsentLedger — generated from ConsentLedger.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class ConsentLedger(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def grant(self, subject_id: str, purpose: str, notice_version: str, at: datetime) -> str: ...
    def revoke(self, subject_id: str, purpose: str, at: datetime) -> None: ...
    def is_granted(self, subject_id: str, purpose: str, at: datetime | None) -> bool: ...
    def history(self, subject_id: str) -> list[dict[str, object]]: ...
