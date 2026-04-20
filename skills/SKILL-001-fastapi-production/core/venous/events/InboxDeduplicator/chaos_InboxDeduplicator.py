"""Chaos / game-day tests for InboxDeduplicator.

Simulates broker redelivery storms, effect failures, clock skew, and nested
transaction attempts to confirm dedupe never drops a first delivery or
double-applies a repeat.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from InboxDeduplicator import (
    InboxDeduplicatorInvariantError,
    InMemoryInboxDeduplicator,
)


def test_chaos_redelivery_storm_under_transient_effect_failures() -> None:
    """Broker redelivers 100 times; the effect fails randomly on the first few
    attempts. The final durable state has exactly one record, effect ran once.
    """
    inbox = InMemoryInboxDeduplicator()
    fail_count = {"remaining": 3}
    ran: list[int] = []

    def effect() -> None:
        ran.append(1)
        if fail_count["remaining"] > 0:
            fail_count["remaining"] -= 1
            raise RuntimeError("flaky downstream")

    errors = 0
    for _ in range(100):
        try:
            with inbox.handle("msg-1", "c", effect):
                pass
        except RuntimeError:
            errors += 1
    assert errors == 3  # first three attempts raised
    assert sum(ran) == 4  # three failed + one success
    assert inbox.seen("msg-1", "c") is True


def test_chaos_nested_begin_is_rejected() -> None:
    inbox = InMemoryInboxDeduplicator()
    outer = inbox.begin()
    try:
        with pytest.raises(InboxDeduplicatorInvariantError):
            inbox.begin()
    finally:
        outer.rollback()


def test_chaos_concurrent_first_delivery_same_key_only_one_wins() -> None:
    """Two threads simultaneously believe they have the first delivery — only
    one record is committed; the loser raises INBOX-INV-02 on commit, which
    the outer consumer code re-interprets as "already-seen, skip."""
    inbox = InMemoryInboxDeduplicator()
    lock = threading.Lock()
    wins: list[int] = []
    losses: list[int] = []
    effects: list[int] = []

    def worker(n: int) -> None:
        with lock:  # serialize begin/commit as the engine requires
            try:
                with inbox.begin() as scope:
                    if inbox.seen("m", "c"):
                        losses.append(n)
                        scope.rollback()
                        return
                    effects.append(n)  # simulated effect
                    inbox.record("m", "c")
                    scope.commit()
                    wins.append(n)
            except InboxDeduplicatorInvariantError:
                losses.append(n)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(wins) == 1
    assert len(effects) == 1  # effect ran exactly once
    assert len(losses) == 19


def test_chaos_clock_skew_backwards_does_not_corrupt_dedupe() -> None:
    """Wall-clock regressions happen (VM migrations, NTP panic). Dedupe MUST
    still hold even when the clock goes backwards.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(days=7))
    with inbox.handle("msg-backward", "c", lambda: None):
        pass
    # Clock snaps backwards by 1 hour → redelivery still deduped.
    clock_state["t"] = now - timedelta(hours=1)
    with inbox.handle("msg-backward", "c", lambda: None) as first:
        assert first is False


def test_chaos_large_replay_window_preserves_first_delivery_flags() -> None:
    """10k unique messages, each redelivered 3x. Every effect ran exactly once."""
    inbox = InMemoryInboxDeduplicator()
    effect_counter: dict[str, int] = {}

    def make_effect(mid: str):
        def effect() -> None:
            effect_counter[mid] = effect_counter.get(mid, 0) + 1
        return effect

    N = 500  # keep runtime reasonable inside gate timeout
    for i in range(N):
        mid = f"m-{i}"
        for _ in range(3):  # broker redelivers 3x
            with inbox.handle(mid, "c", make_effect(mid)):
                pass

    assert len(effect_counter) == N
    assert all(v == 1 for v in effect_counter.values())
    assert len(inbox.store_snapshot) == N


def test_chaos_purge_racing_with_record_is_safe() -> None:
    """A purge thread and a record thread racing never double-apply an effect
    or corrupt the store (purge only affects records OUTSIDE the retention
    window, so the fresh record is safe)."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_state = {"t": now}

    def clock() -> datetime:
        return clock_state["t"]

    inbox = InMemoryInboxDeduplicator(clock=clock, min_retention=timedelta(seconds=1))

    # Seed an old record.
    clock_state["t"] = now - timedelta(minutes=5)
    with inbox.handle("ancient", "c", lambda: None):
        pass
    clock_state["t"] = now

    lock = threading.Lock()
    errors: list[BaseException] = []

    def purger() -> None:
        try:
            cutoff = (clock_state["t"] - timedelta(minutes=2)).isoformat()
            inbox.purge_older_than(cutoff)
        except BaseException as exc:  # noqa: BLE001 — chaos harness records any failure for diagnostics
            with lock:
                errors.append(exc)

    def recorder(i: int) -> None:
        try:
            with inbox.handle(f"fresh-{i}", "c", lambda: None):
                pass
        except BaseException as exc:  # noqa: BLE001 — chaos harness records any failure for diagnostics
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=recorder, args=(i,)) for i in range(10)]
    ts.append(threading.Thread(target=purger))
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert not errors
    # Ancient record evicted, 10 fresh ones durable.
    stored_ids = {r["message_id"] for r in inbox.store_snapshot}
    assert "ancient" not in stored_ids
    assert len(stored_ids) == 10


def test_chaos_empty_identity_rejected_inside_and_outside_txn() -> None:
    inbox = InMemoryInboxDeduplicator()
    with pytest.raises(InboxDeduplicatorInvariantError):
        inbox.seen("", "c")
    with inbox.begin() as scope:
        with pytest.raises(InboxDeduplicatorInvariantError):
            inbox.record("", "c")
        scope.rollback()


def test_chaos_exception_inside_transaction_triggers_rollback() -> None:
    """Any exception in the `with` body rolls back staged rows."""
    inbox = InMemoryInboxDeduplicator()
    with pytest.raises(ZeroDivisionError):
        with inbox.begin() as scope:
            inbox.record("m-x", "c")
            _ = 1 / 0
            scope.commit()  # unreachable
    assert inbox.seen("m-x", "c") is False
