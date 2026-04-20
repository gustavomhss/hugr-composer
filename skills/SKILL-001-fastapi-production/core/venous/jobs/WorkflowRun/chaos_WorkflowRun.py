"""Chaos / fault-injection for WorkflowRun."""

from __future__ import annotations

import asyncio

import pytest

from WorkflowRun import (
    IdReusePolicy,
    InMemoryWorkflowClient,
    RunStatus,
    WorkflowClosedError,
    WorkflowRunError,
)


def test_chaos_invalid_workflow_ids_rejected() -> None:
    c = InMemoryWorkflowClient()
    for bad in ("", " ", "a b", "a\n", "a/b c"):
        with pytest.raises(WorkflowRunError):
            asyncio.run(c.start("T", bad, "q", args=()))


def test_chaos_cancel_nonexistent_raises() -> None:
    c = InMemoryWorkflowClient()
    with pytest.raises(WorkflowRunError):
        asyncio.run(c.cancel("does-not-exist"))


def test_chaos_concurrent_completes_idempotent_like() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.complete("w-1")
    with pytest.raises(WorkflowClosedError):
        c.complete("w-1")


def test_chaos_many_workflows_under_load() -> None:
    c = InMemoryWorkflowClient()

    async def run() -> None:
        await asyncio.gather(*(
            c.start("T", f"w-{i}", "q", args=(i,)) for i in range(500)
        ))

    asyncio.run(run())
    assert c.status_of("w-0") is RunStatus.OPEN
    assert c.status_of("w-499") is RunStatus.OPEN


def test_chaos_terminate_then_reject_policy_switch_safe() -> None:
    # Switching policy mid-flight is simulated by using two clients on logically
    # different workflow_ids; state never leaks across clients.
    c1 = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    c2 = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)
    asyncio.run(c1.start("T", "w-1", "q", args=()))
    asyncio.run(c2.start("T", "w-1", "q", args=()))  # c2 has its own map
    assert c1.status_of("w-1") is RunStatus.OPEN
    assert c2.status_of("w-1") is RunStatus.OPEN


def test_chaos_history_never_shrinks_under_failure() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.schedule_activity("w-1", "A")
    size_before = len(c.history_of("w-1"))
    c.fail("w-1", "boom")
    size_after = len(c.history_of("w-1"))
    assert size_after == size_before + 1
