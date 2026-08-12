"""Concurrency / linearizability harness for RetryPolicy.

Confirms the shared RetryBudget is safe under concurrent admission attempts
(no budget overrun under race) and that parallel execute() calls respect the
budget ceiling without corrupting the attempt log.
"""

from __future__ import annotations

import asyncio
import random
import threading

from RetryPolicy import (
    ExponentialBackoffRetryPolicy,
    RetryBudget,
    RetryPolicyInvariantError,
)


async def _no_sleep(_s: float) -> None:
    return None


def test_concurrent_budget_admission_never_overruns() -> None:
    # With min_floor=5 and zero successes, at most 5 retries are admitted
    # across any number of racing threads.
    budget = RetryBudget(budget_ratio=0.0, min_floor=5)
    admissions: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(50):
            if budget.try_admit_retry():
                with lock:
                    admissions.append(1)

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(admissions) == 5
    assert budget.retries == 5


def test_concurrent_executes_share_budget() -> None:
    # Two parallel execute() coroutines share one RetryBudget.
    budget = RetryBudget(budget_ratio=0.0, min_floor=2)
    p = ExponentialBackoffRetryPolicy(
        max_attempts=10,
        initial_interval_ms=1,
        multiplier=2.0,
        max_interval_ms=10,
        jitter=0.0,
        budget_ratio=0.0,
        requires_idempotency=True,
        rng=random.Random(3),
        sleep_fn=_no_sleep,
        budget=budget,
    )

    async def fail() -> str:
        raise TimeoutError("t")

    async def driver() -> None:
        tasks = [
            asyncio.create_task(p.execute(fail, idempotent=True))
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # All tasks raised; budget capped admissions.
        for r in results:
            assert isinstance(r, (TimeoutError, RetryPolicyInvariantError))

    asyncio.run(driver())
    assert budget.retries <= 2


def test_concurrent_success_accounting_linearizable() -> None:
    # Many concurrent success + retry attempts — total counts are correct.
    budget = RetryBudget(budget_ratio=1.0, min_floor=0)

    def success_worker() -> None:
        for _ in range(100):
            budget.record_success()

    def retry_worker() -> None:
        for _ in range(100):
            budget.try_admit_retry()

    ts = (
        [threading.Thread(target=success_worker) for _ in range(5)]
        + [threading.Thread(target=retry_worker) for _ in range(5)]
    )
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    # Successes exactly 500; retries CANNOT exceed successes (ratio=1.0, floor=0).
    assert budget.successes == 500
    assert budget.retries <= budget.successes


def test_concurrent_attempts_log_never_exceeds_capacity() -> None:
    # The attempts_log deque has maxlen=1024 — bounded under load.
    p = ExponentialBackoffRetryPolicy(
        max_attempts=2,
        initial_interval_ms=0,
        multiplier=1.0,
        max_interval_ms=0,
        jitter=0.0,
        budget_ratio=1.0,
        requires_idempotency=False,
        rng=random.Random(0),
        sleep_fn=_no_sleep,
        budget=RetryBudget(budget_ratio=1.0, min_floor=10_000),
    )

    async def ok() -> str:
        return "x"

    async def driver() -> None:
        await asyncio.gather(*[p.execute(ok) for _ in range(2_000)])

    asyncio.run(driver())
    assert len(p.attempts_log) <= 1024
