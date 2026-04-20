"""Concurrency tests for ActivityCall."""

from __future__ import annotations

import asyncio

from ActivityCall import (
    ActivityCall,
    InMemoryActivityExecutor,
    RetryPolicy,
)


def test_concurrent_executes_isolated_between_activities() -> None:
    ex = InMemoryActivityExecutor()

    async def mk(tag: str):  # type: ignore[no-untyped-def] — test helper
        async def _h(_a: tuple[object, ...]) -> str:
            await asyncio.sleep(0)
            return tag
        return _h

    async def run() -> list[str]:
        for t in ("A", "B", "C", "D"):
            ex.register(t, await mk(t))
        call = lambda name: ActivityCall(  # noqa: E731 — terse factory for test
            name=name, task_queue="q", start_to_close_s=2,
            schedule_to_close_s=60, heartbeat_s=None,
            retry=RetryPolicy(0.0, 1.0, 1), args=(),
        )
        return list(await asyncio.gather(*(ex.execute(call(t)) for t in ("A", "B", "C", "D"))))

    out = asyncio.run(run())
    assert sorted(out) == ["A", "B", "C", "D"]


def test_concurrent_same_activity_name_retries_independent() -> None:
    ex = InMemoryActivityExecutor()
    attempts: dict[int, int] = {}

    async def flaky(a: tuple[object, ...]) -> str:
        i = int(a[0])
        attempts[i] = attempts.get(i, 0) + 1
        if attempts[i] < 2:
            raise RuntimeError("blip")
        return f"ok-{i}"

    ex.register("F", flaky)

    async def run() -> list[str]:
        call = lambda i: ActivityCall(  # noqa: E731 — terse factory
            name="F", task_queue="q", start_to_close_s=2,
            schedule_to_close_s=60, heartbeat_s=None,
            retry=RetryPolicy(0.0, 1.0, 3), args=(i,),
        )
        return list(await asyncio.gather(*(ex.execute(call(i)) for i in range(5))))

    out = asyncio.run(run())
    assert sorted(out) == [f"ok-{i}" for i in range(5)]


def test_concurrent_executor_bounded_attempts() -> None:
    ex = InMemoryActivityExecutor()

    async def always_fail(_a: tuple[object, ...]) -> str:
        raise RuntimeError("x")

    ex.register("F", always_fail)

    async def run() -> None:
        tasks = [asyncio.create_task(ex.execute(ActivityCall(
            name="F", task_queue="q", start_to_close_s=1,
            schedule_to_close_s=60, heartbeat_s=None,
            retry=RetryPolicy(0.0, 1.0, 2), args=(),
        ))) for _ in range(10)]
        for t in tasks:
            try:
                await t
            except Exception:  # noqa: BLE001 — expected terminal
                pass

    asyncio.run(run())
    # Each of 10 failing activities used exactly 2 attempts (AC-INV-04).
    # We verify the LATEST attempts-for match; the count is 2.
    records = ex.attempts_for_latest("F")
    assert len(records) == 2
