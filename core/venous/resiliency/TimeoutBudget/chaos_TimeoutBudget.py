"""Chaos / game-day tests for TimeoutBudget.

Simulates clock stress, fan-out stampedes, header corruption, and exhaustive
derivation chains to confirm the budget never grows and never silently admits
a call past its deadline.
"""

from __future__ import annotations

import threading
import time

import pytest

from TimeoutBudget import (
    DeadlineHeaderCodec,
    GuardedCall,
    MonotonicTimeoutBudget,
    TimeoutBudgetExpired,
    TimeoutBudgetInvariantError,
)


def test_chaos_fanout_stampede_all_refused_when_expired() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="req")
    time.sleep(0.01)
    guard = GuardedCall()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            guard.dispatch(budget, "/x", local_timeout_ms=200)
        except TimeoutBudgetExpired:
            return
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(64)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert guard.refused == 64


def test_chaos_corrupted_header_rejected() -> None:
    # A corrupted upstream deadline header MUST be refused — never silently
    # treated as "no deadline".
    for bad in ("", "abc", "1.5", "   "):
        with pytest.raises(TimeoutBudgetInvariantError):
            DeadlineHeaderCodec.decode(bad, origin="edge")


def test_chaos_negative_header_expired() -> None:
    with pytest.raises(TimeoutBudgetExpired):
        DeadlineHeaderCodec.decode("-10", origin="edge")
    with pytest.raises(TimeoutBudgetExpired):
        DeadlineHeaderCodec.decode("0", origin="edge")


def test_chaos_long_derive_chain_never_exceeds_root() -> None:
    root = MonotonicTimeoutBudget.from_ms(total_ms=5000, origin="root")
    budget = root
    for _ in range(1000):
        budget = budget.derive(child_max_ms=10_000)  # request > parent
        assert budget.deadline_ns <= root.deadline_ns


def test_chaos_concurrent_derive_never_expands() -> None:
    parent = MonotonicTimeoutBudget.from_ms(total_ms=500, origin="p")
    exceeded: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        child = parent.derive(child_max_ms=10_000)
        if child.deadline_ns > parent.deadline_ns:
            with lock:
                exceeded.append(child.deadline_ns)

    ts = [threading.Thread(target=worker) for _ in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert exceeded == []


def test_chaos_immutability_probes_blocked() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req")
    # Every attribute set attempt MUST raise — budget is frozen.
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.deadline_ns = 0  # type: ignore[misc]  # TB-INV-04 probe
    with pytest.raises(TimeoutBudgetInvariantError):
        budget.origin = "x"  # type: ignore[misc]  # TB-INV-04 probe
    with pytest.raises(TimeoutBudgetInvariantError):
        budget._parent_deadline_ns = None  # type: ignore[misc]  # TB-INV-04 probe


def test_chaos_wall_clock_noise_does_not_refresh_budget() -> None:
    # Wall-clock reads MUST NOT perturb the monotonic-based remaining_ms.
    budget = MonotonicTimeoutBudget.from_ms(total_ms=50, origin="req")
    first = budget.remaining_ms()
    for _ in range(200):
        _ = time.time()  # wall clock noise
    second = budget.remaining_ms()
    assert second <= first


def test_chaos_bulk_for_call_always_clamped() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req")
    results = [budget.for_call(max_ms=10_000) for _ in range(50)]
    # All clamped to current remaining_ms — never the local 10_000.
    assert max(results) <= 100
