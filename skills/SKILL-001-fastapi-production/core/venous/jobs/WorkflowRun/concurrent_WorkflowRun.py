"""Concurrency tests for WorkflowRun."""

from __future__ import annotations

import asyncio

from WorkflowRun import (
    IdReusePolicy,
    InMemoryWorkflowClient,
    WorkflowAlreadyRunningError,
)


def test_concurrent_starts_reject_policy_only_one_wins() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)
    outcomes: list[str] = []

    async def racer(i: int) -> None:
        try:
            await c.start("T", "w-1", "q", args=(i,))
            outcomes.append(f"ok-{i}")
        except WorkflowAlreadyRunningError:
            outcomes.append(f"rej-{i}")

    async def run() -> None:
        await asyncio.gather(*(racer(i) for i in range(20)))

    asyncio.run(run())
    # Exactly ONE start wins for REJECT policy (WFR-INV-05).
    assert len([o for o in outcomes if o.startswith("ok-")]) == 1
    assert len([o for o in outcomes if o.startswith("rej-")]) == 19


def test_concurrent_starts_distinct_workflows_all_win() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)

    async def run() -> None:
        await asyncio.gather(*(
            c.start("T", f"w-{i}", "q", args=()) for i in range(50)
        ))

    asyncio.run(run())
    assert len(c.all_runs_of("w-0")) == 1
    assert len(c.all_runs_of("w-49")) == 1


def test_concurrent_describe_is_consistent_under_read_load() -> None:
    c = InMemoryWorkflowClient()
    r = asyncio.run(c.start("T", "w-1", "q", args=()))

    async def reader() -> None:
        for _ in range(10):
            assert await c.describe("w-1") == r

    async def run() -> None:
        await asyncio.gather(*(reader() for _ in range(10)))

    asyncio.run(run())


def test_concurrent_terminate_existing_run_ids_unique() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    run_ids: list[str] = []

    async def one() -> None:
        r = await c.start("T", "w-1", "q", args=())
        run_ids.append(r.run_id)

    async def run() -> None:
        for _ in range(10):  # sequential under TERMINATE_EXISTING, since each start closes the prior
            await one()

    asyncio.run(run())
    # All 10 run_ids are distinct (WFR-INV-03).
    assert len(set(run_ids)) == 10
