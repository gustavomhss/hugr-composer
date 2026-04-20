"""Chaos / game-day tests for RateLimiter.

Simulates thundering-herd admission bursts, clock-insensitive workloads, and
adversarial key churn to confirm the limiter never over-admits and never
unbounded-blocks.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from RateLimiter import InMemoryRateLimiter, RateLimitedError, RateLimiterError


def test_chaos_thundering_herd_respects_burst() -> None:
    # 200 threads race for a burst=5 bucket on the same key — exactly 5 MUST win.
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=5)
    admits: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = limiter.try_acquire("hot-key")
        with lock:
            admits.append(ok)

    ts = [threading.Thread(target=worker) for _ in range(200)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for a in admits if a) == 5


def test_chaos_key_churn_does_not_leak_admissions() -> None:
    # 1000 unique keys each get a fresh burst; no cross-contamination.
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=1)
    unique_admits = 0
    for i in range(1000):
        if limiter.try_acquire(f"key-{i}"):
            unique_admits += 1
    assert unique_admits == 1000
    # A repeat attempt on any exhausted key MUST be refused.
    assert limiter.try_acquire("key-0") is False


def test_chaos_flapping_acquire_rejects_gracefully() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        rejections = 0
        for _ in range(30):
            try:
                await limiter.acquire("k", cost=1, wait_ms=0)
            except RateLimitedError:
                rejections += 1
        assert rejections == 30

    asyncio.run(run())


def test_chaos_wait_ms_deadline_never_overshoots() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        started = time.monotonic()
        with pytest.raises(RateLimitedError):
            await limiter.acquire("k", cost=1, wait_ms=40)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        # Deadline + generous jitter budget. Never 1000ms (the natural refill).
        assert elapsed_ms < 250.0

    asyncio.run(run())


def test_chaos_bool_cost_is_rejected_even_under_stress() -> None:
    # bool is a subclass of int — the limiter MUST refuse it deterministically.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=10)
    for _ in range(50):
        with pytest.raises(RateLimiterError):
            limiter.try_acquire("k", cost=True)  # type: ignore[arg-type]  # RATE_INV_05 — bool FORBIDDEN


def test_chaos_cost_exceeds_burst_is_unsatisfiable() -> None:
    # Any cost > burst is unsatisfiable and MUST fail fast; never hangs for wait_ms.
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=3)
        started = time.monotonic()
        with pytest.raises(RateLimiterError):
            await limiter.acquire("k", cost=10, wait_ms=10_000)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        # Rejected synchronously, not after the 10-second wait.
        assert elapsed_ms < 100.0

    asyncio.run(run())


def test_chaos_events_log_does_not_break_under_burst() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=5)
    for _ in range(500):
        limiter.try_acquire("k")
    # Every attempt produced one event — 5 admits, 495 rejects.
    events = limiter.events
    assert len(events) == 500
    assert sum(1 for e in events if e.admitted) == 5


def test_chaos_concurrent_reset_is_safe() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=3)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def acquire_worker() -> None:
        try:
            for _ in range(100):
                limiter.try_acquire("k")
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    def reset_worker() -> None:
        try:
            for _ in range(100):
                limiter.reset("k")
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=acquire_worker) for _ in range(4)]
    ts += [threading.Thread(target=reset_worker) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
