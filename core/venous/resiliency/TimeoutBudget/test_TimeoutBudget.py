"""Unit tests for TimeoutBudget — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading
import time

import pytest

from TimeoutBudget import (
    CURRENT_BUDGET,
    DeadlineHeaderCodec,
    GuardedCall,
    MonotonicTimeoutBudget,
    TimeoutBudgetExpired,
    TimeoutBudgetInvariantError,
    bind,
    current,
)


# ---------------------------------------------------------------------------
# TB_INV_01 — for_call MUST return min(local, remaining)
# ---------------------------------------------------------------------------
def test_inv_for_call_min_confirms() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1000, origin="ingress")
    effective = budget.for_call(max_ms=250)
    # local (250) is smaller than remaining (~1000), so min == 250.
    assert effective == 250


def test_inv_for_call_min_prevents() -> None:
    # Local timeout larger than remaining — for_call MUST return remaining, not local.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=50, origin="ingress")
    effective = budget.for_call(max_ms=10_000)
    assert 0 < effective <= 50
    # Non-positive or non-int local timeouts MUST be rejected — no silent default.
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.for_call(max_ms=0)
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.for_call(max_ms=-5)


def test_inv_for_call_min_under_failure() -> None:
    # GuardedCall proves the min-rule is honoured at the transport boundary
    # even under repeated dispatches that exhaust the budget.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=200, origin="ingress")
    guard = GuardedCall()
    effective = guard.dispatch(budget, "/a", local_timeout_ms=5000)
    # local 5000 was clamped to remaining (<=200).
    assert effective <= 200
    assert guard.dispatches[0][1] == effective


# ---------------------------------------------------------------------------
# TB_INV_02 — monotonic clock; immune to wall-clock jumps
# ---------------------------------------------------------------------------
def test_inv_monotonic_clock_confirms() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="ingress")
    # Deadline is an int from time.monotonic_ns() + delta.
    assert isinstance(budget.deadline_ns, int)
    first = budget.remaining_ms()
    time.sleep(0.01)
    second = budget.remaining_ms()
    assert second <= first  # monotonically non-increasing


def test_inv_monotonic_clock_prevents() -> None:
    # The deadline_ns field is immutable — no backdoor to move it.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="ingress")
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.deadline_ns = budget.deadline_ns + 10_000_000  # type: ignore[misc]  # TB-INV-04: extension attempt
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.origin = "hijack"  # type: ignore[misc]  # TB-INV-04: immutability probe


def test_inv_monotonic_clock_under_failure() -> None:
    # Wall-clock probes cannot corrupt the monotonic-based remaining_ms.
    # Repeatedly read wall clock + monotonic remaining and assert the budget
    # only ever shrinks (never grows).
    budget = MonotonicTimeoutBudget.from_ms(total_ms=200, origin="ingress")
    prev = budget.remaining_ms()
    for _ in range(50):
        # Touching wall clock MUST NOT affect remaining_ms.
        _ = time.time()
        now = budget.remaining_ms()
        assert now <= prev
        prev = now


# ---------------------------------------------------------------------------
# TB_INV_03 — expired budget refuses the call
# ---------------------------------------------------------------------------
def test_inv_expired_refuses_confirms() -> None:
    # Budget with 1ms + sleep 10ms → expired; for_call MUST raise.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="ingress")
    time.sleep(0.01)
    assert budget.expired()
    with pytest.raises(TimeoutBudgetExpired):
        budget.for_call(max_ms=100)


def test_inv_expired_refuses_prevents() -> None:
    # GuardedCall MUST NOT record a real (positive) dispatch when expired.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="ingress")
    time.sleep(0.01)
    guard = GuardedCall()
    with pytest.raises(TimeoutBudgetExpired):
        guard.dispatch(budget, "/x", local_timeout_ms=100)
    assert guard.refused == 1
    # The refused dispatch was recorded with sentinel -1 (never a positive ms).
    assert guard.dispatches == (("/x", -1),)


def test_inv_expired_refuses_under_failure() -> None:
    # Many concurrent callers on an already-expired budget — ALL must be refused;
    # none should slip through with a positive effective timeout.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="ingress")
    time.sleep(0.01)
    guard = GuardedCall()
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            guard.dispatch(budget, "/fanout", local_timeout_ms=500)
        except TimeoutBudgetExpired:
            return
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert guard.refused == 32
    # Every recorded dispatch is the -1 sentinel — never a positive timeout.
    assert all(eff == -1 for _, eff in guard.dispatches)


# ---------------------------------------------------------------------------
# TB_INV_04 — no extension; derived child ≤ parent
# ---------------------------------------------------------------------------
def test_inv_no_extension_confirms() -> None:
    parent = MonotonicTimeoutBudget.from_ms(total_ms=1000, origin="ingress")
    child = parent.derive(child_max_ms=250)
    # Child cannot outlive parent.
    assert child.deadline_ns <= parent.deadline_ns
    # Child origin inherited (same request boundary).
    assert child.origin == parent.origin


def test_inv_no_extension_prevents() -> None:
    # Directly constructing a child whose deadline > parent MUST be rejected.
    parent = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="ingress")
    with pytest.raises(TimeoutBudgetInvariantError):
        MonotonicTimeoutBudget(
            deadline_ns=parent.deadline_ns + 10_000_000_000,
            origin="ingress",
            parent_deadline_ns=parent.deadline_ns,
        )
    # Non-positive derivation is likewise refused.
    with pytest.raises(TimeoutBudgetInvariantError):
        parent.derive(child_max_ms=0)
    with pytest.raises(TimeoutBudgetInvariantError):
        parent.derive(child_max_ms=-1)


def test_inv_no_extension_under_failure() -> None:
    # Chain of derivations MUST produce monotonically non-increasing deadlines.
    parent = MonotonicTimeoutBudget.from_ms(total_ms=2000, origin="ingress")
    prev_deadline = parent.deadline_ns
    current_budget = parent
    for _ in range(20):
        child = current_budget.derive(child_max_ms=5000)  # requested > parent
        assert child.deadline_ns <= prev_deadline
        prev_deadline = child.deadline_ns
        current_budget = child


# ---------------------------------------------------------------------------
# TB_INV_05 — contextvar propagation (never thread-local)
# ---------------------------------------------------------------------------
def test_inv_contextvar_propagation_confirms() -> None:
    # CURRENT_BUDGET is a ContextVar, not a thread-local.
    from contextvars import ContextVar as _CV
    assert isinstance(CURRENT_BUDGET, _CV)
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req-1")
    with bind(budget):
        assert current() is budget
    # Binding cleared on exit.
    assert CURRENT_BUDGET.get() is None


def test_inv_contextvar_propagation_prevents() -> None:
    # current() MUST refuse to default to "no deadline" when no budget is bound.
    assert CURRENT_BUDGET.get() is None
    with pytest.raises(TimeoutBudgetInvariantError):
        current()
    # Header codec MUST reject missing / invalid header values.
    with pytest.raises(TimeoutBudgetInvariantError):
        DeadlineHeaderCodec.decode("not-an-int", origin="x")


def test_inv_contextvar_propagation_under_failure() -> None:
    # Binding in one context MUST NOT leak into a child thread absent contextvars.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="parent")
    seen: list[object] = []
    lock = threading.Lock()

    def worker() -> None:
        # Fresh thread has no copied context; CURRENT_BUDGET MUST be None.
        with lock:
            seen.append(CURRENT_BUDGET.get())

    with bind(budget):
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert seen == [None]  # thread-local leakage would put `budget` here
