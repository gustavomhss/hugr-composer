"""Behavioral end-to-end scenarios for WorkflowSignal."""

from __future__ import annotations

import asyncio

import pytest

from WorkflowSignal import (
    InMemorySignalSender,
    WorkflowNotFoundError,
    WorkflowSignal,
)


def test_scenario_user_cancels_via_signal() -> None:
    s = InMemorySignalSender()
    s.register_open("order-42", "ShipOrder", "orders")
    asyncio.run(s.send(WorkflowSignal(
        workflow_id="order-42", name="cancel_requested", payload={"reason": "user"},
    )))
    kinds = [k for _, k, _ in s.history_of("order-42")]
    assert "signal" in kinds


def test_scenario_signal_with_start_creates_run() -> None:
    s = InMemorySignalSender()
    run_id = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="new-1", name="init", payload=None),
        workflow_type="T", task_queue="q",
    ))
    assert s.status_of("new-1") == "open"
    assert run_id.startswith("run-")


def test_scenario_signal_to_closed_workflow_rejected() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    s.close("w-1")
    with pytest.raises(WorkflowNotFoundError):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="x", payload=None)))


def test_scenario_many_signals_preserve_order() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    for n in ("a", "b", "c", "d", "e"):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name=n, payload=None)))
    signal_names = [name for _, kind, name in s.history_of("w-1") if kind == "signal"]
    assert signal_names == ["a", "b", "c", "d", "e"]


def test_scenario_payload_types_accepted() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    for payload in (None, True, 42, "text", b"bytes", [1, 2], {"k": "v"}):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="p", payload=payload)))
