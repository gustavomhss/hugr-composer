"""Tests for the sharded event counter example."""
from __future__ import annotations

import threading

import pytest

from app import ShardedCounter


def test_concurrent_increments_no_lost_or_duplicate_counts() -> None:
    c = ShardedCounter(shards=64)

    def worker():
        for _ in range(1_000):
            c.incr("hot-user")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert c.value("hot-user") == 10_000


def test_cold_user_first_read_returns_zero() -> None:
    c = ShardedCounter(shards=64)
    assert c.value("never-seen") == 0


def test_counter_is_monotonic_rejects_negative() -> None:
    c = ShardedCounter(shards=64)
    c.incr("u1", 5)
    with pytest.raises(ValueError, match="monotonic"):
        c.incr("u1", -1)
    assert c.value("u1") == 5


def test_dashboard_shows_per_shard_ops_and_hot_keys() -> None:
    c = ShardedCounter(shards=64)
    for _ in range(500):
        c.incr("whale-1")
    for i in range(50):
        c.incr(f"minnow-{i}")

    ops = c.shard_ops()
    assert sum(ops) == 550
    # At least one shard did meaningful work (the whale's shard).
    assert max(ops) >= 500

    top = c.hot_keys(top_n=3)
    assert top[0] == ("whale-1", 500)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
