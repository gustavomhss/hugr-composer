"""CausalReorderBuffer — Protocol-only declaration (copy from CausalReorderBuffer.py)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CausalReorderBuffer(Protocol):
    def offer(
        self,
        aggregate_id: str,
        sequence: int,
        event: Mapping[str, Any],
        deadline_ms: int,
    ) -> None: ...
    def next_ready(self, aggregate_id: str) -> Iterator[Mapping[str, Any]]: ...
    def timed_out(self, now_ms: int) -> list[tuple[str, int]]: ...
