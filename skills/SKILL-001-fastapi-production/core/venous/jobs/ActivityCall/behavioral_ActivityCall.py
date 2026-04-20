"""Behavioral end-to-end scenarios for ActivityCall."""

from __future__ import annotations

import asyncio

import pytest

from ActivityCall import (
    ActivityCall,
    ActivityMaxAttemptsExceededError,
    InMemoryActivityExecutor,
    RetryPolicy,
)


def _policy(n: int = 3) -> RetryPolicy:
    return RetryPolicy(initial_interval_s=0.0, backoff_coefficient=2.0, maximum_attempts=n)


def _call(name: str, max_attempts: int = 3, start_to_close_s: int = 2) -> ActivityCall:
    return ActivityCall(name=name, task_queue="q", start_to_close_s=start_to_close_s,
                        schedule_to_close_s=60, heartbeat_s=1,
                        retry=_policy(max_attempts), args=())


def test_scenario_charge_card_idempotent_retry() -> None:
    ex = InMemoryActivityExecutor()
    charges: list[int] = []

    async def charge(_a: tuple[object, ...]) -> str:
        charges.append(1)
        if len(charges) < 2:
            raise RuntimeError("gateway blip")
        return "receipt-123"

    ex.register("Charge", charge)
    out = asyncio.run(ex.execute(_call("Charge")))
    assert out == "receipt-123"
    assert len(charges) == 2


def test_scenario_permanent_failure_escalates_to_workflow() -> None:
    ex = InMemoryActivityExecutor()

    async def fail(_a: tuple[object, ...]) -> str:
        raise RuntimeError("permanent")

    ex.register("Fail", fail)
    with pytest.raises(ActivityMaxAttemptsExceededError):
        asyncio.run(ex.execute(_call("Fail")))


def test_scenario_attempt_log_ordered_and_bounded() -> None:
    ex = InMemoryActivityExecutor()
    attempts: list[int] = []

    async def flaky(_a: tuple[object, ...]) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("blip")
        return "ok"

    ex.register("Flaky", flaky)
    asyncio.run(ex.execute(_call("Flaky")))
    records = ex.attempts_for_latest("Flaky")
    assert [r.outcome for r in records] == ["failure", "failure", "success"]


def test_scenario_parallel_activities_independent() -> None:
    ex = InMemoryActivityExecutor()

    async def mk_handler(tag: str):  # type: ignore[no-untyped-def] — test helper
        async def _h(_a: tuple[object, ...]) -> str:
            return tag
        return _h

    async def setup_and_run() -> list[str]:
        for t in ("A", "B", "C"):
            ex.register(t, await mk_handler(t))
        return list(await asyncio.gather(*(
            ex.execute(_call(t)) for t in ("A", "B", "C")
        )))

    out = asyncio.run(setup_and_run())
    assert set(out) == {"A", "B", "C"}


def test_scenario_heartbeat_missed_counted_as_attempt() -> None:
    ex = InMemoryActivityExecutor()

    async def slow(_a: tuple[object, ...]) -> str:
        await asyncio.sleep(5)
        return "late"

    ex.register("Slow", slow)
    with pytest.raises(ActivityMaxAttemptsExceededError):
        asyncio.run(ex.execute(_call("Slow", max_attempts=2, start_to_close_s=1)))
    records = ex.attempts_for_latest("Slow")
    assert [r.outcome for r in records] == ["heartbeat_missed", "heartbeat_missed"]
