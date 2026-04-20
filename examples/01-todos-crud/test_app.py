"""Tests for the todos example — owner semantics + keyset page invariants."""
from __future__ import annotations

import pytest

from app import TodoRepository, owner_scoped_patch


def test_cross_owner_patch_returns_404_never_403() -> None:
    repo = TodoRepository()
    alice = repo.create("alice", "buy milk")
    # Bob tries to flip Alice's todo; must get 404 (anti-enumeration).
    status, row = owner_scoped_patch(repo, "bob", alice.id, done=True)
    assert status == 404
    assert row is None


def test_owner_can_patch_own_todo() -> None:
    repo = TodoRepository()
    t = repo.create("alice", "buy milk")
    status, row = owner_scoped_patch(repo, "alice", t.id, done=True)
    assert status == 200
    assert row is not None and row.done is True


def test_keyset_pagination_no_dup_no_skip_under_concurrent_other_owner_inserts() -> None:
    repo = TodoRepository()
    # Seed 25 todos for Alice.
    for i in range(25):
        repo.create("alice", f"alice-{i}")

    seen: list[int] = []
    cursor: tuple | None = None
    # Page size 10; between each page another owner inserts — must not shift Alice's view.
    page_count = 0
    while True:
        page, cursor = repo.list_page("alice", cursor=cursor, size=10)
        seen.extend(t.id for t in page)
        page_count += 1
        # Simulate a concurrent insert by another user — should NOT affect Alice.
        repo.create("bob", f"bob-{page_count}")
        if cursor is None:
            break

    # Invariant: every alice id seen exactly once.
    assert sorted(seen) == sorted({t.id for t in repo._rows.values() if t.owner_id == "alice"})
    assert len(seen) == len(set(seen)), "duplicates in paginated view"


def test_listing_excludes_other_owners() -> None:
    repo = TodoRepository()
    repo.create("alice", "a1")
    repo.create("bob", "b1")
    page, _ = repo.list_page("alice", cursor=None, size=100)
    assert all(t.owner_id == "alice" for t in page)
    assert len(page) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
