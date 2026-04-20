"""Tests for CausalReorderBuffer invariants CRB_INV_01..05."""

from __future__ import annotations

import pytest

from core.venous.events.CausalReorderBuffer.CausalReorderBuffer import (
    CausalReorderBufferError,
    InMemoryCausalReorderBuffer,
)


# ---------------------------------------------------------------------------
# INV_01: strictly monotonic drain
# ---------------------------------------------------------------------------
def test_inv_monotonic_drain_confirms() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 2, {"v": 2}, deadline_ms=1_000)
    buf.offer("a", 0, {"v": 0}, deadline_ms=1_000)
    buf.offer("a", 1, {"v": 1}, deadline_ms=1_000)
    drained = [e["v"] for e in buf.next_ready("a")]
    assert drained == [0, 1, 2], "events MUST drain in strictly monotonic order"


def test_inv_monotonic_drain_prevents_head_skip() -> None:
    buf = InMemoryCausalReorderBuffer()
    # Only sequence 2 and 1 arrive; head (0) is missing → nothing drains.
    buf.offer("a", 2, {"v": 2}, deadline_ms=10_000)
    buf.offer("a", 1, {"v": 1}, deadline_ms=10_000)
    assert list(buf.next_ready("a")) == [], "drain MUST NOT skip a missing head"


# ---------------------------------------------------------------------------
# INV_02: out-of-order held until predecessor OR deadline
# ---------------------------------------------------------------------------
def test_inv_hold_until_predecessor_confirms() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 1, {"v": 1}, deadline_ms=10_000)
    # Predecessor missing — no drain.
    assert list(buf.next_ready("a")) == []
    # Predecessor arrives within deadline — drain flows.
    buf.offer("a", 0, {"v": 0}, deadline_ms=10_000)
    assert [e["v"] for e in buf.next_ready("a")] == [0, 1]


# ---------------------------------------------------------------------------
# INV_03: deadline expiry emits exactly ONCE
# ---------------------------------------------------------------------------
def test_inv_timed_out_confirms_exactly_once() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 1, {"v": 1}, deadline_ms=500)
    # First reap: gap emitted.
    first = buf.timed_out(now_ms=1_000)
    assert first == [("a", 0)], f"expected one gap, got {first}"
    # Second reap: no re-emission.
    second = buf.timed_out(now_ms=2_000)
    assert second == [], "gap MUST NOT be reported twice"


# ---------------------------------------------------------------------------
# INV_04: after gap, later sequences drain
# ---------------------------------------------------------------------------
def test_inv_post_gap_drain_confirms() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 1, {"v": 1}, deadline_ms=500)
    buf.offer("a", 2, {"v": 2}, deadline_ms=500)
    # Sequence 0 never arrives — deadline fires.
    gaps = buf.timed_out(now_ms=1_000)
    assert gaps == [("a", 0)]
    drained = [e["v"] for e in buf.next_ready("a")]
    assert drained == [1, 2], "post-gap drain MUST yield surviving events"


# ---------------------------------------------------------------------------
# INV_05: duplicate offer is idempotent
# ---------------------------------------------------------------------------
def test_inv_idempotent_offer_confirms() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 0, {"v": "first"}, deadline_ms=1_000)
    # Second offer for same (agg, seq) — MUST be dropped silently.
    buf.offer("a", 0, {"v": "SECOND"}, deadline_ms=1_000)
    drained = [e["v"] for e in buf.next_ready("a")]
    assert drained == ["first"], f"duplicate offer MUST be dropped; got {drained}"


def test_inv_idempotent_offer_prevents_reintroduce_after_drain() -> None:
    buf = InMemoryCausalReorderBuffer()
    buf.offer("a", 0, {"v": "first"}, deadline_ms=1_000)
    list(buf.next_ready("a"))  # drain
    # Replaying the already-drained sequence MUST NOT reappear.
    buf.offer("a", 0, {"v": "REPLAY"}, deadline_ms=1_000)
    assert list(buf.next_ready("a")) == [], "obsolete replay MUST be dropped"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_offer_rejects_negative_sequence() -> None:
    buf = InMemoryCausalReorderBuffer()
    with pytest.raises(CausalReorderBufferError):
        buf.offer("a", -1, {}, deadline_ms=0)


def test_start_sequence_rejects_negative() -> None:
    with pytest.raises(CausalReorderBufferError):
        InMemoryCausalReorderBuffer(start_sequence=-1)
