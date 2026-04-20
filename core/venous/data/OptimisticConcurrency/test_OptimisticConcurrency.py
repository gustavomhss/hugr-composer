"""Tests for OptimisticConcurrency invariants OC_INV_01..05."""

from __future__ import annotations

import threading

import pytest

from core.venous.data.OptimisticConcurrency.OptimisticConcurrency import (
    ConcurrencyError,
    InMemoryOptimisticConcurrency,
    OptimisticConcurrencyError,
)


# ---------------------------------------------------------------------------
# INV_01: atomic CAS — either update lands or raises
# ---------------------------------------------------------------------------
def test_inv_cas_atomic_confirms() -> None:
    store: InMemoryOptimisticConcurrency[int] = InMemoryOptimisticConcurrency()
    v = store.compare_and_swap("k", 0, 1)
    assert v == 1
    _, version = store.read("k")
    assert version == 1


def test_inv_cas_prevents_partial_update_on_conflict() -> None:
    store: InMemoryOptimisticConcurrency[int] = InMemoryOptimisticConcurrency()
    store.compare_and_swap("k", 0, 100)
    with pytest.raises(ConcurrencyError):
        # Stale — stored version is 1, not 0.
        store.compare_and_swap("k", 0, 999)
    # OC_INV_01: the value MUST still be 100.
    val, version = store.read("k")
    assert val == 100 and version == 1


# ---------------------------------------------------------------------------
# INV_02: no hidden retry — conflict surfaces to the caller
# ---------------------------------------------------------------------------
def test_inv_no_hidden_retry_prevents_silent_recovery() -> None:
    store: InMemoryOptimisticConcurrency[str] = InMemoryOptimisticConcurrency()
    store.compare_and_swap("k", 0, "first")
    # Conflict MUST surface — no internal retry swallows the error.
    with pytest.raises(ConcurrencyError) as exc:
        store.compare_and_swap("k", 0, "second")
    assert exc.value.expected_version == 0
    assert exc.value.actual_version == 1


# ---------------------------------------------------------------------------
# INV_03: monotonic gap-free version
# ---------------------------------------------------------------------------
def test_inv_version_monotonic_and_gap_free_confirms() -> None:
    store: InMemoryOptimisticConcurrency[int] = InMemoryOptimisticConcurrency()
    versions: list[int] = []
    v = 0
    for i in range(10):
        v = store.compare_and_swap("k", v, i)
        versions.append(v)
    assert versions == list(range(1, 11))


# ---------------------------------------------------------------------------
# INV_04: no torn reads under concurrent writers
# ---------------------------------------------------------------------------
def test_inv_no_torn_read_confirms() -> None:
    store: InMemoryOptimisticConcurrency[tuple[int, int]] = (
        InMemoryOptimisticConcurrency()
    )
    # Each write puts a SELF-CONSISTENT pair (n, n) into the store.
    # A torn read would see value's two halves drifted.
    store.compare_and_swap("k", 0, (0, 0))
    observed: list[tuple[tuple[int, int] | None, int]] = []

    def writer() -> None:
        v = 1
        for i in range(1, 201):
            try:
                v = store.compare_and_swap("k", v, (i, i))
            except ConcurrencyError:
                _, v = store.read("k")

    def reader() -> None:
        for _ in range(400):
            observed.append(store.read("k"))

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=writer),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for val, _ver in observed:
        assert val is not None
        a, b = val
        # Torn read would yield a != b; the lock prevents that.
        assert a == b, f"torn read: value halves drifted: {val}"


# ---------------------------------------------------------------------------
# INV_05: missing key returns canonical empty
# ---------------------------------------------------------------------------
def test_inv_missing_key_confirms_empty_snapshot() -> None:
    store: InMemoryOptimisticConcurrency[object] = InMemoryOptimisticConcurrency()
    assert store.read("never") == (None, 0)


def test_inv_missing_key_accepts_zero_version_cas() -> None:
    store: InMemoryOptimisticConcurrency[int] = InMemoryOptimisticConcurrency()
    # Writing to a never-existed key MUST succeed with old_version=0.
    v = store.compare_and_swap("new", 0, 42)
    assert v == 1


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def test_invalid_old_version_rejected() -> None:
    store: InMemoryOptimisticConcurrency[int] = InMemoryOptimisticConcurrency()
    with pytest.raises(OptimisticConcurrencyError):
        store.compare_and_swap("k", -1, 0)
