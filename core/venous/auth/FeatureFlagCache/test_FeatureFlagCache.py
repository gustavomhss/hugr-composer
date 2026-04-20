"""Invariant tests for `FeatureFlagCache`.

Synchronous reference model — the staged impl uses asyncio.Lock, which
does not change semantics for these invariants.
"""
from __future__ import annotations

from collections import OrderedDict


class _Cache:
    def __init__(self, ttl: float = 60.0, max_size: int = 3):
        self._ttl = ttl
        self._max = max_size
        self._store: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()

    def _now(self) -> float:
        return self._time

    _time = 0.0

    def tick(self, delta: float) -> None:
        self._time += delta

    def get(self, k: str) -> dict | None:
        e = self._store.get(k)
        if e is None: return None
        stored_at, v = e
        if self._now() - stored_at > self._ttl:
            del self._store[k]
            return None
        self._store.move_to_end(k)
        return v

    def set(self, k: str, v: dict) -> None:
        self._store[k] = (self._now(), v)
        self._store.move_to_end(k)
        while len(self._store) > self._max:
            self._store.popitem(last=False)


# INV_01 -----------------------------------------------------------------
def test_inv_ttl_eviction_confirms() -> None:
    c = _Cache(ttl=10.0)
    c.set("k", {"v": 1})
    c.tick(11.0)
    assert c.get("k") is None
    assert "k" not in c._store  # removed read-through


def test_inv_ttl_eviction_prevents() -> None:
    # Non-expired entry is NOT removed.
    c = _Cache(ttl=100.0)
    c.set("k", {"v": 1})
    c.tick(5.0)
    assert c.get("k") == {"v": 1}
    assert "k" in c._store


def test_inv_ttl_eviction_under_failure() -> None:
    # TTL=0 -> every entry is stale by the next tick.
    c = _Cache(ttl=0.0)
    c.set("k", {"v": 1})
    c.tick(0.001)
    assert c.get("k") is None


# INV_02 -----------------------------------------------------------------
def test_inv_lru_capacity_confirms() -> None:
    c = _Cache(max_size=2)
    c.set("a", {}); c.set("b", {}); c.set("c", {})
    assert len(c._store) == 2
    assert "a" not in c._store  # LRU evicted


def test_inv_lru_capacity_prevents() -> None:
    # Never exceeds cap, even on a burst of writes.
    c = _Cache(max_size=5)
    for i in range(100):
        c.set(f"k{i}", {})
        assert len(c._store) <= 5


def test_inv_lru_capacity_under_failure() -> None:
    c = _Cache(max_size=1)
    c.set("a", {}); c.set("b", {})
    assert list(c._store.keys()) == ["b"]


# INV_03 -----------------------------------------------------------------
def test_inv_write_then_read_confirms() -> None:
    c = _Cache(ttl=100.0)
    c.set("k", {"v": 42})
    assert c.get("k") == {"v": 42}


def test_inv_write_then_read_prevents() -> None:
    # Two writes: the second value wins.
    c = _Cache(ttl=100.0)
    c.set("k", {"v": 1})
    c.set("k", {"v": 2})
    assert c.get("k") == {"v": 2}


def test_inv_write_then_read_under_failure() -> None:
    c = _Cache(ttl=100.0, max_size=1)
    c.set("k", {"v": 1})
    c.set("other", {"v": 2})  # evicts "k"
    assert c.get("k") is None
