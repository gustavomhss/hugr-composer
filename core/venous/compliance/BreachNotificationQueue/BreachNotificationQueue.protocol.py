"""Protocol for BreachNotificationQueue — generated from BreachNotificationQueue.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """BreachNotificationQueue primitive — GDPR Art 33 72-hour clock."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class BreachNotificationQueue(Protocol):
    """Catalog-defined Protocol."""

    def open_incident(self, detected_at: datetime, severity: Severity, summary: str) -> str: ...
    def confirm(self, incident_id: str, confirmed_at: datetime, data_classes: tuple[str, ...]) -> None: ...
    def notify_authority(self, incident_id: str, authority: str, at: datetime, reference: str) -> None: ...
    def close(self, incident_id: str, outcome: str) -> None: ...
