"""Protocol for RequestShape — generated from RequestShape.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class RequestShape(Protocol):
    """RequestShape primitive — immutable resiliency context propagated across hops."""

    def to_headers(self) -> dict[str, str]: ...
    def from_headers(self, headers: dict[str, str]) -> RequestShape: ...
