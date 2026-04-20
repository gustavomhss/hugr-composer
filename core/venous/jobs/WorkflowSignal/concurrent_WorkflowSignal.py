"""Concurrency tests for WorkflowSignal."""

from __future__ import annotations

import asyncio

from WorkflowSignal import (
    InMemorySignalSender,
    WorkflowSignal,
)


def test_concurrent_send_all_signals_recorded() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")

    async def run() -> None:
        await asyncio.gather(*(
            s.send(WorkflowSignal(workflow_id="w-1", name=f"s{i}", payload=None))
            for i in range(100)
        ))

    asyncio.run(run())
    signals = [e for e in s.history_of("w-1") if e[1] == "signal"]
    assert len(signals) == 100


def test_concurrent_send_to_different_workflows_isolated() -> None:
    s = InMemorySignalSender()
    for i in range(10):
        s.register_open(f"w-{i}", "T", "q")

    async def run() -> None:
        await asyncio.gather(*(
            s.send(WorkflowSignal(workflow_id=f"w-{i}", name="sig", payload=None))
            for i in range(10)
        ))

    asyncio.run(run())
    for i in range(10):
        sigs = [e for e in s.history_of(f"w-{i}") if e[1] == "signal"]
        assert len(sigs) == 1


def test_concurrent_send_with_start_races_one_new_run() -> None:
    s = InMemorySignalSender()
    run_ids: list[str] = []

    async def racer() -> None:
        rid = await s.send_with_start(
            WorkflowSignal(workflow_id="w-new", name="sig", payload=None),
            workflow_type="T", task_queue="q",
        )
        run_ids.append(rid)

    async def run() -> None:
        await asyncio.gather(*(racer() for _ in range(20)))

    asyncio.run(run())
    # All 20 saw the SAME run_id — because after the first won the race,
    # subsequent calls reused the existing open run (WFS-INV-04).
    assert len(set(run_ids)) == 1


def test_concurrent_seq_numbers_strict_total_order() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")

    async def run() -> None:
        await asyncio.gather(*(
            s.send(WorkflowSignal(workflow_id="w-1", name=f"n{i}", payload=None))
            for i in range(50)
        ))

    asyncio.run(run())
    seqs = [seq for seq, _, _ in s.history_of("w-1")]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
