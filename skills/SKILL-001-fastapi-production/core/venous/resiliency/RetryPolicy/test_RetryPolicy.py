"""Unit tests for RetryPolicy — three per invariant (confirms / prevents / under_failure)."""

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


def _run(coro: object) -> object:
    return asyncio.get_event_loop().run_until_complete(coro)  # type: ignore[arg-type]


async def _always_fail(exc: BaseException) -> None:
    raise exc


def _policy(
    *,
    max_attempts: int = 3,
    requires_idempotency: bool = True,
    jitter: float = 0.0,
    budget_ratio: float = 0.1,
    budget: RetryBudget | None = None,
    sleep_fn: object | None = None,
) -> ExponentialBackoffRetryPolicy:
    async def _no_sleep(_s: float) -> None:
        return None

    return ExponentialBackoffRetryPolicy(
        max_attempts=max_attempts,
        initial_interval_ms=10,
        multiplier=2.0,
        max_interval_ms=1_000,
        jitter=jitter,
        budget_ratio=budget_ratio,
        requires_idempotency=requires_idempotency,
        rng=random.Random(42),
        budget=budget or RetryBudget(budget_ratio=budget_ratio, min_floor=10),
        sleep_fn=sleep_fn or _no_sleep,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# RETRY_INV_01 — idempotency required
# ---------------------------------------------------------------------------
def test_inv_idempotency_required_confirms() -> None:
    # Caller explicitly marks idempotent=True — retry proceeds normally.
    p = _policy()
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise TimeoutError("transient")
        return "ok"

    result = asyncio.run(p.execute(flaky, idempotent=True))
    assert result == "ok"
    assert attempts["n"] == 2


def test_inv_idempotency_required_prevents() -> None:
    # requires_idempotency=True and caller did NOT pass idempotent → retry forbidden.
    p = _policy()

    async def flaky() -> str:
        raise TimeoutError("transient")

    with pytest.raises(RetryPolicyInvariantError):
        asyncio.run(p.execute(flaky))


def test_inv_idempotency_required_under_failure() -> None:
    # Under repeated failures, the policy MUST still refuse non-idempotent retries.
    p = _policy()
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        raise ConnectionError("network")

    with pytest.raises(RetryPolicyInvariantError):
        asyncio.run(p.execute(flaky))
    # Attempt count monotonic: exactly one call before refusal.
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# RETRY_INV_02 — retry budget
# ---------------------------------------------------------------------------
def test_inv_retry_budget_confirms() -> None:
    # Budget is admitted and counted; successes increase headroom.
    budget = RetryBudget(budget_ratio=0.5, min_floor=1)
    budget.record_success()
    budget.record_success()
    assert budget.try_admit_retry() is True  # floor 1
    assert budget.try_admit_retry() is True  # ratio allows 1 more
    assert budget.retries == 2


def test_inv_retry_budget_prevents() -> None:
    # Zero successes + zero floor → zero retries allowed.
    budget = RetryBudget(budget_ratio=0.1, min_floor=0)
    assert budget.try_admit_retry() is False
    assert budget.retries == 0


def test_inv_retry_budget_under_failure() -> None:
    # Exhaust budget under sustained failure, policy MUST refuse further retries.
    budget = RetryBudget(budget_ratio=0.0, min_floor=1)
    p = _policy(budget=budget, budget_ratio=0.0)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        raise TimeoutError("boom")

    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(flaky, idempotent=True))
    # First attempt + at most one admitted retry under min_floor=1.
    assert calls["n"] <= 2


# ---------------------------------------------------------------------------
# RETRY_INV_03 — jitter bounded
# ---------------------------------------------------------------------------
def test_inv_jitter_bounded_confirms() -> None:
    p = _policy(jitter=1.0)
    # For attempt=1, base = min(10 * 2^0, 1000) = 10. Delay ∈ [10, 20].
    for _ in range(100):
        d = p.next_delay_ms(1)
        assert 10 <= d <= 20


def test_inv_jitter_bounded_prevents() -> None:
    p = _policy(jitter=0.5)
    # For attempt=2, base = min(10 * 2^1, 1000) = 20. Delay ∈ [20, 30].
    for _ in range(100):
        d = p.next_delay_ms(2)
        assert 20 <= d <= 30


def test_inv_jitter_bounded_under_failure() -> None:
    # Even with adversarial jitter=0, delay equals base (deterministic, nonnegative).
    p = _policy(jitter=0.0)
    for a in (1, 2, 3, 4):
        d = p.next_delay_ms(a)
        assert d >= 0
        # Cap enforced at max_interval_ms=1000.
        assert d <= 1_000


# ---------------------------------------------------------------------------
# RETRY_INV_04 — deadline / TimeoutBudget
# ---------------------------------------------------------------------------
def test_inv_deadline_confirms() -> None:
    # Budget with enough headroom → retry proceeds.
    p = _policy()
    bud = TimeoutBudget(remaining_ms=10_000)
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise TimeoutError("t")
        return "ok"

    result = asyncio.run(p.execute(flaky, idempotent=True, budget=bud))
    assert result == "ok"


def test_inv_deadline_prevents() -> None:
    p = _policy()
    bud = TimeoutBudget(remaining_ms=0)

    async def flaky() -> str:
        raise TimeoutError("t")

    with pytest.raises(RetryPolicyInvariantError):
        asyncio.run(p.execute(flaky, idempotent=True, budget=bud))


def test_inv_deadline_under_failure() -> None:
    # Budget exhausts mid-sequence — retries MUST stop.
    p = _policy(max_attempts=5)
    bud = TimeoutBudget(remaining_ms=1)  # first retry's delay (>=10ms) exhausts it

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        raise TimeoutError("t")

    with pytest.raises((TimeoutError, RetryPolicyInvariantError)):
        asyncio.run(p.execute(flaky, idempotent=True, budget=bud))
    # Policy ran first attempt + possibly one retry; must NOT reach max_attempts=5.
    assert calls["n"] < 5


# ---------------------------------------------------------------------------
# RETRY_INV_05 — classification
# ---------------------------------------------------------------------------
def test_inv_classification_confirms() -> None:
    p = _policy()
    assert p.classify(TimeoutError()) == "retryable"
    assert p.classify(ConnectionError()) == "retryable"
    assert p.classify(OSError()) == "retryable"
    assert p.classify(ValueError()) == "non_retryable"
    assert p.classify(NonRetryableError()) == "non_retryable"
    assert p.classify(FatalError()) == "fatal"


def test_inv_classification_prevents() -> None:
    # Non-retryable / fatal errors MUST never be retried.
    p = _policy()
    calls = {"n": 0}

    async def bad_value() -> str:
        calls["n"] += 1
        raise ValueError("programmer error")

    with pytest.raises(ValueError):
        asyncio.run(p.execute(bad_value, idempotent=True))
    assert calls["n"] == 1  # no retry


def test_inv_classification_under_failure() -> None:
    p = _policy()
    calls = {"n": 0}

    async def fatal() -> str:
        calls["n"] += 1
        raise FatalError("boom")

    with pytest.raises(FatalError):
        asyncio.run(p.execute(fatal, idempotent=True))
    assert calls["n"] == 1
