"""Metamorphic + differential tests for RetryPolicy.

Algebraic properties:
- classification is deterministic: same exc type → same class across calls.
- next_delay_ms(attempt) with jitter=0 is monotonically non-decreasing up to cap.
- with jitter=0, next_delay_ms equals the exponential formula, no randomness.
- increasing max_attempts never reduces the number of attempts executed.
- full-jitter variance: mean across many samples ≈ base * (1 + jitter/2).
"""

from __future__ import annotations

import asyncio
import random
import statistics

from RetryPolicy import (
    ExponentialBackoffRetryPolicy,
    FatalError,
    NonRetryableError,
    RetryBudget,
    RetryClassifier,
)


async def _no_sleep(_s: float) -> None:
    return None


def _policy(**kw: object) -> ExponentialBackoffRetryPolicy:
    defaults: dict[str, object] = dict(
        max_attempts=5,
        initial_interval_ms=10,
        multiplier=2.0,
        max_interval_ms=10_000,
        jitter=0.0,
        budget_ratio=0.5,
        requires_idempotency=True,
        rng=random.Random(7),
        sleep_fn=_no_sleep,
        budget=RetryBudget(budget_ratio=0.5, min_floor=100),
    )
    defaults.update(kw)
    return ExponentialBackoffRetryPolicy(**defaults)  # type: ignore[arg-type]


def test_metamorphic_classification_deterministic() -> None:
    c = RetryClassifier()
    for _ in range(50):
        assert c.classify(TimeoutError("x")) == "retryable"
        assert c.classify(ValueError("x")) == "non_retryable"
        assert c.classify(FatalError("x")) == "fatal"
        assert c.classify(NonRetryableError("x")) == "non_retryable"


def test_metamorphic_delay_monotonic_no_jitter() -> None:
    p = _policy(jitter=0.0)
    delays = [p.next_delay_ms(a) for a in range(1, 6)]
    # 10, 20, 40, 80, 160 — strictly increasing until the cap bites.
    assert delays == sorted(delays)
    assert delays[0] < delays[-1]


def test_metamorphic_delay_capped_at_max_interval() -> None:
    p = _policy(initial_interval_ms=1_000, max_interval_ms=2_000, jitter=0.0)
    for a in range(1, 20):
        assert p.next_delay_ms(a) <= 2_000


def test_metamorphic_jitter_mean_matches_formula() -> None:
    # With full jitter=1.0, delay ~ uniform(base, 2*base). Mean ~ 1.5 * base.
    p = _policy(jitter=1.0, initial_interval_ms=100, max_interval_ms=100_000)
    samples = [p.next_delay_ms(1) for _ in range(5_000)]
    mean = statistics.fmean(samples)
    # base=100; expected mean 150 ± 5 (with 5k samples).
    assert 140 <= mean <= 160


def test_differential_larger_max_attempts_runs_at_least_as_many_calls() -> None:
    # Same error stream; more attempts → ≥ as many fn invocations.
    async def run_with(max_attempts: int) -> int:
        calls = {"n": 0}
        p = _policy(max_attempts=max_attempts)

        async def fail() -> str:
            calls["n"] += 1
            raise TimeoutError("t")

        try:
            await p.execute(fail, idempotent=True)
        except BaseException:  # noqa: BLE001
            pass
        return calls["n"]

    a = asyncio.run(run_with(2))
    b = asyncio.run(run_with(5))
    assert b >= a


def test_metamorphic_budget_monotonic_retries() -> None:
    # RetryBudget.retries count is non-decreasing under try_admit_retry.
    b = RetryBudget(budget_ratio=1.0, min_floor=100)
    prev = b.retries
    for _ in range(10):
        b.try_admit_retry()
        assert b.retries >= prev
        prev = b.retries
