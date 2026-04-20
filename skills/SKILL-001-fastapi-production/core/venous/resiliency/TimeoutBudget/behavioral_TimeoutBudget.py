"""Behavioral end-to-end scenarios for TimeoutBudget — proves invariants at runtime."""

from __future__ import annotations

import threading
import time

import pytest

from TimeoutBudget import (
    DeadlineHeaderCodec,
    GuardedCall,
    MonotonicTimeoutBudget,
    TimeoutBudgetExpired,
    bind,
    current,
)


def test_scenario_hop_chain_shrinks_monotonically() -> None:
    # Ingress opens a 500ms budget; three downstream hops derive children.
    root = MonotonicTimeoutBudget.from_ms(total_ms=500, origin="req-A")
    with bind(root):
        b1 = current()
        c1 = b1.for_call(max_ms=1000)
        child = root.derive(child_max_ms=200)
        with bind(child):
            c2 = current().for_call(max_ms=1000)
            grand = child.derive(child_max_ms=1000)
            with bind(grand):
                c3 = current().for_call(max_ms=1000)
    # Each deeper hop sees strictly non-increasing effective timeout.
    assert c1 >= c2 >= c3
    assert c3 > 0


def test_scenario_http_header_roundtrip_preserves_shrinkage() -> None:
    upstream = MonotonicTimeoutBudget.from_ms(total_ms=300, origin="edge")
    # Emit the header as a middleware would.
    header = DeadlineHeaderCodec.encode(upstream)
    # Simulate network delay — wall-clock irrelevant, monotonic rules (TB-INV-02).
    time.sleep(0.01)
    downstream = DeadlineHeaderCodec.decode(header, origin="edge")
    # Downstream budget CANNOT exceed what upstream emitted.
    assert downstream.remaining_ms() <= int(header)


def test_scenario_expired_budget_refuses_dispatch() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="req")
    time.sleep(0.01)
    guard = GuardedCall()
    with pytest.raises(TimeoutBudgetExpired):
        guard.dispatch(budget, "/downstream", local_timeout_ms=200)
    # Zero socket dispatches — only the sentinel refusal record.
    assert guard.refused == 1


def test_scenario_fanout_shares_parent_ceiling() -> None:
    # Ten concurrent children derived from the same parent — none may outlive parent.
    parent = MonotonicTimeoutBudget.from_ms(total_ms=400, origin="req-fan")
    ceilings: list[int] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        child = parent.derive(child_max_ms=1000)
        with lock:
            ceilings.append(child.deadline_ns)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ceilings) == 10
    assert all(c <= parent.deadline_ns for c in ceilings)


def test_scenario_unbound_current_raises_never_silent() -> None:
    # A call-site without an ambient budget MUST refuse to proceed — never
    # silently default to "no deadline".
    with pytest.raises(Exception) as excinfo:
        current()
    assert "TB-INV-05" in str(excinfo.value)


def test_scenario_contextvar_reset_after_bind() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=100, origin="req-R")
    with bind(budget):
        inner = current()
        assert inner.origin == "req-R"
    with pytest.raises(Exception):
        current()  # bind scope exited — MUST raise
