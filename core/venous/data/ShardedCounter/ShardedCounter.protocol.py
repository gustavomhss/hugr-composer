"""ShardedCounter — Protocol-only declaration."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class PolicyToken:
    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason


@runtime_checkable
class ShardedCounter(Protocol):
    def increment(self, key: str, delta: int = 1) -> None: ...
    def value(self, key: str) -> int: ...
    def reset(self, key: str, token: PolicyToken) -> None: ...
