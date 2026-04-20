"""Metamorphic + differential tests for SagaOrchestrator.

Algebraic properties:
- compensation order is ALWAYS the reverse of completion order
- redelivery is idempotent: N duplicates have the same effect as 1
- start() is idempotent: calling twice leaves the saga in the state of the first call
- two isolated correlation_ids never interfere with each other
- the journal length monotonically grows with state transitions
"""

from __future__ import annotations

from SagaOrchestrator import (
    STATE_COMPLETED,
    STATE_FAILED,
    InMemorySagaOrchestrator,
    SagaDefinition,
)


def _saga(trace: list[str]) -> SagaDefinition:
    sd = SagaDefinition("m")
    sd.register("a", compensator=lambda p: trace.append(f"~a:{p!r}"))(lambda p: p)
    sd.register("b", compensator=lambda p: trace.append(f"~b:{p!r}"))(lambda p: p)
    sd.register("c", compensator=lambda p: trace.append(f"~c:{p!r}"))(lambda p: p)
    return sd


def test_metamorphic_compensation_reverses_completion() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("x", {})
    saga.step("x", "a", 1)
    saga.step("x", "b", 2)
    saga.step("x", "c", {"__saga_failed__": True, "reason": "r"})
    undos = [t for t in trace if t.startswith("~")]
    assert undos == ["~b:2", "~a:1"]


def test_metamorphic_redelivery_is_idempotent() -> None:
    trace: list[str] = []
    saga_a = InMemorySagaOrchestrator(_saga(trace))
    saga_a.start("a1", {})
    saga_a.step("a1", "a", 10)
    state_a, done_a = saga_a.status("a1")

    trace_b: list[str] = []
    saga_b = InMemorySagaOrchestrator(_saga(trace_b))
    saga_b.start("b1", {})
    for _ in range(50):
        saga_b.step("b1", "a", 10)
    state_b, done_b = saga_b.status("b1")

    assert state_a == state_b
    assert list(done_a) == list(done_b) == ["a"]


def test_metamorphic_start_is_idempotent() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("s", {"v": 1})
    first_journal = saga.journal_for("s")
    saga.start("s", {"v": 2})
    saga.start("s", {"v": 3})
    second_journal = saga.journal_for("s")
    # Journal MUST NOT grow on repeated starts.
    assert len(first_journal) == len(second_journal)


def test_metamorphic_isolated_correlations_do_not_interfere() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("one", {})
    saga.start("two", {})
    saga.step("one", "a", 1)
    saga.step("two", "a", 2)
    saga.step("two", "b", 3)
    s1, d1 = saga.status("one")
    s2, d2 = saga.status("two")
    assert list(d1) == ["a"]
    assert list(d2) == ["a", "b"]
    assert s1 == s2 == "running"


def test_metamorphic_journal_monotonic_on_completion() -> None:
    trace: list[str] = []
    saga = InMemorySagaOrchestrator(_saga(trace))
    saga.start("m1", {})
    lengths: list[int] = [len(saga.journal_for("m1"))]
    saga.step("m1", "a", 1)
    lengths.append(len(saga.journal_for("m1")))
    saga.step("m1", "b", 2)
    lengths.append(len(saga.journal_for("m1")))
    saga.step("m1", "c", 3)
    lengths.append(len(saga.journal_for("m1")))
    # Strictly monotonic.
    assert all(lengths[i] < lengths[i + 1] for i in range(len(lengths) - 1))
    assert saga.status("m1")[0] == STATE_COMPLETED


def test_differential_full_fail_vs_explicit_compensate_equivalent() -> None:
    """A failure on the tail step produces the SAME compensation trace as an
    explicit compensate() from the tail."""
    trace_fail: list[str] = []
    saga_a = InMemorySagaOrchestrator(_saga(trace_fail))
    saga_a.start("fa", {})
    saga_a.step("fa", "a", 1)
    saga_a.step("fa", "b", 2)
    saga_a.step("fa", "c", {"__saga_failed__": True, "reason": "x"})

    trace_comp: list[str] = []
    saga_b = InMemorySagaOrchestrator(_saga(trace_comp))
    saga_b.start("fb", {})
    saga_b.step("fb", "a", 1)
    saga_b.step("fb", "b", 2)
    saga_b.compensate("fb", from_step="b")

    # Both end FAILED; both ran b's then a's compensator.
    assert saga_a.status("fa")[0] == STATE_FAILED
    assert saga_b.status("fb")[0] == STATE_FAILED
    undos_a = [t for t in trace_fail if t.startswith("~")]
    undos_b = [t for t in trace_comp if t.startswith("~")]
    assert undos_a == ["~b:2", "~a:1"]
    assert undos_b == ["~b:2", "~a:1"]
