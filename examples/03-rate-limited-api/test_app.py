"""Tests for rate-limited API example."""
from __future__ import annotations

import threading

import pytest

from app import PriorityBulkhead, ShardedCounter, TokenBucket


def test_token_bucket_allows_up_to_capacity_then_refuses() -> None:
    b = TokenBucket(capacity=3, window_s=60)
    now = 1000.0
    first = [b.allow(now=now) for _ in range(3)]
    assert all(d.allowed for d in first)
    assert [d.remaining for d in first] == [2, 1, 0]

    d = b.allow(now=now)
    assert d.allowed is False
    assert d.retry_after_s > 0 and d.retry_after_s <= 61


def test_token_bucket_refills_at_window_boundary() -> None:
    b = TokenBucket(capacity=2, window_s=60)
    assert b.allow(now=0.0).allowed
    assert b.allow(now=0.0).allowed
    assert b.allow(now=0.0).allowed is False
    # After the window, refilled.
    assert b.allow(now=60.0).allowed


def test_bulkhead_sheds_low_priority_first_when_saturated() -> None:
    bh = PriorityBulkhead(capacity=2)
    assert bh.try_admit("low") is True
    assert bh.try_admit("low") is True
    # High comes in while full — should evict a low and get in.
    assert bh.try_admit("high") is True
    # Another low arrives — full, no more lows to evict, must refuse.
    assert bh.try_admit("low") is False


def test_bulkhead_high_priority_refused_when_all_high() -> None:
    bh = PriorityBulkhead(capacity=1)
    assert bh.try_admit("high") is True
    # Only a high is in flight; a new high cannot evict itself.
    assert bh.try_admit("high") is False


def test_sharded_counter_accurate_under_concurrent_increment() -> None:
    c = ShardedCounter(shards=16)

    def worker() -> None:
        for _ in range(1000):
            c.incr("apikey-1")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert c.total() == 10 * 1000


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
