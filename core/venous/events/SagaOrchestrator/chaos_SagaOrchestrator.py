"""Chaos / game-day tests for SagaOrchestrator.

Simulates sink outages, compensator faults, out-of-order participant reports,
repeated redelivery, and concurrent starts to confirm the saga never enters an
inconsistent state or leaves completed steps uncompensated.
"""

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
    SagaOrchestratorInvariantError,
)


def _saga(trace: list[str]) -> SagaDefinition:
    sd = SagaDefinition("chaos")
    sd.register("a", compensator=lambda p: trace.append(f"~a:{p!r}"))(lambda p: p)
    sd.register("b", compensator=lambda p: trace.append(f"~b:{p!r}"))(lambda p: p)
    sd.register("c", compensator=lambda p: trace.append(f"~c:{p!r}"))(lambda p: p)
    return sd


def test_chaos_sink_always_fails_journal_survives() -> None:
    trace: list[str] = []

    def bad_sink(_c: str, _n: str, _p: object) -> None:
        raise OSError("bus down")

    saga = InMemorySagaOrchestrator(_saga(trace), command_sink=bad_sink)
    saga.start("c", {})
    # Every step report fails to emit but the journal keeps growing and the
    # state machine keeps advancing — the journal is the source of truth.
    saga.step("c", "a", 1)
    saga.step("c", "b", 2)
    saga.step("c", "c", 3)
    assert saga.status("c")[0] == STATE_COMPLETED
    journal = saga.journal_for("c")
    # PENDING->RUNNING, RUNNING->RUNNING x2, RUNNING->COMPLETED = 4 entries.
    assert len(journal) == 4


def test_chaos_compensator_raises_saga_halts_but_state_recorded() -> None:
    trace: list[str] = []
    sd = SagaDefinition("x")

    def angry_compensator(_p: object) -> None:
        raise ValueError("rollback service down")

    sd.register("a", compensator=angry_compensator)(lambda p: p)
    sd.register("b", compensator=lambda p: trace.append(f"~b:{p!r}"))(lambda p: p)
    saga = InMemorySagaOrchestrator(sd)
    saga.start("s", {})
    saga.step("s", "a", 1)
    # Fail on b — must compensate a, whose compensator explodes.
    saga.step("s", "b", {"__saga_failed__": True, "reason": "r"})
    # Saga did NOT reach FAILED because compensator halted; it is stuck in
    # COMPENSATING with last_error populated — operator can resume.
    state, _done = saga.status("s")
    assert state == "compensating"
    assert "rollback service down" in (saga.last_error("s") or "")


def test_chaos_duplicate_redelivery_never_double_applies() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("d", {})
    for _ in range(100):
        saga.step("d", "a", 99)
    state, done = saga.status("d")
    assert list(done) == ["a"]
    assert state == STATE_RUNNING


def test_chaos_out_of_order_step_rejected() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("oo", {})
    # Participant for step 'c' reports before 'a' or 'b' → rejected.
    with pytest.raises(SagaOrchestratorInvariantError):
        saga.step("oo", "c", 1)


def test_chaos_explicit_compensate_out_of_order_rejected() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("oc", {})
    saga.step("oc", "a", 1)
    saga.step("oc", "b", 2)
    with pytest.raises(CompensationOrderError):
        saga.compensate("oc", from_step="a")


def test_chaos_concurrent_starts_are_idempotent() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    ok: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        saga.start("race", {})
        with lock:
            ok.append(1)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Only one saga instance exists.
    assert "race" in saga.known_correlations()
    # The journal has exactly one PENDING->RUNNING transition, not 20.
    journal = saga.journal_for("race")
    pending_transitions = [r for r in journal if r.from_state == "pending"]
    assert len(pending_transitions) == 1


def test_chaos_terminal_saga_ignores_late_reports() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("t", {})
    saga.step("t", "a", 1)
    saga.step("t", "b", 2)
    saga.step("t", "c", 3)
    assert saga.status("t")[0] == STATE_COMPLETED
    # A late re-delivery AFTER completion must NOT advance or explode.
    saga.step("t", "c", 3)
    saga.step("t", "a", 1)
    # No change.
    assert saga.status("t")[0] == STATE_COMPLETED


def test_chaos_large_burst_of_reports_across_correlations() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    N = 200
    for i in range(N):
        saga.start(f"b{i}", {"i": i})
    # Drive each saga to completion in parallel.
    threads = []
    for i in range(N):
        def finish(cid: str = f"b{i}") -> None:
            saga.step(cid, "a", 1)
            saga.step(cid, "b", 2)
            saga.step(cid, "c", 3)
        t = threading.Thread(target=finish)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    assert saga.active_count() == 0
    for i in range(N):
        assert saga.status(f"b{i}")[0] == STATE_COMPLETED


def test_chaos_compensate_on_unknown_saga_raises() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    with pytest.raises(SagaOrchestratorInvariantError):
        saga.compensate("never-started", from_step="a")


def test_chaos_empty_saga_compensate_transitions_to_failed() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("empty", {})
    # Before any step completes, operator compensates — MUST go to FAILED.
    saga.compensate("empty", from_step="a")  # from_step is accepted here because nothing completed yet
    assert saga.status("empty")[0] == STATE_FAILED
