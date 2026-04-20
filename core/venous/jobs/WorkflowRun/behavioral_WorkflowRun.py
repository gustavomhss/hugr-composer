"""Behavioral end-to-end scenarios for WorkflowRun."""

from __future__ import annotations

import asyncio

import pytest

from WorkflowRun import (
    IdReusePolicy,
    InMemoryWorkflowClient,
    RunStatus,
    WorkflowAlreadyRunningError,
    WorkflowClosedError,
)


def test_scenario_order_shipping_end_to_end() -> None:
    c = InMemoryWorkflowClient()
    run = asyncio.run(c.start("ShipOrder", "order-42", "orders", args=(42,)))
    assert run.run_id.startswith("run-")
    c.schedule_activity("order-42", "ChargeCard")
    c.schedule_activity("order-42", "ReserveStock")
    c.schedule_activity("order-42", "NotifyCustomer")
    c.complete("order-42")
    assert c.status_of("order-42") is RunStatus.COMPLETED
    assert [e.kind for e in c.history_of("order-42")] == [
        "started", "activity_scheduled", "activity_scheduled",
        "activity_scheduled", "completed",
    ]


def test_scenario_reject_policy_blocks_duplicate_start() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.REJECT)
    asyncio.run(c.start("T", "w-1", "q", args=()))
    with pytest.raises(WorkflowAlreadyRunningError):
        asyncio.run(c.start("T", "w-1", "q", args=()))


def test_scenario_terminate_then_rerun_allocates_new_run_id() -> None:
    c = InMemoryWorkflowClient(id_reuse=IdReusePolicy.TERMINATE_EXISTING)
    r1 = asyncio.run(c.start("T", "w-1", "q", args=()))
    r2 = asyncio.run(c.start("T", "w-1", "q", args=()))
    assert r1.run_id != r2.run_id


def test_scenario_cancel_closed_run_refused() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    asyncio.run(c.cancel("w-1"))
    with pytest.raises(WorkflowClosedError):
        asyncio.run(c.cancel("w-1"))


def test_scenario_describe_returns_consistent_run() -> None:
    c = InMemoryWorkflowClient()
    r = asyncio.run(c.start("T", "w-1", "q", args=()))
    out = asyncio.run(c.describe("w-1"))
    assert out == r


def test_scenario_failure_preserves_history() -> None:
    c = InMemoryWorkflowClient()
    asyncio.run(c.start("T", "w-1", "q", args=()))
    c.schedule_activity("w-1", "SendEmail")
    c.fail("w-1", "smtp down")
    history = c.history_of("w-1")
    assert [e.kind for e in history] == ["started", "activity_scheduled", "failed"]
    assert dict(history[-1].attributes)["reason"] == "smtp down"
