"""Unit tests for the IdempotencyStore primitive.

IdempotencyStore is a thread-safe in-memory dict facade for batch-
request replay protection. The tests below exercise the three
invariants a caller relies on:

- IS_INV_01 — ``get`` returns the stored result after ``put``; ``None``
  when never put.
- IS_INV_02 — ``seen`` is equivalent to ``get(...) is not None`` — a
  boolean shortcut that stays in sync with ``get``.
- IS_INV_03 — concurrent ``put`` calls never race: the store observes
  every write and no write is dropped / torn.
"""
from __future__ import annotations

import threading

from IdempotencyStore import IdempotencyStore


# ---------------------------------------------------------------------------
# IS_INV_01 — get-after-put / get-when-empty
# ---------------------------------------------------------------------------
def test_inv_get_confirms() -> None:
    store = IdempotencyStore()
    store.put("req-1", {"status": "ok", "id": 42})
    assert store.get("req-1") == {"status": "ok", "id": 42}


def test_inv_get_returns_none_when_never_put() -> None:
    store = IdempotencyStore()
    assert store.get("missing") is None


def test_inv_put_overwrites_existing_key() -> None:
    store = IdempotencyStore()
    store.put("req-1", "first")
    store.put("req-1", "second")
    assert store.get("req-1") == "second"


# ---------------------------------------------------------------------------
# IS_INV_02 — seen == (get is not None)
# ---------------------------------------------------------------------------
def test_inv_get_prevents() -> None:
    store = IdempotencyStore()
    assert store.seen("req-x") is False
    store.put("req-x", "result")
    assert store.seen("req-x") is True


def test_inv_seen_tracks_get_exactly() -> None:
    store = IdempotencyStore()
    for key in ("a", "b", "c"):
        assert store.seen(key) is (store.get(key) is not None)
    store.put("a", "value-a")
    for key in ("a", "b", "c"):
        assert store.seen(key) is (store.get(key) is not None)


# ---------------------------------------------------------------------------
# IS_INV_03 — concurrent writes are serialised by the internal lock
# ---------------------------------------------------------------------------
def test_inv_get_under_failure() -> None:
    """Concurrent puts never drop a write and never tear a value.

    Launches 50 threads, each writing 20 unique keys. Final store
    size MUST equal 50 * 20 = 1000 distinct entries and every value
    must match its key's expected payload.
    """
    store = IdempotencyStore()
    threads_n, per_thread = 50, 20

    def _writer(tid: int) -> None:
        for i in range(per_thread):
            store.put(f"t{tid}-k{i}", f"v{tid}-{i}")

    threads = [threading.Thread(target=_writer, args=(tid,)) for tid in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for tid in range(threads_n):
        for i in range(per_thread):
            assert store.get(f"t{tid}-k{i}") == f"v{tid}-{i}"
    # Also assert the internal dict carries exactly threads_n * per_thread
    # keys — no duplicate, no missed write.
    assert sum(
        1
        for tid in range(threads_n)
        for i in range(per_thread)
        if store.seen(f"t{tid}-k{i}")
    ) == threads_n * per_thread


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_put_accepts_arbitrary_values() -> None:
    """Store is result-agnostic — dict / list / None / dataclass all OK."""
    store = IdempotencyStore()
    payloads: list[object] = [
        {"shape": "dict"},
        ["a", "b", 1],
        ("tuple", "items"),
        42,
        None,
        "string",
    ]
    for i, payload in enumerate(payloads):
        store.put(f"k{i}", payload)
    for i, payload in enumerate(payloads):
        assert store.get(f"k{i}") == payload


def test_put_none_value_is_retrievable_and_seen() -> None:
    """Putting None is distinct from never putting — seen() must say True."""
    store = IdempotencyStore()
    store.put("req-nullable", None)
    assert store.get("req-nullable") is None
    assert store.seen("req-nullable") is True
