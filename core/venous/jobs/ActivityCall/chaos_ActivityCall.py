"""Chaos / fault-injection for ActivityCall."""

from __future__ import annotations

import asyncio

import pytest

from ActivityCall import (
    ActivityCall,
    ActivityCallError,
    ActivityMaxAttemptsExceededError,
    InMemoryActivityExecutor,
    RetryPolicy,
)


def test_chaos_unknown_activity_rejected() -> None:
    ex = InMemoryActivityExecutor()
    call = ActivityCall(name="Unknown", task_queue="q", start_to_close_s=1,
                        schedule_to_close_s=60, heartbeat_s=None,
                        retry=RetryPolicy(0.0, 1.0, 1), args=())
    with pytest.raises(ActivityCallError):
        asyncio.run(ex.execute(call))


def test_chaos_bad_retry_policy_rejected() -> None:
    with pytest.raises(ActivityCallError):
        RetryPolicy(-1.0, 2.0, 3)
    with pytest.raises(ActivityCallError):
        RetryPolicy(0.1, 0.5, 3)


def test_chaos_zero_start_to_close_rejected() -> None:
    with pytest.raises(ActivityCallError):
        ActivityCall(name="x", task_queue="q", start_to_close_s=0,
                     schedule_to_close_s=None, heartbeat_s=None,
                     retry=RetryPolicy(0.0, 1.0, 1), args=())


def test_chaos_handler_raises_non_runtime_exception() -> None:
    ex = InMemoryActivityExecutor()

    async def fail(_a: tuple[object, ...]) -> str:
        raise ValueError("semantic")

    ex.register("V", fail)
    call = ActivityCall(name="V", task_queue="q", start_to_close_s=2,
                        schedule_to_close_s=60, heartbeat_s=None,
                        retry=RetryPolicy(0.0, 1.0, 2), args=())
    with pytest.raises(ActivityMaxAttemptsExceededError):
        asyncio.run(ex.execute(call))


def test_chaos_heartbeat_missed_and_then_success() -> None:
    ex = InMemoryActivityExecutor()
    attempts: list[int] = []

    async def slow_then_ok(_a: tuple[object, ...]) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            await asyncio.sleep(5)
        return "ok"

    ex.register("ST", slow_then_ok)
    call = ActivityCall(name="ST", task_queue="q", start_to_close_s=1,
                        schedule_to_close_s=60, heartbeat_s=1,
                        retry=RetryPolicy(0.0, 1.0, 3), args=())
    out = asyncio.run(ex.execute(call))
    assert out == "ok"


def test_chaos_concurrent_registered_activities_no_interference() -> None:
    ex = InMemoryActivityExecutor()

    async def ok(_a: tuple[object, ...]) -> str:
        return "ok"

    for name in ("A", "B"):
        ex.register(name, ok)
    call = lambda n: ActivityCall(  # noqa: E731 — terse factory
        name=n, task_queue="q", start_to_close_s=2,
        schedule_to_close_s=60, heartbeat_s=None,
        retry=RetryPolicy(0.0, 1.0, 1), args=(),
    )

    async def run() -> list[str]:
        return list(await asyncio.gather(ex.execute(call("A")), ex.execute(call("B"))))

    assert sorted(asyncio.run(run())) == ["ok", "ok"]
