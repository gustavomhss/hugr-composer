"""Tests for SessionCache invariants SC_INV_01..05."""

from __future__ import annotations

import pytest

from core.venous.cache.SessionCache.SessionCache import (
    InMemorySessionCache,
    ReadThroughSessionCache,
    SessionCacheError,
)


class _FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# INV_01: get() is read-only (no mutation on repeated reads)
# ---------------------------------------------------------------------------
def test_inv_get_is_read_only_confirms() -> None:
    clock = _FakeClock(now=0.0)
    cache = InMemorySessionCache(clock=clock)
    cache.set("t1", {"plan": "pro"}, ttl_s=60)
    snapshot_before = dict(cache._store["t1"].__dict__)  # noqa: SLF001
    for _ in range(5):
        cache.get("t1")
    snapshot_after = dict(cache._store["t1"].__dict__)  # noqa: SLF001
    assert snapshot_before == snapshot_after, "get() MUST NOT mutate entry"


# ---------------------------------------------------------------------------
# INV_02: miss returns None; loader error raises SessionCacheError
# ---------------------------------------------------------------------------
def test_inv_miss_returns_none_confirms() -> None:
    cache = InMemorySessionCache()
    assert cache.get("unknown") is None


def test_inv_error_raises_confirms() -> None:
    def broken_loader(_token: str) -> dict | None:
        raise RuntimeError("store down")

    cache = ReadThroughSessionCache(broken_loader, ttl_s=10)
    with pytest.raises(SessionCacheError):
        cache.get("x")


def test_inv_loader_returns_none_is_miss_not_error() -> None:
    def empty_loader(_token: str) -> dict | None:
        return None

    cache = ReadThroughSessionCache(empty_loader, ttl_s=10)
    assert cache.get("x") is None


# ---------------------------------------------------------------------------
# INV_03: invalidate() is idempotent
# ---------------------------------------------------------------------------
def test_inv_invalidate_is_idempotent_confirms() -> None:
    cache = InMemorySessionCache()
    cache.set("t1", {"v": 1}, ttl_s=60)
    cache.invalidate("t1")
    cache.invalidate("t1")  # MUST NOT raise
    cache.invalidate("never-existed")
    assert cache.get("t1") is None


# ---------------------------------------------------------------------------
# INV_04: TTL honored on read
# ---------------------------------------------------------------------------
def test_inv_ttl_honored_confirms() -> None:
    clock = _FakeClock(now=0.0)
    cache = InMemorySessionCache(clock=clock)
    cache.set("t1", {"v": 1}, ttl_s=30)
    assert cache.get("t1") == {"v": 1}
    clock.now = 31.0  # past TTL.
    assert cache.get("t1") is None, "expired entry MUST act like missing"


def test_inv_ttl_rejects_non_positive() -> None:
    cache = InMemorySessionCache()
    with pytest.raises(SessionCacheError):
        cache.set("t1", {"v": 1}, ttl_s=0)


# ---------------------------------------------------------------------------
# INV_05: cold-cache tolerance via ReadThroughSessionCache
# ---------------------------------------------------------------------------
def test_inv_cold_cache_confirms_tolerance() -> None:
    sessions = {"tok-a": {"plan": "enterprise"}}
    calls: list[str] = []

    def loader(token: str) -> dict | None:
        calls.append(token)
        return sessions.get(token)

    node_a = ReadThroughSessionCache(loader, ttl_s=60)
    node_b = ReadThroughSessionCache(loader, ttl_s=60)  # separate node — never seen tok-a

    assert node_a.get("tok-a") == {"plan": "enterprise"}
    # Cold node B resolves via the same external loader — no locality bug.
    assert node_b.get("tok-a") == {"plan": "enterprise"}
    assert calls == ["tok-a", "tok-a"], "each cold node MUST hit the loader once"


# ---------------------------------------------------------------------------
# Defensive copy — caller mutations MUST NOT corrupt the cache
# ---------------------------------------------------------------------------
def test_set_copies_value_to_prevent_caller_mutation() -> None:
    cache = InMemorySessionCache()
    payload = {"plan": "pro"}
    cache.set("t1", payload, ttl_s=30)
    payload["plan"] = "TAMPERED"
    got = cache.get("t1")
    assert got == {"plan": "pro"}, "cache MUST defensive-copy on set"
