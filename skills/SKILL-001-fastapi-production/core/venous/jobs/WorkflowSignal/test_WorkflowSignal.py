"""Unit tests for WorkflowSignal — three per invariant."""

from __future__ import annotations

import asyncio

import pytest

from WorkflowSignal import (
    MAX_PAYLOAD_BYTES,
    InMemorySignalSender,
    WorkflowNotFoundError,
    WorkflowSignal,
    WorkflowSignalError,
)


# ---------------------------------------------------------------------------
# WFS_INV_01 — signal recorded as event before delivered
# ---------------------------------------------------------------------------
def test_inv_signal_recorded_confirms() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="cancel", payload=None)))
    history = s.history_of("w-1")
    assert any(kind == "signal" and name == "cancel" for _seq, kind, name in history)


def test_inv_signal_recorded_prevents() -> None:
    # Empty name rejected at construction.
    with pytest.raises(WorkflowSignalError, match="WFS-INV-01"):
        WorkflowSignal(workflow_id="w-1", name="", payload=None)
    with pytest.raises(WorkflowSignalError, match="WFS-INV-01"):
        WorkflowSignal(workflow_id="", name="cancel", payload=None)


def test_inv_signal_recorded_under_failure() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    # Oversize payload rejected (WFS-INV-01 supporting).
    big = b"x" * (MAX_PAYLOAD_BYTES + 1)
    with pytest.raises(WorkflowSignalError):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="big", payload=big)))
    # No event was recorded.
    assert not any(name == "big" for _, kind, name in s.history_of("w-1"))


# ---------------------------------------------------------------------------
# WFS_INV_02 — sender cannot observe a return value (fire-and-forget)
# ---------------------------------------------------------------------------
def test_inv_fire_and_forget_confirms() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    out = asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="x", payload=None)))
    assert out is None


def test_inv_fire_and_forget_prevents() -> None:
    # Protocol method `send` is typed as returning None; the surface has no
    # `send_and_await_reply` / `call` method.
    s = InMemorySignalSender()
    public = {m for m in dir(s) if not m.startswith("_")}
    for forbidden in ("send_and_wait", "call", "request_reply", "rpc"):
        assert forbidden not in public


def test_inv_fire_and_forget_under_failure() -> None:
    # send_with_start does return a str (run_id), but send does not.
    s = InMemorySignalSender()
    run_id = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="w-new", name="init", payload=None),
        workflow_type="T", task_queue="q",
    ))
    assert isinstance(run_id, str)


# ---------------------------------------------------------------------------
# WFS_INV_03 — signals to closed workflows rejected
# ---------------------------------------------------------------------------
def test_inv_closed_rejected_confirms() -> None:
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    s.close("w-1")
    with pytest.raises(WorkflowNotFoundError, match="WFS-INV-03"):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="x", payload=None)))


def test_inv_closed_rejected_prevents() -> None:
    s = InMemorySignalSender()
    # Workflow never started — NOT a closed run, but still rejected.
    with pytest.raises(WorkflowNotFoundError, match="WFS-INV-03"):
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-ghost", name="x", payload=None)))


def test_inv_closed_rejected_under_failure() -> None:
    # Signal to closed workflow MUST NOT start it via `send` alone.
    s = InMemorySignalSender()
    s.register_open("w-1", "T", "q")
    s.close("w-1")
    try:
        asyncio.run(s.send(WorkflowSignal(workflow_id="w-1", name="x", payload=None)))
    except WorkflowNotFoundError:
        pass
    # History of closed w-1 MUST remain unchanged post-reject.
    assert all(name != "x" for _, kind, name in s.history_of("w-1"))


# ---------------------------------------------------------------------------
# WFS_INV_04 — send_with_start is atomic
# ---------------------------------------------------------------------------
def test_inv_send_with_start_atomic_confirms() -> None:
    s = InMemorySignalSender()
    run_id = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="w-new", name="init", payload=None),
        workflow_type="T", task_queue="q",
    ))
    assert isinstance(run_id, str)
    # Both started AND signal recorded atomically.
    kinds = [kind for _, kind, _ in s.history_of("w-new")]
    assert "started" in kinds
    assert "signal" in kinds


def test_inv_send_with_start_atomic_prevents() -> None:
    s = InMemorySignalSender()
    # Invalid workflow_type rejected BEFORE any state change.
    with pytest.raises(WorkflowSignalError, match="WFS-INV-04"):
        asyncio.run(s.send_with_start(
            WorkflowSignal(workflow_id="w-new", name="init", payload=None),
            workflow_type="", task_queue="q",
        ))
    # w-new was never created.
    with pytest.raises(WorkflowNotFoundError):
        s.status_of("w-new")


def test_inv_send_with_start_atomic_under_failure() -> None:
    s = InMemorySignalSender()
    # If workflow already open, send_with_start reuses the run_id.
    existing_run = s.register_open("w-1", "T", "q")
    run_id = asyncio.run(s.send_with_start(
        WorkflowSignal(workflow_id="w-1", name="append", payload=None),
        workflow_type="T", task_queue="q",
    ))
    assert run_id == existing_run


# ---------------------------------------------------------------------------
# WFS_INV_05 — handler must follow the same determinism rules
# ---------------------------------------------------------------------------
def test_inv_deterministic_handler_confirms() -> None:
    # The signal contract refuses non-serialisable payloads (objects).
    class NonSerialisable:
        pass

    with pytest.raises(WorkflowSignalError, match="WFS-INV-05"):
        InMemorySignalSender._validate_payload(NonSerialisable())  # type: ignore[attr-defined]


def test_inv_deterministic_handler_prevents() -> None:
    # File handles, open sockets — any non-serialisable type is refused.
    import io
    s = io.StringIO()
    try:
        with pytest.raises(WorkflowSignalError, match="WFS-INV-05"):
            InMemorySignalSender._validate_payload(s)  # type: ignore[attr-defined]
    finally:
        s.close()


def test_inv_deterministic_handler_under_failure() -> None:
    # Valid serialisable payloads are accepted.
    for payload in (None, True, 42, 3.14, "ok", b"bytes", [1, 2], {"k": "v"}, (1, 2, 3)):
        InMemorySignalSender._validate_payload(payload)  # type: ignore[attr-defined]
