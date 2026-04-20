"""Unit tests for RateLimiter — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from RateLimiter import (
    InMemoryRateLimiter,
    RateLimitedError,
    RateLimiterError,
)


# ---------------------------------------------------------------------------
# RATE_INV_01 — long-run admitted rate NEVER exceeds rate_per_second
# ---------------------------------------------------------------------------
def test_inv_rate_cap_confirms() -> None:
    # Burst=1, rate=10/s — after the first (burst) token the admitted rate is capped.
    limiter = InMemoryRateLimiter(rate_per_second=10.0, burst=1)
    admitted = 0
    started = time.monotonic()
    for _ in range(25):
        if limiter.try_acquire("tenant-a"):
            admitted += 1
        time.sleep(0.01)
    elapsed = time.monotonic() - started
    # Cap: burst + rate * elapsed; allow small scheduler slack.
    cap = 1 + int(10.0 * elapsed) + 1
    assert admitted <= cap


def test_inv_rate_cap_prevents() -> None:
    # Two bursts in quick succession on the same key MUST NOT both pass.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is True
    # Third admission requires refill; bucket is empty and no time has passed.
    assert limiter.try_acquire("k") is False


def test_inv_rate_cap_under_failure() -> None:
    # Even under concurrent bursts from many threads, admissions MUST respect the cap.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=3)
    admitted: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = limiter.try_acquire("shared")
        with lock:
            admitted.append(ok)

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Over this sub-second window the cap is at most burst+1 (refill is tiny).
    assert sum(1 for a in admitted if a) <= 4


# ---------------------------------------------------------------------------
# RATE_INV_02 — acquire NEVER blocks longer than wait_ms
# ---------------------------------------------------------------------------
def test_inv_wait_deadline_confirms() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
        assert await limiter.acquire("k", cost=1, wait_ms=0) is True
        # Second acquire with wait_ms=30 MUST raise within ~30ms since refill takes 1s.
        started = time.monotonic()
        with pytest.raises(RateLimitedError):
            await limiter.acquire("k", cost=1, wait_ms=30)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        # Allow generous upper bound for CI jitter but prove no unbounded block.
        assert elapsed_ms < 300.0

    asyncio.run(run())


def test_inv_wait_deadline_prevents() -> None:
    # A negative wait_ms MUST be rejected at construction time.
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
        with pytest.raises(RateLimiterError):
            await limiter.acquire("k", cost=1, wait_ms=-5)

    asyncio.run(run())


def test_inv_wait_deadline_under_failure() -> None:
    # Under heavy contention (many waiters for the same key) each one respects its own deadline.
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=0.5, burst=1)
        assert await limiter.acquire("k", cost=1, wait_ms=0) is True
        started = time.monotonic()
        tasks = [
            asyncio.create_task(limiter.acquire("k", cost=1, wait_ms=20))
            for _ in range(5)
        ]
        # All MUST raise within ~20ms + slack.
        for t in tasks:
            with pytest.raises(RateLimitedError):
                await t
        elapsed_ms = (time.monotonic() - started) * 1000.0
        assert elapsed_ms < 500.0

    asyncio.run(run())


# ---------------------------------------------------------------------------
# RATE_INV_03 — keys are explicit, non-empty, instance-scoped
# ---------------------------------------------------------------------------
def test_inv_key_scope_confirms() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    # Distinct keys are tracked independently.
    assert limiter.try_acquire("alpha") is True
    assert limiter.try_acquire("beta") is True
    # Exhausted keys do not affect one another.
    assert limiter.try_acquire("alpha") is False
    assert limiter.try_acquire("beta") is False


def test_inv_key_scope_prevents() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    # Empty keys, non-string keys, oversized keys are all rejected.
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("")
    with pytest.raises(RateLimiterError):
        limiter.try_acquire(123)  # type: ignore[arg-type]  # RATE_INV_03 — non-str keys FORBIDDEN
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("x" * 1024)


def test_inv_key_scope_under_failure() -> None:
    # Two INDEPENDENT limiter instances MUST NOT share bucket state for the same key string.
    a = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    b = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    assert a.try_acquire("shared-key") is True
    # b's bucket for "shared-key" is fresh — limiter instance defines scope.
    assert b.try_acquire("shared-key") is True


# ---------------------------------------------------------------------------
# RATE_INV_04 — a rejection carries retry_after_ms computed from depletion
# ---------------------------------------------------------------------------
def test_inv_retry_after_confirms() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=2.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        with pytest.raises(RateLimitedError) as excinfo:
            await limiter.acquire("k", cost=1, wait_ms=0)
        # 1 token at 2/s = ~500ms retry.
        assert 200 <= excinfo.value.retry_after_ms <= 800

    asyncio.run(run())


def test_inv_retry_after_prevents() -> None:
    # A rejected try_acquire MUST have logged retry_after_ms > 0 in the event trail.
    limiter = InMemoryRateLimiter(rate_per_second=2.0, burst=1)
    limiter.try_acquire("k")  # admitted, empties bucket
    assert limiter.try_acquire("k") is False
    rejected = [e for e in limiter.events if e.key == "k" and not e.admitted]
    assert rejected
    assert rejected[-1].retry_after_ms > 0


def test_inv_retry_after_under_failure() -> None:
    # A rejected acquire-with-wait also publishes retry_after_ms on the exception.
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=5.0, burst=2)
        await limiter.acquire("k", cost=2, wait_ms=0)
        with pytest.raises(RateLimitedError) as excinfo:
            await limiter.acquire("k", cost=2, wait_ms=10)
        assert excinfo.value.retry_after_ms > 0

    asyncio.run(run())


# ---------------------------------------------------------------------------
# RATE_INV_05 — cost > 1 consumes proportional tokens
# ---------------------------------------------------------------------------
def test_inv_cost_proportional_confirms() -> None:
    # cost=3 on a burst=3 bucket admits once and exhausts the bucket.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=3)
    assert limiter.try_acquire("k", cost=3) is True
    # Subsequent cost=1 MUST be refused (bucket drained by the cost=3 admission).
    assert limiter.try_acquire("k", cost=1) is False


def test_inv_cost_proportional_prevents() -> None:
    # cost=0 / negative / bool / non-int are rejected; cost > burst is rejected.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("k", cost=0)
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("k", cost=-1)
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("k", cost=True)  # type: ignore[arg-type]  # RATE_INV_05 — bool is FORBIDDEN
    with pytest.raises(RateLimiterError):
        limiter.try_acquire("k", cost=10)


def test_inv_cost_proportional_under_failure() -> None:
    # A cost=3 success MUST drain more than a cost=1 success — quantitative parity check.
    a = InMemoryRateLimiter(rate_per_second=1.0, burst=5)
    b = InMemoryRateLimiter(rate_per_second=1.0, burst=5)
    a.try_acquire("k", cost=3)
    b.try_acquire("k", cost=1)
    # After cost=3, only 2 tokens remain in a; after cost=1, 4 remain in b.
    # Equivalently: a fills up to fewer additional cost=1 calls than b.
    remaining_a = 0
    while a.try_acquire("k", cost=1):
        remaining_a += 1
    remaining_b = 0
    while b.try_acquire("k", cost=1):
        remaining_b += 1
    assert remaining_a < remaining_b
