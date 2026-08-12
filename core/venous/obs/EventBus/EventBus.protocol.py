"""Protocol for EventBus — generated from EventBus.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Mapping

@runtime_checkable
class EventBus(Protocol):
    """EventBus primitive — in-process named event publish/subscribe facade."""

    def publish(self, name: str, payload: Mapping[str, Any]) -> None: ...
    def subscribe(self, pattern: str, handler: Subscriber) -> Callable[[], None]: ...
