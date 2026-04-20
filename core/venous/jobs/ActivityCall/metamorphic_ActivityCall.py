"""Metamorphic + differential tests for ActivityCall."""

from __future__ import annotations

import asyncio

from ActivityCall import (
    ActivityCall,
    InMemoryActivityExecutor,
    RetryPolicy,
    retry_delay_s,
)


def test_metamorphic_retry_delay_monotone_nondecreasing() -> None:
    p = RetryPolicy(initial_interval_s=1.0, backoff_coefficient=1.5, maximum_attempts=5)
    delays = [retry_delay_s(p, i) for i in range(1, 6)]
    for i in range(1, len(delays)):
        assert delays[i] >= delays[i - 1]


def test_metamorphic_retry_delay_zero_initial_stays_zero() -> None:
    p = RetryPolicy(initial_interval_s=0.0, backoff_coefficient=10.0, maximum_attempts=5)
    for i in range(1, 6):
        assert retry_delay_s(p, i) == 0.0


def test_differential_two_executors_same_handler_same_result() -> None:
    async def ok(_a: tuple[object, ...]) -> str:
        return "same"

    a = InMemoryActivityExecutor()
    b = InMemoryActivityExecutor()
    a.register("x", ok); b.register("x", ok)
    call = ActivityCall(name="x", task_queue="q", start_to_close_s=2,
                        schedule_to_close_s=60, heartbeat_s=None,
                        retry=RetryPolicy(0.0, 1.0, 1), args=())
    assert asyncio.run(a.execute(call)) == asyncio.run(b.execute(call))


def test_metamorphic_success_on_first_attempt_records_one_record() -> None:
    ex = InMemoryActivityExecutor()

    async def ok(_a: tuple[object, ...]) -> str:
        return "done"

    ex.register("ok", ok)
    call = ActivityCall(name="ok", task_queue="q", start_to_close_s=2,
                        schedule_to_close_s=60, heartbeat_s=None,
                        retry=RetryPolicy(0.0, 1.0, 5), args=())
    asyncio.run(ex.execute(call))
    assert len(ex.attempts_for_latest("ok")) == 1


def test_metamorphic_failure_records_equal_max_attempts() -> None:
    ex = InMemoryActivityExecutor()

    async def fail(_a: tuple[object, ...]) -> str:
        raise RuntimeError("x")

    ex.register("fail", fail)
    call = ActivityCall(name="fail", task_queue="q", start_to_close_s=2,
                        schedule_to_close_s=60, heartbeat_s=None,
                        retry=RetryPolicy(0.0, 1.0, 3), args=())
    try:
        asyncio.run(ex.execute(call))
    except Exception:  # noqa: BLE001 — expected
        pass
    assert len(ex.attempts_for_latest("fail")) == 3
