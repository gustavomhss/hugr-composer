"""Concurrency / linearizability harness for RateLimiter.

Confirms that concurrent admissions, rejections, and resets never over-admit
past burst and never corrupt the per-key bucket.
"""

from __future__ import annotations

import asyncio
import threading
import time

from RateLimiter import InMemoryRateLimiter


def test_concurrent_admissions_respect_burst_bound() -> None:
    # 64 threads, burst=10 — no more than 10 admissions on the same key.
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=10)
    admitted: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = limiter.try_acquire("k")
        with lock:
            admitted.append(ok)

    ts = [threading.Thread(target=worker) for _ in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for a in admitted if a) == 10


def test_concurrent_distinct_keys_never_cross_contend() -> None:
    # 32 threads each on a distinct key — each gets their full burst.
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=2)
    results: dict[str, int] = {}
    lock = threading.Lock()

    def worker(i: int) -> None:
        key = f"k-{i}"
        local = 0
        for _ in range(5):
            if limiter.try_acquire(key):
                local += 1
        with lock:
            results[key] = local

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Every distinct key admitted exactly the burst=2 attempts.
    assert all(v == 2 for v in results.values())


def test_concurrent_async_waiters_do_not_over_admit() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=5.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        # 10 waiters, all racing over a 150ms window; refill at 5/s -> ~0-1 extra admit.
        tasks = [
            asyncio.create_task(limiter.acquire("k", cost=1, wait_ms=150))
            for _ in range(10)
        ]
        results: list[bool] = []
        for t in tasks:
            try:
                ok = await t
                results.append(ok)
            except Exception:
                results.append(False)
        admitted = sum(1 for r in results if r)
        # At most ~1 additional token arrives in the 150ms window.
        assert admitted <= 2

    asyncio.run(run())


def test_concurrent_reset_amid_admissions_does_not_raise() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=0.001, burst=4)
    errors: list[BaseException] = []
    stop = threading.Event()
    lock = threading.Lock()

    def admit_worker() -> None:
        while not stop.is_set():
            try:
                limiter.try_acquire("k")
            except BaseException as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)

    def reset_worker() -> None:
        while not stop.is_set():
            try:
                limiter.reset("k")
            except BaseException as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)

    ts = [threading.Thread(target=admit_worker) for _ in range(4)]
    ts += [threading.Thread(target=reset_worker) for _ in range(2)]
    for t in ts:
        t.start()
    time.sleep(0.1)
    stop.set()
    for t in ts:
        t.join(timeout=2.0)
    assert errors == []
