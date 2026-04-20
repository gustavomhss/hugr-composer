"""Unit tests for SagaOrchestrator — three per invariant (confirms/prevents/under_failure)."""

from __future__ import annotations

import threading

import pytest

from SagaOrchestrator import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    CompensationOrderError,
    InMemorySagaOrchestrator,
    SagaDefinition,
    SagaDefinitionError,
    SagaOrchestratorInvariantError,
    UnknownSagaError,
)


def _three_step_saga(
    trace: list[str] | None = None,
) -> tuple[SagaDefinition, list[str]]:
    log: list[str] = [] if trace is None else trace
    sd = SagaDefinition("order-saga")

    @sd.register("reserve_stock", compensator=lambda p: log.append(f"undo_reserve:{p}"))
    def h1(payload: object) -> object:
        log.append(f"reserve_stock:{payload}")
        return payload

    @sd.register("charge_card", compensator=lambda p: log.append(f"refund:{p}"))
    def h2(payload: object) -> object:
        log.append(f"charge_card:{payload}")
        return payload

    @sd.register("ship_order", compensator=lambda p: log.append(f"cancel_ship:{p}"))
    def h3(payload: object) -> object:
        log.append(f"ship_order:{payload}")
        return payload

    return sd, log


# ---------------------------------------------------------------------------
# SAGA_INV_01 — every forward step MUST declare a compensator
# ---------------------------------------------------------------------------
def test_inv_compensator_required_confirms() -> None:
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c1", {"order": 1})
    saga.step("c1", "reserve_stock", {"ok": True})
    saga.step("c1", "charge_card", {"ok": True})
    saga.step("c1", "ship_order", {"ok": True})
    state, done = saga.status("c1")
    assert state == STATE_COMPLETED
    assert list(done) == ["reserve_stock", "charge_card", "ship_order"]


def test_inv_compensator_required_prevents() -> None:
    sd = SagaDefinition("bad")
    with pytest.raises(SagaDefinitionError):
        sd.register("s1", compensator=None)(lambda p: p)  # type: ignore[arg-type]


def test_inv_compensator_required_under_failure() -> None:
    sd = SagaDefinition("has-step")
    sd.register("s1", compensator=lambda p: None)(lambda p: p)
    # Repeated registration of the same step name is forbidden (SAGA-INV-01).
    with pytest.raises(SagaDefinitionError):
        sd.register("s1", compensator=lambda p: None)(lambda p: p)


# ---------------------------------------------------------------------------
# SAGA_INV_02 — compensation order is reverse of completed forward steps
# ---------------------------------------------------------------------------
def test_inv_reverse_compensation_confirms() -> None:
    sd, log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c2", {"order": 1})
    saga.step("c2", "reserve_stock", {"ok": True})
    saga.step("c2", "charge_card", {"ok": True})
    # Now ship_order fails → compensators must run in reverse.
    saga.step("c2", "ship_order", {"__saga_failed__": True, "reason": "carrier down"})
    state, done = saga.status("c2")
    assert state == STATE_FAILED
    assert list(done) == []  # all completed steps were compensated
    # The compensation order must be reverse of the completion order.
    undos = [line for line in log if line.startswith(("undo_", "refund", "cancel_"))]
    assert undos == ["refund:{'ok': True}", "undo_reserve:{'ok': True}"]


def test_inv_reverse_compensation_prevents() -> None:
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c3", {"order": 1})
    saga.step("c3", "reserve_stock", {"ok": True})
    saga.step("c3", "charge_card", {"ok": True})
    # Attempt to compensate an earlier step than the tail is FORBIDDEN.
    with pytest.raises(CompensationOrderError):
        saga.compensate("c3", from_step="reserve_stock")


def test_inv_reverse_compensation_under_failure() -> None:
    sd, log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c4", {"order": 1})
    saga.step("c4", "reserve_stock", {"ok": True})
    # Fail on the second step — only reserve_stock has completed.
    saga.step("c4", "charge_card", {"__saga_failed__": True, "reason": "insufficient funds"})
    state, done = saga.status("c4")
    assert state == STATE_FAILED
    assert list(done) == []
    undos = [line for line in log if "undo_" in line or "refund" in line or "cancel_" in line]
    assert undos == ["undo_reserve:{'ok': True}"]


# ---------------------------------------------------------------------------
# SAGA_INV_03 — state transitions persisted atomically with emitted commands
# ---------------------------------------------------------------------------
def test_inv_atomic_journal_confirms() -> None:
    sd, _log = _three_step_saga()
    emitted: list[tuple[str, str]] = []

    def sink(cid: str, cmd: str, _payload: object) -> None:
        emitted.append((cid, cmd))

    saga = InMemorySagaOrchestrator(sd, command_sink=sink)
    saga.start("c5", {"order": 1})
    # After start(), state is RUNNING and the first invoke command has been emitted.
    state, _done = saga.status("c5")
    assert state == STATE_RUNNING
    assert emitted and emitted[0] == ("c5", "invoke_reserve_stock")
    # The journal records the transition AND the command as one unit.
    journal = saga.journal_for("c5")
    assert journal[0].from_state == "pending"
    assert journal[0].to_state == STATE_RUNNING
    assert journal[0].command_name == "invoke_reserve_stock"


def test_inv_atomic_journal_prevents() -> None:
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    with pytest.raises(UnknownSagaError):
        saga.status("unknown")


def test_inv_atomic_journal_under_failure() -> None:
    """Sink failure during emit does NOT corrupt the journal."""
    sd, _log = _three_step_saga()
    call_count = {"n": 0}

    def flaky_sink(_cid: str, _cmd: str, _payload: object) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("sink down")

    saga = InMemorySagaOrchestrator(sd, command_sink=flaky_sink)
    saga.start("c6", {"order": 1})
    # The sink raised but the journal MUST still be intact and recoverable.
    journal = saga.journal_for("c6")
    assert len(journal) == 1
    assert journal[0].to_state == STATE_RUNNING
    # last_error tracks the sink failure for recovery tooling.
    assert "sink failure" in (saga.last_error("c6") or "")


# ---------------------------------------------------------------------------
# SAGA_INV_04 — async coordination; orchestrator never assumes strong consistency
# ---------------------------------------------------------------------------
def test_inv_async_coordination_confirms() -> None:
    """The orchestrator ACCEPTS async step reports one-at-a-time without blocking."""
    sd, _log = _three_step_saga()
    emitted: list[tuple[str, str]] = []

    def sink(cid: str, cmd: str, _payload: object) -> None:
        emitted.append((cid, cmd))

    saga = InMemorySagaOrchestrator(sd, command_sink=sink)
    saga.start("c7", {"order": 1})
    # The orchestrator does NOT synchronously run step handlers — it emits a
    # command and waits for the participant to report back asynchronously.
    assert emitted == [("c7", "invoke_reserve_stock")]
    # Simulate a delayed async reply.
    saga.step("c7", "reserve_stock", {"ok": True})
    assert emitted[-1] == ("c7", "invoke_charge_card")


def test_inv_async_coordination_prevents() -> None:
    """Duplicate (re-delivered) step reports are IDEMPOTENT, not double-applied."""
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c8", {"order": 1})
    saga.step("c8", "reserve_stock", {"ok": True})
    # Re-deliver — must be idempotent (SAGA-INV-04: messages can be redelivered).
    saga.step("c8", "reserve_stock", {"ok": True})
    saga.step("c8", "reserve_stock", {"ok": True})
    state, done = saga.status("c8")
    # Still advanced only once; current state is RUNNING awaiting charge_card.
    assert state == STATE_RUNNING
    assert list(done) == ["reserve_stock"]


def test_inv_async_coordination_under_failure() -> None:
    """Out-of-order step reports (participant reports step B before A is done)
    are rejected — the orchestrator never advances to a later step whose
    prerequisites are not yet confirmed as completed."""
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("c9", {"order": 1})
    with pytest.raises(SagaOrchestratorInvariantError):
        saga.step("c9", "ship_order", {"ok": True})  # skipping reserve_stock + charge_card


# ---------------------------------------------------------------------------
# Concurrency sanity (used by multiple invariants)
# ---------------------------------------------------------------------------
def test_thread_safety_step_reports_never_corrupt_state() -> None:
    sd, _log = _three_step_saga()
    saga = InMemorySagaOrchestrator(sd)
    saga.start("cc", {"order": 1})

    def worker() -> None:
        # Ten threads redeliver the same step — must collapse to ONE advance.
        saga.step("cc", "reserve_stock", {"ok": True})

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    state, done = saga.status("cc")
    assert list(done) == ["reserve_stock"]
    assert state == STATE_RUNNING
