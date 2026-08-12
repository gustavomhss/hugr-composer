"""Protocol for CorrelationId — generated from CorrelationId.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class CorrelationIdProvider(Protocol):
    """CorrelationId primitive — opaque, request-scoped identifier."""

    def current(self) -> CorrelationId: ...
    def generate(self) -> CorrelationId: ...
