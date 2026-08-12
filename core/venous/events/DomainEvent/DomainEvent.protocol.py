"""Protocol for DomainEvent — generated from DomainEvent.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class DomainEvent(Protocol):
    """DomainEvent primitive — Evans/Vernon/Richardson immutable domain fact."""

    def event_id(self) -> str: ...
    def aggregate_id(self) -> str: ...
    def occurred_at(self) -> str: ...
    def version(self) -> int: ...
    def payload(self) -> Mapping[str, Any]: ...

@runtime_checkable
class PublishFn(Protocol):
    """DomainEvent primitive — Evans/Vernon/Richardson immutable domain fact."""

    ...
