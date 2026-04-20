"""Unit tests for InboxDeduplicator — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from InboxDeduplicator import (
    InboxDeduplicatorInvariantError,
    InMemoryInboxDeduplicator,
)


# ---------------------------------------------------------------------------
# INBOX_INV_01 — record written in same txn as the side-effect
# ---------------------------------------------------------------------------
def test_inv_same_txn_record_confirms() -> None:
    inbox = InMemoryInboxDeduplicator()
    effect_order: list[str] = []

    def effect() -> None:
        effect_order.append("effect")
        # Inside the same scope the record is staged, not yet in the store.
        assert inbox.store_snapshot == ()

    with inbox.handle("m-1", "orders_consumer", effect) as first:
        assert first is True
    # After commit, both the effect happened AND the record is durable.
    assert effect_order == ["effect"]
    snap = inbox.store_snapshot
    assert len(snap) == 1
    assert snap[0]["message_id"] == "m-1"


def test_inv_same_txn_record_prevents() -> None:
    inbox = InMemoryInboxDeduplicator()
    # Calling record outside any transaction is FORBIDDEN.
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.record("m-1", "c")


def test_inv_same_txn_record_under_failure() -> None:
    inbox = InMemoryInboxDeduplicator()

    def bad_effect() -> None:
        raise RuntimeError("business logic exploded")

    with pytest.raises(RuntimeError):
        with inbox.handle("m-1", "c", bad_effect):
            pass
    # Effect failed → staged record MUST NOT be durable; seen stays False.
    assert inbox.seen("m-1", "c") is False
    assert inbox.store_snapshot == ()


# ---------------------------------------------------------------------------
# INBOX_INV_02 — seen is deterministic, no double-apply
# ---------------------------------------------------------------------------
def test_inv_deterministic_seen_confirms() -> None:
    inbox = InMemoryInboxDeduplicator()
    ran = {"count": 0}

    def effect() -> None:
        ran["count"] += 1

    # First delivery runs the effect.
    with inbox.handle("m-1", "c", effect) as first:
        assert first is True
    # Redelivery: seen returns True deterministically; effect MUST NOT re-run.
    for _ in range(5):
        with inbox.handle("m-1", "c", effect) as again:
            assert again is False
    assert ran["count"] == 1


def test_inv_deterministic_seen_prevents() -> None:
    inbox = InMemoryInboxDeduplicator()
    # Double-record in the same transaction is FORBIDDEN — the caller must
    # gate on `seen` first.
    with inbox.begin() as scope:
        inbox.record("m-1", "c")
        with pytest.raises(InboxDeduplicatorInvariantError):
            inbox.record("m-1", "c")
        scope.rollback()


def test_inv_deterministic_seen_under_failure() -> None:
    inbox = InMemoryInboxDeduplicator()

    def effect() -> None:
        pass

    with inbox.handle("m-1", "c", effect):
        pass
    # Even under repeated racing retries, seen NEVER flips back to False.
    for _ in range(20):
        assert inbox.seen("m-1", "c") is True
    # And a second committed record for the same pair is FORBIDDEN.
    with pytest.raises(InboxDeduplicatorInvariantError):
        with inbox.begin() as scope:
            inbox.record("m-1", "c")
            scope.commit()


# ---------------------------------------------------------------------------
# INBOX_INV_03 — retention covers the minimum redelivery window
# ---------------------------------------------------------------------------
def test_inv_retention_window_confirms() -> None:
    # Purge cutoff older than the minimum retention is accepted and evicts
    # only the records older than the cutoff.
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now - timedelta(days=30)}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    for i in range(3):
        with inbox.handle(f"m-{i}", "c", lambda: None):
            pass

    # Advance the clock to "now" (30 days later) and purge anything older
    # than 14 days (well outside the 7-day min retention).
    clock_state["t"] = now
    cutoff = (now - timedelta(days=14)).isoformat()
    evicted = inbox.purge_older_than(cutoff)
    assert evicted == 3
    assert inbox.store_snapshot == ()


def test_inv_retention_window_prevents() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    # Cutoff 1 day ago → inside the retention window → FORBIDDEN.
    cutoff = (now - timedelta(days=1)).isoformat()
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.purge_older_than(cutoff)


def test_inv_retention_window_under_failure() -> None:
    # A malformed ISO timestamp MUST be rejected (no silent corruption of
    # the retention boundary).
    inbox = InMemoryInboxDeduplicator()
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.purge_older_than("not-a-date")
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.purge_older_than("")
    # Naive (no-tz) timestamps are also rejected — retention math MUST be
    # anchored to UTC to survive DST / host-clock drift.
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.purge_older_than("2026-01-01T00:00:00")


# ---------------------------------------------------------------------------
# INBOX_INV_04 — missing record ALWAYS means first delivery
# ---------------------------------------------------------------------------
def test_inv_missing_means_first_confirms() -> None:
    inbox = InMemoryInboxDeduplicator()
    # Nothing recorded → seen is False for every pair queried.
    assert inbox.seen("m-1", "c") is False
    assert inbox.seen("m-1", "other-consumer") is False
    assert inbox.seen("m-2", "c") is False


def test_inv_missing_means_first_prevents() -> None:
    inbox = InMemoryInboxDeduplicator()
    # Empty / whitespace identifiers are rejected — they would collapse all
    # messages onto one sentinel key and silently reclassify new deliveries
    # as duplicates.
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.seen("", "c")
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.seen("m-1", "")


def test_inv_missing_means_first_under_failure() -> None:
    # After a rolled-back transaction, the staged record is gone — seen
    # MUST return False so the consumer treats the next delivery as first.
    inbox = InMemoryInboxDeduplicator()
    with inbox.begin() as scope:
        inbox.record("m-1", "c")
        assert inbox.seen("m-1", "c") is True  # staged is visible to same-txn seen
        scope.rollback()
    assert inbox.seen("m-1", "c") is False
    assert inbox.store_snapshot == ()
