"""Protocol for RetentionPolicy — generated from RetentionPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable, Mapping

@runtime_checkable
class HoldCheck(Protocol):
    """LegalHold interception hook (duck-typed to avoid circular imports)."""

    def covers(self, record_id: str) -> bool: ...

@runtime_checkable
class AuditSink(Protocol):
    """Emits one TamperEvidentAuditLog entry per purge; decoupled from the log impl."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class RetentionEnforcer(Protocol):
    """Catalog-defined Protocol."""

    def bind(self, policy: RetentionPolicy) -> None: ...
    def enforce_on_write(self, data_class: str, record_id: str) -> None: ...
    def sweep(self) -> int: ...
