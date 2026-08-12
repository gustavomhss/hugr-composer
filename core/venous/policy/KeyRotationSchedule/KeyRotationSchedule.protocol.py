"""Protocol for KeyRotationSchedule — generated from KeyRotationSchedule.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """KeyRotationSchedule primitive — scheduled key rotation with overlap window."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class KeyRotator(Protocol):
    """Catalog-defined Protocol."""

    def schedule(self, sched: KeyRotationSchedule) -> None: ...
    def rotate_now(self, key_alias: str) -> str: ...
    def active_key(self, key_alias: str, at: datetime) -> str: ...
