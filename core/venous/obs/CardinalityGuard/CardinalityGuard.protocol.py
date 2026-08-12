"""Protocol for CardinalityGuard — generated from CardinalityGuard.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class CardinalityGuard(Protocol):
    """CardinalityGuard primitive — bounds unique attribute-value combinations."""

    def admit(self, metric_name: str, attributes: Mapping[str, str]) -> Mapping[str, str]: ...
    def configure(self) -> None: ...
    def stats(self, metric_name: str) -> Mapping[str, int]: ...
