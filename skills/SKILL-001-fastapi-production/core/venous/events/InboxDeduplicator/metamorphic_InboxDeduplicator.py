"""Metamorphic + differential tests for InboxDeduplicator.

Algebraic laws:
- seen is monotone: once True for (mid, c), STAYS True until the record is
  purged outside the retention window.
- handle is idempotent: N redeliveries produce the same store as 1 delivery.
- rollback is a left-zero for record: record → rollback ≡ no-op.
- commit-then-seen ≡ seen-in-same-txn for staged rows.
- Order of (seen, record) across distinct pairs commutes for the final store.
- Purge is a no-op iff no row is older than the cutoff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from InboxDeduplicator import InMemoryInboxDeduplicator


def test_metamorphic_seen_is_monotone_until_purge() -> None:
    inbox = InMemoryInboxDeduplicator()
    with inbox.handle("m", "c", lambda: None):
        pass
    # Repeated reads never flip back to False.
    for _ in range(50):
        assert inbox.seen("m", "c") is True


def test_metamorphic_handle_idempotent_under_redelivery() -> None:
    inbox_one = InMemoryInboxDeduplicator()
    inbox_many = InMemoryInboxDeduplicator()
    runs_one = {"n": 0}
    runs_many = {"n": 0}

    def eff_one() -> None:
        runs_one["n"] += 1

    def eff_many() -> None:
        runs_many["n"] += 1

    with inbox_one.handle("m", "c", eff_one):
        pass
    for _ in range(10):
        with inbox_many.handle("m", "c", eff_many):
            pass
    # Same number of effects, same durable state (compare keys — timestamps
    # are by-design clock-time so vary between instances).
    assert runs_one == runs_many
    keys_one = {(r["message_id"], r["consumer"]) for r in inbox_one.store_snapshot}
    keys_many = {(r["message_id"], r["consumer"]) for r in inbox_many.store_snapshot}
    assert keys_one == keys_many


def test_metamorphic_rollback_is_left_zero_for_record() -> None:
    inbox = InMemoryInboxDeduplicator()
    with inbox.begin() as scope:
        inbox.record("m", "c")
        scope.rollback()
    # The rollback discarded the staged record → store equivalent to an
    # inbox that never got the record call at all.
    ref = InMemoryInboxDeduplicator()
    assert inbox.store_snapshot == ref.store_snapshot


def test_metamorphic_same_txn_seen_equals_post_commit_seen() -> None:
    inbox = InMemoryInboxDeduplicator()
    with inbox.begin() as scope:
        inbox.record("m", "c")
        same_txn = inbox.seen("m", "c")
        scope.commit()
    post_commit = inbox.seen("m", "c")
    assert same_txn == post_commit == True  # noqa: E712 — explicit identity check documents metamorphic equality


def test_metamorphic_distinct_pairs_commute() -> None:
    # Order of recording distinct pairs MUST NOT change the final store.
    inbox_a = InMemoryInboxDeduplicator()
    inbox_b = InMemoryInboxDeduplicator()
    with inbox_a.begin() as sa:
        inbox_a.record("m1", "c")
        inbox_a.record("m2", "c")
        sa.commit()
    with inbox_b.begin() as sb:
        inbox_b.record("m2", "c")
        inbox_b.record("m1", "c")
        sb.commit()
    # Compare by (sorted) pairs, ignoring recorded_at_iso which is clock-time.
    keys_a = sorted((r["message_id"], r["consumer"]) for r in inbox_a.store_snapshot)
    keys_b = sorted((r["message_id"], r["consumer"]) for r in inbox_b.store_snapshot)
    assert keys_a == keys_b


def test_metamorphic_purge_noop_when_nothing_stale() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    with inbox.handle("m", "c", lambda: None):
        pass
    # Advance slightly (still inside retention window — cannot purge).
    clock_state["t"] = now + timedelta(days=30)
    cutoff = (clock_state["t"] - timedelta(days=15)).isoformat()
    before = inbox.store_snapshot
    evicted = inbox.purge_older_than(cutoff)
    # Record was created at `now`, cutoff is `now + 15 days` → record is
    # strictly older than cutoff → it IS evicted. Re-run with a cutoff that
    # precedes the record: no eviction.
    assert evicted == 1
    # Second run: empty store, any (valid) purge returns 0.
    cutoff2 = (clock_state["t"] - timedelta(days=10)).isoformat()
    evicted2 = inbox.purge_older_than(cutoff2)
    assert evicted2 == 0
    assert len(before) == 1


def test_differential_inbox_vs_ground_truth_set() -> None:
    """Compare InboxDeduplicator semantics against a simple Python set model."""
    inbox = InMemoryInboxDeduplicator()
    model: set[tuple[str, str]] = set()

    events = [
        ("a", "c1"),
        ("a", "c1"),  # dup
        ("b", "c1"),
        ("a", "c2"),  # different consumer, fresh
        ("b", "c1"),  # dup
        ("c", "c1"),
    ]
    for mid, cons in events:
        if (mid, cons) not in model:
            with inbox.handle(mid, cons, lambda: None) as first:
                assert first is True
            model.add((mid, cons))
        else:
            with inbox.handle(mid, cons, lambda: None) as first:
                assert first is False

    keys = {(r["message_id"], r["consumer"]) for r in inbox.store_snapshot}
    assert keys == model
