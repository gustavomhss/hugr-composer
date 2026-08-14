"""Tests for ShardedCounter invariants SC_INV_01..05."""

from __future__ import annotations

import threading

import pytest

from core.venous.data.ShardedCounter.ShardedCounter import (
    InMemoryShardedCounter,
    PolicyToken,
    ShardedCounterError,
)


# ---------------------------------------------------------------------------
# INV_01: no decrement
# ---------------------------------------------------------------------------
def test_inv_monotonic_prevents_zero_delta() -> None:
    c = InMemoryShardedCounter()
    with pytest.raises(ShardedCounterError):
        c.increment("k", 0)


def test_inv_monotonic_prevents_negative_delta() -> None:
    c = InMemoryShardedCounter()
    with pytest.raises(ShardedCounterError):
        c.increment("k", -3)


# ---------------------------------------------------------------------------
# INV_02: session causality
# ---------------------------------------------------------------------------
def test_inv_session_causality_confirms() -> None:
    c = InMemoryShardedCounter()
    c.increment("k", 5)
    assert c.value("k") >= 5
    c.increment("k", 2)
    assert c.value("k") == 7


# ---------------------------------------------------------------------------
# INV_03: value is sum across shards
# ---------------------------------------------------------------------------
def test_inv_value_is_sum_confirms() -> None:
    c = InMemoryShardedCounter(shard_count=4)
    # Mutate shards directly to simulate cross-thread fan-out.
    c._shards["k"] = [3, 7, 1, 4]  # noqa: SLF001
    assert c.value("k") == 15


def test_inv_missing_key_returns_zero() -> None:
    c = InMemoryShardedCounter()
    assert c.value("never-touched") == 0


# ---------------------------------------------------------------------------
# INV_04: shard count is fixed
# ---------------------------------------------------------------------------
def test_inv_shard_count_fixed_at_construction() -> None:
    c = InMemoryShardedCounter(shard_count=8)
    assert c.shard_count == 8
    # Property is read-only — there is no setter.
    with pytest.raises(AttributeError):
        c.shard_count = 16  # type: ignore[misc]


def test_inv_shard_count_prevents_zero() -> None:
    with pytest.raises(ShardedCounterError):
        InMemoryShardedCounter(shard_count=0)


# ---------------------------------------------------------------------------
# INV_05: concurrent increments fan out across shards
# ---------------------------------------------------------------------------
def test_inv_concurrent_increments_fan_out_confirms() -> None:
    c = InMemoryShardedCounter(shard_count=8)
    # A Barrier guarantees all 8 threads are alive and truly concurrent before
    # any increment runs. Without it, each thread finishes (100 trivial
    # increments) before the next starts, the runtime reuses the thread ident,
    # and every increment lands on the same shard — a test artifact, not a
    # primitive defect.
    barrier = threading.Barrier(8)

    def bump() -> None:
        barrier.wait()
        for _ in range(100):
            c.increment("hot", 1)

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 8 threads * 100 increments = 800.
    assert c.value("hot") == 800
    # At least 2 shards must be non-zero — confirms fan-out.
    non_zero = sum(1 for s in c._shards["hot"] if s > 0)  # noqa: SLF001
    assert non_zero >= 2, f"expected fan-out across shards, got {c._shards['hot']}"  # noqa: SLF001


# ---------------------------------------------------------------------------
# reset requires a PolicyToken
# ---------------------------------------------------------------------------
def test_reset_requires_policy_token() -> None:
    c = InMemoryShardedCounter()
    c.increment("k", 5)
    with pytest.raises(ShardedCounterError):
        c.reset("k", None)  # type: ignore[arg-type]
    c.reset("k", PolicyToken("quota-rollover"))
    assert c.value("k") == 0
