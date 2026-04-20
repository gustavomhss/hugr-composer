"""Metamorphic + differential tests for RateLimiter.

Algebraic properties verified:
- Decomposition: N cost=1 calls drain the bucket identically to one cost=N call.
- Additivity: admissions across distinct keys are independent (sum of parts = whole).
- Monotonicity: the admitted count within a fixed window is non-decreasing in rate_per_second.
- Reset idempotence: a bucket after reset behaves indistinguishably from a fresh instance.
- Differential: ``try_acquire`` and ``await acquire(..., wait_ms=0)`` yield the same admission outcome.
"""

from __future__ import annotations

import asyncio
import time

from RateLimiter import InMemoryRateLimiter, RateLimitedError


def test_metamorphic_cost_decomposition() -> None:
    a = InMemoryRateLimiter(rate_per_second=0.001, burst=10)
    b = InMemoryRateLimiter(rate_per_second=0.001, burst=10)
    # One cost=5 admission.
    assert a.try_acquire("k", cost=5) is True
    # Five cost=1 admissions — same total drain on a fresh-but-equivalent bucket.
    for _ in range(5):
        assert b.try_acquire("k", cost=1) is True
    # Both have 5 tokens remaining.
    assert a.try_acquire("k", cost=5) is True
    assert b.try_acquire("k", cost=5) is True
    assert a.try_acquire("k", cost=1) is False
    assert b.try_acquire("k", cost=1) is False


def test_metamorphic_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=3)
    admits_per_key: dict[str, int] = {}
    for k in ("alpha", "beta", "gamma"):
        admits_per_key[k] = 0
        while limiter.try_acquire(k):
            admits_per_key[k] += 1
    # Each key gets its own fresh burst.
    assert all(v == 3 for v in admits_per_key.values())


def test_metamorphic_rate_monotonicity() -> None:
    def run(rate: float) -> int:
        limiter = InMemoryRateLimiter(rate_per_second=rate, burst=1)
        admitted = 0
        started = time.monotonic()
        # 120ms observation window.
        while time.monotonic() - started < 0.12:
            if limiter.try_acquire("k"):
                admitted += 1
            time.sleep(0.005)
        return admitted

    low = run(5.0)
    high = run(50.0)
    assert high >= low  # more rate => more admissions (never fewer).


def test_metamorphic_reset_idempotence() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    limiter.try_acquire("k")
    limiter.try_acquire("k")
    assert limiter.try_acquire("k") is False
    limiter.reset("k")
    # Fresh-bucket behaviour after reset.
    fresh = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    assert limiter.try_acquire("k") == fresh.try_acquire("k")
    assert limiter.try_acquire("k") == fresh.try_acquire("k")
    assert limiter.try_acquire("k") == fresh.try_acquire("k")


def test_differential_try_vs_acquire_waitzero_agree() -> None:
    async def run() -> None:
        a = InMemoryRateLimiter(rate_per_second=0.001, burst=3)
        b = InMemoryRateLimiter(rate_per_second=0.001, burst=3)

        sync_outcomes = []
        async_outcomes = []
        for _ in range(5):
            sync_outcomes.append(a.try_acquire("k"))
            try:
                await b.acquire("k", cost=1, wait_ms=0)
                async_outcomes.append(True)
            except RateLimitedError:
                async_outcomes.append(False)
        # Both paths admit exactly `burst=3` attempts.
        assert sync_outcomes == async_outcomes

    asyncio.run(run())
