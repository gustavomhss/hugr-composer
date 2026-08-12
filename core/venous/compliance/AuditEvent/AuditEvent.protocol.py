"""Protocol for AuditEvent — generated from AuditEvent.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable

@runtime_checkable
class AuditEventSink(Protocol):
    """Catalog-defined sink Protocol (verbatim)."""

    def emit(self, event: AuditEvent) -> None: ...
    def verify_chain(self, from_event_id: str | None) -> bool: ...
