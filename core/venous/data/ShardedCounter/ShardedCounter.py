"""ShardedCounter primitive — hot-key-safe monotonic counter.

Distributes writes across N fixed shards so concurrent increments on the
same key never all hit one row/partition. The visible ``value(key)`` is
the sum of all shards.

Based on Google Cloud Datastore's sharded-counter recommendation — see
``ShardedCounter.md`` provenance. This reference impl is pure in-memory;
Redis / Postgres adapters live in ``core/venous/_adapters/`` and add
durability.

Invariant IDs (full text in ``ShardedCounter.md``):

- SC_INV_01: Counter MUST NEVER decrement (delta MUST be > 0).
- SC_INV_02: Read-after-write in the same session reflects at least the
  preceding increment (session causality).
- SC_INV_03: ``value(key)`` is the SUM of all shard values — never a
  single shard.
- SC_INV_04: Shard count is fixed at construction; changing it requires
  a migration primitive (out of scope here).
- SC_INV_05: Concurrent increments on the same key hit DIFFERENT shards
  (hashed modulo shard_count on thread/async-task id).
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable


class ShardedCounterError(RuntimeError):
    """Raised when counter contract is violated."""


class PolicyToken:
    """Opaque authorization marker — obtain via a policy primitive."""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ShardedCounterError("PolicyToken reason MUST be non-empty str")
        self.reason = reason


@runtime_checkable
class ShardedCounter(Protocol):
    def increment(self, key: str, delta: int = 1) -> None: ...
    def value(self, key: str) -> int: ...
    def reset(self, key: str, token: PolicyToken) -> None: ...


def _hash_task_id() -> int:
    """Stable int derived from current thread — async tasks inherit the
    thread id in a single-loop runtime. Fed through ``hash(...)`` so
    consecutive OS thread ids do not collide on the same low bits when
    taken modulo small shard counts. For true async-task routing, wrap
    this primitive in an adapter that uses ``asyncio.current_task()``.
    """
    tid = threading.get_ident()
    # Mix the bits — OS thread ids tend to share low nibbles and would
    # collide on small shard counts otherwise.
    x = (tid ^ (tid >> 16)) * 0x45D9F3B
    x = (x ^ (x >> 16)) * 0x45D9F3B
    return x ^ (x >> 16)


class InMemoryShardedCounter:
    """Reference ShardedCounter — dict[key, list[int-per-shard]] in memory."""

    def __init__(self, *, shard_count: int = 8) -> None:
        if shard_count < 1:
            raise ShardedCounterError("shard_count MUST be >= 1")
        # SC_INV_04: shard_count is a private attribute; no setter exposed.
        self._shard_count: int = shard_count
        self._shards: dict[str, list[int]] = {}
        self._lock = threading.RLock()

    @property
    def shard_count(self) -> int:
        return self._shard_count

    # ------------------------------------------------------------------
    # Public Protocol
    # ------------------------------------------------------------------
    def increment(self, key: str, delta: int = 1) -> None:
        """SC_INV_01: delta MUST be > 0."""
        if not isinstance(key, str) or not key:
            raise ShardedCounterError("key MUST be a non-empty str")
        if delta <= 0:
            raise ShardedCounterError(
                "SC_INV_01: delta MUST be > 0; sharded counters do not decrement"
            )
        # SC_INV_05: route by thread/task id modulo shard_count.
        shard_idx = _hash_task_id() % self._shard_count
        with self._lock:
            shards = self._shards.get(key)
            if shards is None:
                shards = [0] * self._shard_count
                self._shards[key] = shards
            shards[shard_idx] += delta

    def value(self, key: str) -> int:
        """SC_INV_03: sum across ALL shards."""
        if not isinstance(key, str):
            raise ShardedCounterError("key MUST be a str")
        with self._lock:
            shards = self._shards.get(key)
            if shards is None:
                return 0
            return sum(shards)

    def reset(self, key: str, token: PolicyToken) -> None:
        """Reset requires an explicit PolicyToken — no accidental resets."""
        if not isinstance(token, PolicyToken):
            raise ShardedCounterError(
                "reset() requires a PolicyToken; obtain via the policy primitive"
            )
        with self._lock:
            self._shards.pop(key, None)


__all__ = [
    "InMemoryShardedCounter",
    "PolicyToken",
    "ShardedCounter",
    "ShardedCounterError",
]
