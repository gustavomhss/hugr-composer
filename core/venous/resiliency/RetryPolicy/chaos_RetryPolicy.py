"""Chaos / game-day tests for RetryPolicy.

Simulates flapping backends, budget exhaustion, adversarial classifiers, and
interleaved deadline + non-idempotent attempts. Confirms the policy never
amplifies failing traffic beyond the budget and never retries forbidden calls.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from RetryPolicy import (
    ExponentialBackoffRetryPolicy,
    FatalError,
    NonRetryableError,
    RetryBudget,
    RetryPolicyInvariantError,
    TimeoutBudget,
)


async def _no_sleep(_s: float) -> None:
    return None


def _policy(**kw: object) -> ExponentialBackoffRetryPolicy:
    defaults: dict[str, object] = dict(
        max_attempts=4,
        initial_interval_ms=1,
        multiplier=2.0,
        max_interval_ms=100,
        jitter=1.0,
        budget_ratio=0.2,
        requires_idempotency=True,
        rng=random.Random(13),
        sleep_fn=_no_sleep,
        budget=RetryBudget(budget_ratio=0.2, min_floor=5),
    )
    defaults.update(kw)
    return ExponentialBackoffRetryPolicy(**defaults)  # type: ignore[arg-type]


def test_chaos_flapping_backend_eventually_succeeds() -> None:
    p = _policy(max_attempts=10)
    attempts = {"n": 0}
    pattern = [True, True, True, True, False]  # 4 failures then success

    async def flaky() -> str:
        i = attempts["n"]
        attempts["n"] += 1
        if pattern[i % len(pattern)]:
            raise TimeoutError("flap")
        return "ok"

    result = asyncio.run(p.execute(flaky, idempotent=True))
    assert result == "ok"


def test_chaos_sustained_failure_exhausts_max_attempts() -> None:
    p = _policy(max_attempts=3)
    calls = {"n": 0}

    async def dead() -> str:
        calls["n"] += 1
        raise ConnectionError("dead")

    with pytest.raises(ConnectionError):
        asyncio.run(p.execute(dead, idempotent=True))
    assert calls["n"] == 3  # attempt count monotonic; exactly max_attempts


def test_chaos_budget_stops_retry_storm() -> None:
    # With small budget and many calls, retries MUST cap at budget admission.
    budget = RetryBudget(budget_ratio=0.0, min_floor=2)
    p = _policy(budget=budget, budget_ratio=0.0, max_attempts=100)

    async def dead() -> str:
        raise TimeoutError("t")

    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(dead, idempotent=True))
    assert budget.retries <= 2


def test_chaos_fatal_aborts_immediately() -> None:
    p = _policy()
    calls = {"n": 0}

    async def fatal() -> str:
        calls["n"] += 1
        raise FatalError("revoked")

    with pytest.raises(FatalError):
        asyncio.run(p.execute(fatal, idempotent=True))
    assert calls["n"] == 1


def test_chaos_non_idempotent_mutation_never_retried() -> None:
    p = _policy()

    async def mutate() -> str:
        raise ConnectionError("mid-write socket reset")

    with pytest.raises(RetryPolicyInvariantError):
        asyncio.run(p.execute(mutate))


def test_chaos_deadline_pressure_cuts_sequence() -> None:
    p = _policy(max_attempts=10)
    bud = TimeoutBudget(remaining_ms=2)
    calls = {"n": 0}

    async def slow_fail() -> str:
        calls["n"] += 1
        raise TimeoutError("slow")

    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(slow_fail, idempotent=True, budget=bud))
    assert calls["n"] < 10


def test_chaos_requires_idempotency_false_allows_retries() -> None:
    # Explicit operator decision: retry without idempotency flag.
    p = _policy(requires_idempotency=False)
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise TimeoutError("t")
        return "ok"

    assert asyncio.run(p.execute(flaky)) == "ok"
    assert attempts["n"] == 2
