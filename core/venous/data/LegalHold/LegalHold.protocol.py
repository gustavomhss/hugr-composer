"""Protocol for LegalHold — generated from LegalHold.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """LegalHold primitive — suspends retention + erasure for recorded scopes."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class LegalHoldRegistry(Protocol):
    """Catalog-defined Protocol."""

    def open(self, hold: LegalHold) -> None: ...
    def release(self, hold_id: str, released_by: str) -> None: ...
    def covers(self, record_id: str) -> bool: ...
