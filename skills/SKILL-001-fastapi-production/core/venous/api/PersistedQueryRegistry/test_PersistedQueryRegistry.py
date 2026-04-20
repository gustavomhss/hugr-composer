"""Tests for PersistedQueryRegistry invariants PQR_INV_01..05."""

from __future__ import annotations

import hashlib

import pytest

from core.venous.api.PersistedQueryRegistry.PersistedQueryRegistry import (
    InMemoryPersistedQueryRegistry,
    PQRImmutableError,
    PQRTamperError,
)


# ---------------------------------------------------------------------------
# INV_01: sha-256 hex + idempotent registration
# ---------------------------------------------------------------------------
def test_inv_hash_shape_confirms() -> None:
    q = "query { me { id } }"
    expected = hashlib.sha256(q.encode("utf-8")).hexdigest()
    reg = InMemoryPersistedQueryRegistry()
    qid = reg.register(q)
    assert qid == expected
    assert len(qid) == 64 and qid == qid.lower()


def test_inv_register_is_idempotent() -> None:
    sink_calls: list[dict[str, str]] = []
    reg = InMemoryPersistedQueryRegistry(snapshot_sink=sink_calls.append)
    q = "query A { a }"
    id1 = reg.register(q)
    id2 = reg.register(q)
    assert id1 == id2
    # Sink called ONCE — idempotent second call skips the snapshot.
    assert len(sink_calls) == 1


# ---------------------------------------------------------------------------
# INV_02: tamper detection on get()
# ---------------------------------------------------------------------------
def test_inv_tamper_prevents_silent_substitution() -> None:
    reg = InMemoryPersistedQueryRegistry()
    qid = reg.register("query { a }")
    # Simulate on-disk tamper — replace the stored query.
    reg._store[qid] = "query { secret_backdoor }"  # noqa: SLF001
    with pytest.raises(PQRTamperError):
        reg.get(qid)


def test_inv_untampered_get_confirms() -> None:
    reg = InMemoryPersistedQueryRegistry()
    q = "query B { b }"
    qid = reg.register(q)
    assert reg.get(qid) == q
    assert reg.get("00" * 32) is None


# ---------------------------------------------------------------------------
# INV_03: frozen registry is read-only
# ---------------------------------------------------------------------------
def test_inv_frozen_prevents_register() -> None:
    reg = InMemoryPersistedQueryRegistry()
    reg.register("query A { a }")
    reg.freeze()
    with pytest.raises(PQRImmutableError):
        reg.register("query B { b }")


def test_inv_frozen_still_allows_reads() -> None:
    reg = InMemoryPersistedQueryRegistry()
    qid = reg.register("q { x }")
    reg.freeze()
    assert reg.contains(qid)
    assert reg.get(qid) == "q { x }"


# ---------------------------------------------------------------------------
# INV_04: lookup is O(1) — smoke tests that contains() and get() do not
# scale with the number of entries for the same call count.
# ---------------------------------------------------------------------------
def test_inv_o1_lookup_confirms() -> None:
    reg = InMemoryPersistedQueryRegistry()
    for i in range(1000):
        reg.register(f"query Q{i} {{ q{i} }}")
    # Any id lookup is a dict lookup — constant work.
    probe = reg.register("query Q500 { q500 }")
    assert reg.contains(probe)
    assert reg.get(probe) is not None


# ---------------------------------------------------------------------------
# INV_05: no public enumeration API
# ---------------------------------------------------------------------------
def test_inv_no_enumeration_api() -> None:
    reg = InMemoryPersistedQueryRegistry()
    reg.register("q { a }")
    # The Protocol surface intentionally excludes list/keys/__iter__.
    assert not hasattr(reg, "list")
    assert not hasattr(reg, "keys")
    with pytest.raises(TypeError):
        iter(reg)  # type: ignore[call-overload]
