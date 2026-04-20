"""Behavioral end-to-end scenarios for RetryPolicy — proves invariants at runtime."""

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
        max_attempts=3,
        initial_interval_ms=10,
        multiplier=2.0,
        max_interval_ms=1_000,
        jitter=1.0,
        budget_ratio=0.5,
        requires_idempotency=True,
        rng=random.Random(0),
        sleep_fn=_no_sleep,
        budget=RetryBudget(budget_ratio=0.5, min_floor=10),
    )
    defaults.update(kw)
    return ExponentialBackoffRetryPolicy(**defaults)  # type: ignore[arg-type]


def test_scenario_transient_error_recovered_with_idempotent_retry() -> None:
    p = _policy()
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("transient")
        return "ok"

    result = asyncio.run(p.execute(flaky, idempotent=True))
    assert result == "ok"
    assert attempts["n"] == 3


def test_scenario_non_idempotent_mutation_refused_even_on_transient() -> None:
    # RETRY-INV-01: FORBIDDEN to retry a mutation without explicit idempotency.
    p = _policy()

    async def post_charge() -> str:
        raise ConnectionError("socket closed mid-write")

    with pytest.raises(RetryPolicyInvariantError):
        asyncio.run(p.execute(post_charge))


def test_scenario_programmer_error_propagates_without_retry() -> None:
    # RETRY-INV-05: non-retryable classifier → no retries; original exception re-raised.
    p = _policy()
    calls = {"n": 0}

    async def bad() -> str:
        calls["n"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        asyncio.run(p.execute(bad, idempotent=True))
    assert calls["n"] == 1


def test_scenario_deadline_cuts_retry_sequence_short() -> None:
    p = _policy(max_attempts=10)
    budget = TimeoutBudget(remaining_ms=1)  # one retry exhausts it
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        raise TimeoutError("t")

    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(flaky, idempotent=True, budget=budget))
    assert calls["n"] < 10


def test_scenario_max_attempts_exhausted_reraises_last_error() -> None:
    p = _policy(max_attempts=3)

    async def flaky() -> str:
        raise ConnectionError("still down")

    with pytest.raises(ConnectionError):
        asyncio.run(p.execute(flaky, idempotent=True))


def test_scenario_fatal_error_short_circuits_loop() -> None:
    p = _policy()
    calls = {"n": 0}

    async def fatal() -> str:
        calls["n"] += 1
        raise FatalError("credentials revoked")

    with pytest.raises(FatalError):
        asyncio.run(p.execute(fatal, idempotent=True))
    assert calls["n"] == 1


def test_scenario_budget_ratio_caps_retry_amplification() -> None:
    # RETRY-INV-02: with a tiny budget, retry amplification is bounded.
    budget = RetryBudget(budget_ratio=0.0, min_floor=1)
    p = _policy(budget=budget)

    async def always_fail() -> str:
        raise TimeoutError("t")

    # Caller's own non-idempotent protection doesn't apply — idempotent=True.
    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(always_fail, idempotent=True))
    # Only one retry was admitted (min_floor=1).
    assert budget.retries <= 1
