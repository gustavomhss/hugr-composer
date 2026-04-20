"""Metamorphic + differential tests for WorkflowSignal."""

from __future__ import annotations

import asyncio

from WorkflowSignal import (
    InMemorySignalSender,
    WorkflowSignal,
)


def test_metamorphic_history_grows_on_send() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    for n in range(1, 11):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name=f"s{n}", payload=None)))
        signals = [e for e in s.history_of("w-1") if e[1] == "signal"]
        assert len(signals) == n


def test_metamorphic_send_with_start_idempotent_on_open_run() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    first = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="w-1", name="x", payload=None),
        workflow_type="T", task_queue="q",
    ))
    second = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="w-1", name="y", payload=None),
        workflow_type="T", task_queue="q",
    ))
    assert first == second  # same run_id — existing open reused


def test_differential_two_senders_same_final_history() -> None:
    a = InMemorySignalSender(); b = InMemorySignalSender()
    for s in (a, b):
        s.register_open("w-1", "T", "q")
        for n in ("x", "y", "z"):
            asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name=n, payload=None)))
    assert [e[1:] for e in a.history_of("w-1")] == [e[1:] for e in b.history_of("w-1")]


def test_metamorphic_seq_monotone() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    for i in range(5):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name=f"s{i}", payload=None)))
    seqs = [seq for seq, _, _ in s.history_of("w-1")]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_metamorphic_payload_none_treated_as_no_payload() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="p", payload=None)))
    # Still recorded.
    assert any(k == "signal" for _, k, _ in s.history_of("w-1"))
