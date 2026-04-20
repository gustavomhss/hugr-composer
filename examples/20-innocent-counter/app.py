"""Per-user lifetime counter — ShardedCounter over 64 shards."""
from __future__ import annotations

import threading
from collections import defaultdict


class ShardedCounter:
    """N-sharded per-key counter.

    Writes are local to a shard (no cross-shard lock contention).
    Reads sum the N shard entries for the key — O(N) with N small.
    """

    def __init__(self, *, shards: int = 64) -> None:
        self._n = shards
        self._shards: list[dict[str, int]] = [defaultdict(int) for _ in range(shards)]
        self._locks = [threading.Lock() for _ in range(shards)]
        self._shard_ops = [0] * shards

    def _idx(self, key: str) -> int:
        return hash(key) % self._n

    def incr(self, key: str, n: int = 1) -> None:
        if n < 0:
            raise ValueError("counter is monotonic; negative increments rejected")
        idx = self._idx(key)
        with self._locks[idx]:
            self._shards[idx][key] += n
            self._shard_ops[idx] += 1

    def value(self, key: str) -> int:
        total = 0
        for i, shard in enumerate(self._shards):
            # Lock each shard briefly for a consistent read.
            with self._locks[i]:
                total += shard.get(key, 0)
        return total

    def shard_ops(self) -> list[int]:
        return list(self._shard_ops)

    def hot_keys(self, top_n: int = 10) -> list[tuple[str, int]]:
        """Aggregate per-key totals across shards and return top N."""
        agg: dict[str, int] = defaultdict(int)
        for i, shard in enumerate(self._shards):
            with self._locks[i]:
                for k, v in shard.items():
                    agg[k] += v
        return sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
