"""Unit tests for IdentityMap — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from IdentityMap import (
    ConcurrentSessionError,
    IdentityMapInvariantError,
    InMemoryIdentityMap,
    ThreadBoundIdentityMap,
    session_scope,
)


@dataclass
class Order:
    id: int
    total: int = 0


@dataclass
class Customer:
    id: int
    name: str = ""


# ---------------------------------------------------------------------------
# IDMAP_INV_01 — same (type, id) returns the same reference
# ---------------------------------------------------------------------------
def test_inv_same_reference_confirms() -> None:
    imap = InMemoryIdentityMap()
    order = Order(id=1, total=100)
    imap.add(order)
    # Every get MUST return the very same object reference.
    first = imap.get(Order, 1)
    second = imap.get(Order, 1)
    assert first is order
    assert second is order
    assert first is second


def test_inv_same_reference_prevents() -> None:
    imap = InMemoryIdentityMap()
    original = Order(id=7, total=10)
    imap.add(original)
    replacement = Order(id=7, total=999)
    # A second add with a DIFFERENT instance must be rejected so a stale copy
    # cannot silently replace the canonical reference.
    with pytest.raises(IdentityMapInvariantError):
        imap.add(replacement)
    # Canonical reference is still the original.
    assert imap.get(Order, 7) is original


def test_inv_same_reference_under_failure() -> None:
    imap = InMemoryIdentityMap()
    order = Order(id=42)
    imap.add(order)
    # 50 threads concurrently re-add the SAME reference (idempotent) and
    # concurrently read the cached object. The single reference must win.
    lock = threading.Lock()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            imap.add(order)
            got = imap.get(Order, 42)
            assert got is order
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert imap.get(Order, 42) is order


# ---------------------------------------------------------------------------
# IDMAP_INV_02 — no duplicate identity with a different instance
# ---------------------------------------------------------------------------
def test_inv_no_duplicate_identity_confirms() -> None:
    imap = InMemoryIdentityMap()
    a = Order(id=3)
    b = Order(id=4)
    imap.add(a)
    imap.add(b)
    assert imap.get(Order, 3) is a
    assert imap.get(Order, 4) is b


def test_inv_no_duplicate_identity_prevents() -> None:
    imap = InMemoryIdentityMap()
    imap.add(Order(id=9))
    with pytest.raises(IdentityMapInvariantError):
        imap.add(Order(id=9))
    # Passing None must be rejected with a clear INV-02 citation.
    with pytest.raises(IdentityMapInvariantError):
        imap.add(None)


def test_inv_no_duplicate_identity_under_failure() -> None:
    imap = InMemoryIdentityMap()
    canonical = Order(id=100)
    imap.add(canonical)
    # Many threads each try to add a DIFFERENT instance with the same id;
    # every single attempt MUST be rejected, the canonical ref survives.
    lock = threading.Lock()
    rejected = 0

    def attacker() -> None:
        nonlocal rejected
        try:
            imap.add(Order(id=100, total=999))
        except IdentityMapInvariantError:
            with lock:
                rejected += 1

    threads = [threading.Thread(target=attacker) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert rejected == 25
    assert imap.get(Order, 100) is canonical


# ---------------------------------------------------------------------------
# IDMAP_INV_03 — session scoping, never shared across transactions
# ---------------------------------------------------------------------------
def test_inv_session_scoped_confirms() -> None:
    # Two session_scope() invocations produce TWO distinct maps.
    with session_scope(session_id="tx1") as m1:
        m1.add(Order(id=1))
    with session_scope(session_id="tx2") as m2:
        # m2 has no knowledge of tx1's entries — the maps are independent.
        assert m2.get(Order, 1) is None
        m2.add(Order(id=1))
        assert m2.get(Order, 1) is not None


def test_inv_session_scoped_prevents() -> None:
    # ThreadBoundIdentityMap refuses cross-thread access at runtime.
    imap = ThreadBoundIdentityMap()
    imap.add(Order(id=5))
    errors: list[BaseException] = []

    def foreign() -> None:
        try:
            imap.get(Order, 5)
        except ConcurrentSessionError as exc:
            errors.append(exc)

    t = threading.Thread(target=foreign)
    t.start()
    t.join()
    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentSessionError)


def test_inv_session_scoped_under_failure() -> None:
    # If a session_scope raises mid-flight, the map still disposes and cannot
    # be seen by any other transaction.
    captured: list[InMemoryIdentityMap] = []
    with pytest.raises(ValueError):
        with session_scope() as imap:
            captured.append(imap)
            imap.add(Order(id=77))
            raise ValueError("boom")
    assert captured[0].state == "disposed"
    with pytest.raises(IdentityMapInvariantError):
        captured[0].get(Order, 77)


# ---------------------------------------------------------------------------
# IDMAP_INV_04 — dispose clears and forbids further access
# ---------------------------------------------------------------------------
def test_inv_dispose_clears_confirms() -> None:
    imap = InMemoryIdentityMap()
    imap.add(Order(id=1))
    imap.add(Customer(id=1, name="alice"))
    assert imap.size() == 2
    imap.dispose()
    assert imap.state == "disposed"
    # Idempotent.
    imap.dispose()
    assert imap.state == "disposed"


def test_inv_dispose_clears_prevents() -> None:
    imap = InMemoryIdentityMap()
    imap.add(Order(id=1))
    imap.dispose()
    # Every catalog method MUST refuse operation once disposed.
    with pytest.raises(IdentityMapInvariantError):
        imap.get(Order, 1)
    with pytest.raises(IdentityMapInvariantError):
        imap.add(Order(id=2))
    with pytest.raises(IdentityMapInvariantError):
        imap.contains(Order, 1)
    with pytest.raises(IdentityMapInvariantError):
        imap.remove(Order, 1)
    # Context-manager re-entry after dispose is also forbidden.
    with pytest.raises(IdentityMapInvariantError):
        with imap:
            pass  # pragma: no cover — __enter__ should have raised


def test_inv_dispose_clears_under_failure() -> None:
    # Even when many readers race an in-flight dispose(), post-dispose access
    # MUST raise — no reader can see a live reference after the session ends.
    imap = InMemoryIdentityMap()
    for i in range(50):
        imap.add(Order(id=i))

    lock = threading.Lock()
    post_errors: list[BaseException] = []

    def reader() -> None:
        try:
            # Either the map is still open and we get a result OR it is
            # disposed and we see IdentityMapInvariantError — never None
            # after a partial clear.
            _ = imap.get(Order, 0)
        except IdentityMapInvariantError:
            with lock:
                post_errors.append(IdentityMapInvariantError())

    threads = [threading.Thread(target=reader) for _ in range(20)]
    for t in threads:
        t.start()
    imap.dispose()
    for t in threads:
        t.join()
    # Post-dispose, every future get MUST raise.
    with pytest.raises(IdentityMapInvariantError):
        imap.get(Order, 0)
    assert imap.state == "disposed"
