"""OptimisticConcurrency — Protocol-only declaration."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

V = TypeVar("V")


@runtime_checkable
class OptimisticConcurrency(Protocol[V]):
    def read(self, key: str) -> tuple[V | None, int]: ...
    def compare_and_swap(
        self, key: str, old_version: int, new_value: V
    ) -> int: ...
