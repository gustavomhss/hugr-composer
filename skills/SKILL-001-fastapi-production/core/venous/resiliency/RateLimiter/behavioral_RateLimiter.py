"""Behavioral end-to-end scenarios for RateLimiter — proves invariants at runtime."""

from __future__ import annotations

import asyncio
import time

import pytest

from RateLimiter import InMemoryRateLimiter, RateLimitedError


def test_scenario_noisy_tenant_does_not_starve_quiet_tenants() -> None:
    # A burst of 50 attempts from "noisy" MUST NOT reduce "quiet"'s quota.
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    for _ in range(50):
        limiter.try_acquire("noisy")
    # quiet's bucket is fresh.
    assert limiter.try_acquire("quiet") is True
    assert limiter.try_acquire("quiet") is True


def test_scenario_burst_then_steady_rate() -> None:
    # After the initial burst, the steady-state admitted rate tracks rate_per_second.
    limiter = InMemoryRateLimiter(rate_per_second=50.0, burst=5)
    burst_admits = 0
    for _ in range(5):
        if limiter.try_acquire("k"):
            burst_admits += 1
    assert burst_admits == 5
    # Immediately another admit MUST fail — bucket is empty.
    assert limiter.try_acquire("k") is False
    # After 60ms, at 50 tokens/s, ~3 tokens are available.
    time.sleep(0.06)
    recovered = 0
    for _ in range(5):
        if limiter.try_acquire("k"):
            recovered += 1
    assert 1 <= recovered <= 4


def test_scenario_wait_ms_succeeds_when_tokens_arrive_in_time() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=50.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        # With a 50ms wait and 50 tokens/s, the second acquire WILL succeed.
        ok = await limiter.acquire("k", cost=1, wait_ms=80)
        assert ok is True

    asyncio.run(run())


def test_scenario_rejected_caller_sees_retry_after() -> None:
    async def run() -> None:
        limiter = InMemoryRateLimiter(rate_per_second=5.0, burst=1)
        await limiter.acquire("k", cost=1, wait_ms=0)
        with pytest.raises(RateLimitedError) as excinfo:
            await limiter.acquire("k", cost=1, wait_ms=0)
        err = excinfo.value
        assert err.key == "k"
        assert err.cost == 1
        # 1 token at 5/s -> ~200ms retry.
        assert 100 <= err.retry_after_ms <= 400

    asyncio.run(run())


def test_scenario_expensive_call_costs_more_than_cheap_call() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=10)
    # One cost=5 call drains half the bucket.
    assert limiter.try_acquire("k", cost=5) is True
    cheap_admits = 0
    while limiter.try_acquire("k", cost=1):
        cheap_admits += 1
    # Only 5 cost=1 admits should fit in the remaining capacity.
    assert cheap_admits == 5


def test_scenario_reset_clears_bucket() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=2)
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is False
    limiter.reset("k")
    # Fresh bucket after reset.
    assert limiter.try_acquire("k") is True
    assert limiter.try_acquire("k") is True


def test_scenario_admission_events_are_observable() -> None:
    limiter = InMemoryRateLimiter(rate_per_second=1.0, burst=1)
    limiter.try_acquire("tenant-1")
    limiter.try_acquire("tenant-1")  # rejected
    events = limiter.events
    assert len(events) == 2
    assert events[0].admitted is True
    assert events[1].admitted is False
    assert events[1].retry_after_ms > 0
