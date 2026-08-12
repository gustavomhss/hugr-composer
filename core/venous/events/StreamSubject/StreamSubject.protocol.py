"""Protocol for StreamSubject — generated from StreamSubject.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class StreamSubjectProtocol(Protocol):
    """A fully-specified publishable subject name."""

    def matches(self, pattern: str) -> bool: ...

@runtime_checkable
class SubjectRegistryProtocol(Protocol):
    """Stateful registry of subscribers keyed by pattern."""

    def subscribe(self, pattern: str, subscriber_id: str) -> None: ...
    def unsubscribe(self, pattern: str, subscriber_id: str) -> None: ...
    def publish(self, subject: StreamSubject) -> int: ...
    def deliveries(self) -> list[tuple[str, str, int]]: ...
