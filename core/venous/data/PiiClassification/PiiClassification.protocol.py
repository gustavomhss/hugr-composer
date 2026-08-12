"""Protocol for PiiClassification — generated from PiiClassification.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """PiiClassification primitive — schema-level PII/PHI/PCI tagging + central mask."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class PiiClassification(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def classify(self, model: type, field: str) -> PiiClass: ...
    def mask(self, obj: Any, audience: str) -> Mapping[str, Any]: ...
    def audit_leak(self, obj: Any, sink: str) -> None: ...
