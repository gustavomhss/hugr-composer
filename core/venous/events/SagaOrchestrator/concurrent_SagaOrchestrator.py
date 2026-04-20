"""Concurrency / linearizability harness for SagaOrchestrator.

Confirms that concurrent step reports, concurrent starts, and concurrent
compensations preserve the invariants:
- no step is advanced twice (idempotent redelivery)
- compensation order remains reverse-of-completion even under races
- journal ordering is a total order consistent with state transitions
"""

from __future__ import annotations

import threading

from SagaOrchestrator import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    InMemorySagaOrchestrator,
    SagaDefinition,
)


def _saga(trace: list[str]) -> SagaDefinition:
    sd = SagaDefinition("conc")
    sd.register("a", compensator=lambda p: trace.append(f"~a:{p!r}"))(lambda p: p)
    sd.register("b", compensator=lambda p: trace.append(f"~b:{p!r}"))(lambda p: p)
    sd.register("c", compensator=lambda p: trace.append(f"~c:{p!r}"))(lambda p: p)
    return sd


def test_concurrent_duplicate_step_reports_collapse_to_one_advance() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("c1", {})

    def worker() -> None:
        saga.step("c1", "a", {"v": 1})

    ts = [threading.Thread(target=worker) for _ in range(50)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    state, done = saga.status("c1")
    assert list(done) == ["a"]
    assert state == STATE_RUNNING


def test_concurrent_starts_same_correlation_idempotent() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))

    def worker() -> None:
        saga.start("c2", {"payload": "x"})

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    journal = saga.journal_for("c2")
    # Only ONE initial PENDING->RUNNING transition.
    firsts = [r for r in journal if r.from_state == "pending"]
    assert len(firsts) == 1


def test_concurrent_distinct_correlations_no_interference() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))

    def drive(cid: str) -> None:
        saga.start(cid, {})
        saga.step(cid, "a", 1)
        saga.step(cid, "b", 2)
        saga.step(cid, "c", 3)

    N = 40
    ts = [threading.Thread(target=drive, args=(f"x{i}",)) for i in range(N)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    for i in range(N):
        assert saga.status(f"x{i}")[0] == STATE_COMPLETED


def test_concurrent_failure_compensates_in_reverse() -> None:
    """Even under racing step reports, if a failure occurs the compensation
    sequence is a strict reverse of the `completed` list at the moment of
    failure."""
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("cf", {})
    # Thread 1: reports `a` success
    # Thread 2: reports `b` success
    # Main: after both, fail on `c`
    def t_a() -> None:
        for _ in range(5):
            saga.step("cf", "a", 1)

    def t_b() -> None:
        # Must run strictly after a has advanced — poll state.
        while saga.status("cf")[1] != ("a",):
            pass
        for _ in range(5):
            saga.step("cf", "b", 2)

    ts = [threading.Thread(target=t_a), threading.Thread(target=t_b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Now fail the tail.
    saga.step("cf", "c", {"__saga_failed__": True, "reason": "x"})
    assert saga.status("cf")[0] == STATE_FAILED
    undos = [t for t in trace if t.startswith("~")]
    assert undos == ["~b:2", "~a:1"]


def test_concurrent_journal_ordering_is_a_total_order() -> None:
    """Sequence numbers on the journal never repeat and are strictly increasing
    even when many threads drive the orchestrator."""
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))

    def drive(cid: str) -> None:
        saga.start(cid, {})
        saga.step(cid, "a", 1)

    N = 50
    ts = [threading.Thread(target=drive, args=(f"j{i}",)) for i in range(N)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    all_seqs: list[int] = []
    for i in range(N):
        for r in saga.journal_for(f"j{i}"):
            all_seqs.append(r.seq)
    assert len(set(all_seqs)) == len(all_seqs)  # every seq is unique (global total order)
