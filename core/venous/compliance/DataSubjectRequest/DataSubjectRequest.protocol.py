"""Protocol for DataSubjectRequest — generated from DataSubjectRequest.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class AuditSink(Protocol):
    """DataSubjectRequest primitive — GDPR access/erasure lifecycle coordinator."""

    def append(self, actor: str, action: str, resource: str, outcome: str, attributes: Mapping[str, object]) -> str: ...

@runtime_checkable
class DataSubjectRequest(Protocol):
    """Catalog-defined Protocol (verbatim)."""

    def open(self, subject_id: str, kind: DsrKind, received_at: datetime) -> str: ...
    def attach_artifact(self, request_id: str, store: str, manifest: bytes) -> None: ...
    def close(self, request_id: str, outcome: str) -> None: ...
    def due_at(self, request_id: str) -> datetime: ...
