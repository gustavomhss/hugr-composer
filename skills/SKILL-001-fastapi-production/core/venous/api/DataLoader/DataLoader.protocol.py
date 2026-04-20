"""DataLoader — Protocol-only declaration (copy from DataLoader.py)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Hashable, Protocol, TypeVar, runtime_checkable

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

BatchFn = Callable[[list[K]], Awaitable[list[V]]]


@runtime_checkable
class DataLoader(Protocol[K, V]):
    async def load(self, key: K) -> V: ...
    async def load_many(self, keys: list[K]) -> list[V]: ...
    def prime(self, key: K, value: V) -> None: ...
    def clear(self, key: K) -> None: ...
