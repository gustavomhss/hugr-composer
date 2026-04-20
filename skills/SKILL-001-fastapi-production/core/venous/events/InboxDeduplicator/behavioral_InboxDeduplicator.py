"""Behavioral end-to-end scenarios for InboxDeduplicator — proves invariants at runtime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from InboxDeduplicator import (
    InboxDeduplicatorInvariantError,
    InMemoryInboxDeduplicator,
)


def test_scenario_at_least_once_transport_yields_exactly_once_effect() -> None:
    """Redelivery simulation: the broker delivers the same message 5x; the
    side-effect runs exactly once (exactly-once-effect = dedupe + atomic txn).
    """
    inbox = InMemoryInboxDeduplicator()
    sent_emails: list[str] = []

    def send_email() -> None:
        sent_emails.append("order-placed@customer")

    # Simulated broker redelivery loop.
    for _ in range(5):
        with inbox.handle("msg-42", "orders_consumer", send_email):
            pass

    assert sent_emails == ["order-placed@customer"]
    assert inbox.seen("msg-42", "orders_consumer") is True


def test_scenario_distinct_consumers_dedupe_independently() -> None:
    """Two consumers observing the same message each run their effect once."""
    inbox = InMemoryInboxDeduplicator()
    orders_log: list[str] = []
    billing_log: list[str] = []

    def orders_effect() -> None:
        orders_log.append("credited")

    def billing_effect() -> None:
        billing_log.append("invoiced")

    # Same message_id, different consumers → both run their effect exactly
    # once; redeliveries to either consumer are idempotent.
    for _ in range(3):
        with inbox.handle("msg-7", "orders", orders_effect):
            pass
        with inbox.handle("msg-7", "billing", billing_effect):
            pass

    assert orders_log == ["credited"]
    assert billing_log == ["invoiced"]


def test_scenario_effect_failure_rolls_back_dedupe_record() -> None:
    """If the side-effect raises, the dedupe record is discarded so the broker
    can safely redeliver and retry (INBOX-INV-01 + INBOX-INV-04)."""
    inbox = InMemoryInboxDeduplicator()
    attempts: list[int] = []
    fail_first = {"yes": True}

    def effect() -> None:
        attempts.append(len(attempts) + 1)
        if fail_first["yes"]:
            fail_first["yes"] = False
            raise RuntimeError("transient DB hiccup")

    with pytest.raises(RuntimeError):
        with inbox.handle("msg-1", "c", effect):
            pass
    assert inbox.seen("msg-1", "c") is False  # no leaked dedupe
    # Broker redelivers → this time effect succeeds and the dedupe is durable.
    with inbox.handle("msg-1", "c", effect) as first:
        assert first is True
    assert attempts == [1, 2]
    assert inbox.seen("msg-1", "c") is True


def test_scenario_retention_window_protects_against_late_redelivery() -> None:
    """A record within the min-retention window survives a purge attempt."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now - timedelta(days=2)}  # record ages by 2 days

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    with inbox.handle("msg-late", "c", lambda: None):
        pass
    clock_state["t"] = now

    # Trying to purge with a cutoff 2 days ago is inside the 7-day window.
    cutoff = (now - timedelta(days=2)).isoformat()
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.purge_older_than(cutoff)

    # Late redelivery on day 29: the record is still there, effect is skipped.
    ran = {"count": 0}

    def effect() -> None:
        ran["count"] += 1

    with inbox.handle("msg-late", "c", effect) as first:
        assert first is False  # caught by dedupe, not re-applied
    assert ran["count"] == 0


def test_scenario_purge_after_retention_reclaims_storage() -> None:
    """After the retention window has passed, purge evicts stale rows."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now - timedelta(days=60)}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    for i in range(10):
        with inbox.handle(f"m-{i}", "c", lambda: None):
            pass
    clock_state["t"] = now

    # Purge at cutoff = 30 days ago (well outside the 7-day retention).
    cutoff = (now - timedelta(days=30)).isoformat()
    evicted = inbox.purge_older_than(cutoff)
    assert evicted == 10
    # All evicted → seen returns False again for those ids.
    for i in range(10):
        assert inbox.seen(f"m-{i}", "c") is False


def test_scenario_consumer_that_forgets_seen_gate_is_caught() -> None:
    """Calling record twice without a seen gate is rejected, so consumers
    can't silently double-apply an effect even if they code it wrong."""
    inbox = InMemoryInboxDeduplicator()
    with inbox.begin() as scope:
        inbox.record("msg-x", "c")
        with pytest.raises(InboxDeduplicatorInvariantError):
            inbox.record("msg-x", "c")
        scope.rollback()


def test_scenario_seen_inside_same_txn_reflects_staged_record() -> None:
    """A consumer that checks `seen` after `record` inside one txn sees True —
    enables intra-txn idempotent retries without violating INBOX-INV-02."""
    inbox = InMemoryInboxDeduplicator()
    with inbox.begin() as scope:
        assert inbox.seen("msg-z", "c") is False
        inbox.record("msg-z", "c")
        assert inbox.seen("msg-z", "c") is True
        scope.commit()
    assert inbox.seen("msg-z", "c") is True
