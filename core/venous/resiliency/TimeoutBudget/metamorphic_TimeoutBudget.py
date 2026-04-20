"""Metamorphic + differential tests for TimeoutBudget.

Algebraic laws asserted here:

- ``for_call(m) <= m`` for every ``m > 0``  (bounded-below by local).
- ``for_call(m) <= remaining_ms()``         (bounded-below by parent-remaining).
- ``derive`` is monotonically non-expanding in its requested child_max_ms.
- ``DeadlineHeaderCodec.encode → decode`` preserves the "≤" ordering.
- Two budgets with identical total_ms report the same ordering for remaining_ms.
"""

from __future__ import annotations

import time

import pytest

from TimeoutBudget import (
    DeadlineHeaderCodec,
    MonotonicTimeoutBudget,
    TimeoutBudgetExpired,
)


def test_metamorphic_for_call_bounded_below_by_local() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1000, origin="req")
    for m in (1, 10, 100, 500):
        assert budget.for_call(max_ms=m) <= m


def test_metamorphic_for_call_bounded_below_by_remaining() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=50, origin="req")
    for m in (100, 500, 10_000):
        eff = budget.for_call(max_ms=m)
        assert eff <= budget.remaining_ms() + 1  # +1 for rounding tolerance


def test_metamorphic_derive_non_expanding_in_request() -> None:
    parent = MonotonicTimeoutBudget.from_ms(total_ms=500, origin="req")
    # Larger child requests CANNOT produce larger child deadlines once capped.
    a = parent.derive(child_max_ms=100)
    b = parent.derive(child_max_ms=10_000)  # capped at parent
    assert a.deadline_ns <= parent.deadline_ns
    assert b.deadline_ns <= parent.deadline_ns
    # 'b' is capped at parent; a smaller-request 'a' MUST NOT exceed it.
    # (They are near-equal; the inequality we need is 'no expansion'.)
    assert a.deadline_ns <= b.deadline_ns + 10_000_000  # 10ms slack


def test_metamorphic_header_codec_preserves_monotone_ordering() -> None:
    src = MonotonicTimeoutBudget.from_ms(total_ms=300, origin="edge")
    h1 = int(DeadlineHeaderCodec.encode(src))
    time.sleep(0.005)
    h2 = int(DeadlineHeaderCodec.encode(src))
    assert h2 <= h1


def test_differential_two_budgets_same_total_consistent_ordering() -> None:
    a = MonotonicTimeoutBudget.from_ms(total_ms=200, origin="a")
    b = MonotonicTimeoutBudget.from_ms(total_ms=200, origin="b")
    # Both budgets opened back-to-back → their deadlines differ by < 10ms; the
    # ordering of remaining_ms MUST be consistent and both >= 0.
    assert a.remaining_ms() >= 0
    assert b.remaining_ms() >= 0
    assert abs(a.remaining_ms() - b.remaining_ms()) <= 10


def test_metamorphic_expired_is_terminal() -> None:
    budget = MonotonicTimeoutBudget.from_ms(total_ms=1, origin="req")
    time.sleep(0.005)
    # Expired → remaining_ms stays at 0 across repeated reads; for_call raises.
    for _ in range(10):
        assert budget.remaining_ms() == 0
        with pytest.raises(TimeoutBudgetExpired):
            budget.for_call(max_ms=50)
