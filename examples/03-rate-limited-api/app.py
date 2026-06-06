"""Rate-limited API — token bucket + priority bulkhead + sharded counter.

Self-contained in-memory demo. The production version wires these to the
`RateLimiter`, `Bulkhead`, and `ShardedCounter` primitives.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Literal


@dataclass
class Decision:
    allowed: bool
    remaining: int
    retry_after_s: int  # 0 when allowed


class TokenBucket:
    """Minute-window token bucket mirror of the `RateLimiter` primitive.

    Invariants:
      - Non-negative remaining at all times.
      - On refusal, ``retry_after_s > 0`` points at the window reset.
    """

    def __init__(self, *, capacity: int, window_s: int = 60) -> None:
        self.capacity = capacity
        self.window_s = window_s
        self._remaining = capacity
        self._window_start = 0.0
        self._lock = threading.Lock()

    def allow(self, *, now: float) -> Decision:
        with self._lock:
            if now - self._window_start >= self.window_s:
                self._window_start = now
                self._remaining = self.capacity
            if self._remaining <= 0:
                retry = int(self._window_start + self.window_s - now) + 1
                return Decision(allowed=False, remaining=0, retry_after_s=max(retry, 1))
            self._remaining -= 1
            return Decision(allowed=True, remaining=self._remaining, retry_after_s=0)


Priority = Literal["low", "high"]


class PriorityBulkhead:
    """Mirror of `Bulkhead` + `LoadShedder`.

    `try_admit(priority)` returns True if the request is admitted. When
    in-flight exceeds capacity, low-priority is shed first.
    """

    def __init__(self, *, capacity: int) -> None:
        self.capacity = capacity
        self._in_flight: deque[Priority] = deque()
        self._lock = threading.Lock()

    def try_admit(self, priority: Priority) -> bool:
        with self._lock:
            if len(self._in_flight) < self.capacity:
                self._in_flight.append(priority)
                return True
            # At capacity. Check if any in-flight is low-priority and this is high.
            if priority == "high":
                for i, p in enumerate(self._in_flight):
                    if p == "low":
                        del self._in_flight[i]
                        self._in_flight.append("high")
                        return True
            return False

    def release(self, priority: Priority) -> None:
        with self._lock:
            try:
                self._in_flight.remove(priority)
            except ValueError:
                pass


class ShardedCounter:
    """Mirror of `ShardedCounter` primitive. Per-key additive counter.

    Invariant: sum-on-read equals total increments across all shards, always.
    """

    def __init__(self, *, shards: int = 32) -> None:
        self._shards = [0] * shards
        self._locks = [threading.Lock() for _ in range(shards)]

    def incr(self, key: str, n: int = 1) -> None:
        idx = hash(key) % len(self._shards)
        with self._locks[idx]:
            self._shards[idx] += n

    def total(self) -> int:
        # Snapshot of shards — acquires every lock briefly.
        out = 0
        for lk, v in zip(self._locks, self._shards):
            with lk:
                out += v
        return out
