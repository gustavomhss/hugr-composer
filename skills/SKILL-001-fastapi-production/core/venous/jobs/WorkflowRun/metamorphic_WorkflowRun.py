"""Metamorphic + differential tests for WorkflowRun."""

from __future__ import annotations

import asyncio

from WorkflowRun import IdReusePolicy, InMemoryWorkflowClient, RunStatus


def test_metamorphic_describe_is_pure() -> None:
    c = InMemoryWorkflowClient()
    r = asyncio.run(c.start("T", "w-1", "q", args=()))
    for _ in range(10):
        assert asyncio.run(c.describe("w-1")) == r


def test_metamorphic_history_append_only() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    prev = c.history_of("w-1")
    c.schedule_activity("w-1", "A")
    now = c.history_of("w-1")
    # History length strictly grows.
    assert len(now) == len(prev) + 1
    # Every previously recorded event is preserved at the same index.
    for i, ev in enumerate(prev):
        assert now[i] == ev


def test_differential_reuse_vs_reject_policy() -> None:
    c_reuse = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REUSE_EXISTING)
    asyncio.run(c_reuse.start("T", "w-1", "q", args=()))
    r2 = asyncio.run(c_reuse.start("T", "w-1", "q", args=()))
    # REUSE returns the same run; history unchanged.
    assert c_reuse.status_of("w-1") is RunStatus.OPEN
    assert len(c_reuse.all_runs_of("w-1")) == 1
    assert r2.run_id == c_reuse.all_runs_of("w-1")[0].run_id


def test_metamorphic_replay_deterministic_across_calls() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.schedule_activity("w-1", "A")
    c.schedule_activity("w-1", "B")
    c.complete("w-1")
    t1 = c.replay("w-1")
    t2 = c.replay("w-1")
    t3 = c.replay("w-1")
    assert t1 == t2 == t3


def test_metamorphic_run_ids_monotone_fresh() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    run_ids: list[str] = []
    for _ in range(5):
        r = asyncio.run(c.start("T", "w-1", "q", args=()))
        run_ids.append(r.run_id)
    # All distinct.
    assert len(set(run_ids)) == 5
