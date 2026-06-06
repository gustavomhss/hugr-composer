"""Tests for the mobile-backend example."""
from __future__ import annotations

import pytest

from app import (
    BatchItem,
    ConflictError,
    DeviceRegistry,
    SyncStore,
    apply_batch,
)


def test_conflicting_updates_one_winner_both_converge() -> None:
    store = SyncStore()
    store.write("r1", {"v": 1}, expected_rev=0)
    # Both clients saw rev=1. They race to update.
    store.write("r1", {"v": 2}, expected_rev=1)
    with pytest.raises(ConflictError) as exc:
        store.write("r1", {"v": 3}, expected_rev=1)
    assert exc.value.current_rev == 2
    # Loser re-syncs and writes with the fresh rev — convergence.
    final = store.write("r1", {"v": 3}, expected_rev=2)
    assert final.value == {"v": 3}


def test_push_prunes_stale_tokens() -> None:
    def fake_send(token: str, msg: str) -> str:
        return "stale" if token.startswith("bad") else "ok"

    reg = DeviceRegistry(fake_send)
    reg.register("alice", "good-1")
    reg.register("alice", "good-2")
    reg.register("alice", "bad-1")
    delivered, pruned = reg.push("alice", "hi")
    assert delivered == 2
    assert pruned == 1
    assert "bad-1" not in reg.tokens("alice")


def test_sync_cursor_is_monotonic() -> None:
    store = SyncStore()
    r1 = store.write("a", {}, expected_rev=0)
    r2 = store.write("b", {}, expected_rev=0)
    r3 = store.write("a", {"v": 2}, expected_rev=r1.rev)
    # since(cursor=r1.rev) should include r2 and r3 but not r1.
    recs = store.since(cursor=r1.rev)
    revs = [r.rev for r in recs]
    assert revs == sorted(revs)
    assert all(rv > r1.rev for rv in revs)
    assert r3.rev > r2.rev > r1.rev


def test_batch_atomic_or_precise_per_item_errors() -> None:
    store = SyncStore()
    store.write("a", {}, expected_rev=0)

    # One item conflicts; batch must NOT commit anything.
    items = [
        BatchItem("a", {"v": 1}, expected_rev=99),   # conflict
        BatchItem("b", {"v": 2}, expected_rev=0),    # would be ok
    ]
    result = apply_batch(store, items)
    assert result.ok == []
    assert "a" in result.errors
    # "b" must NOT have been written.
    assert store.get("b") is None


def test_batch_commits_all_when_valid() -> None:
    store = SyncStore()
    items = [BatchItem(f"r{i}", {"i": i}, expected_rev=0) for i in range(100)]
    result = apply_batch(store, items)
    assert len(result.ok) == 100
    assert result.errors == {}
    assert store.get("r50").value == {"i": 50}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
