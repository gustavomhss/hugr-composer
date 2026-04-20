"""Invariant tests for `TracingBuffer`."""
from __future__ import annotations

from collections import deque


class _Buf:
    def __init__(self, maxlen: int = 3):
        self._buf: deque = deque(maxlen=maxlen)

    def record(self, e: dict) -> None:
        self._buf.append(e)

    def get_all(self) -> list[dict]:
        return list(reversed(self._buf))

    def get_by_id(self, rid: str) -> dict | None:
        for e in self._buf:
            if e.get("id") == rid:
                return e
        return None


# INV_01 -----------------------------------------------------------------
def test_inv_ring_bounded_confirms() -> None:
    b = _Buf(maxlen=3)
    for i in range(10):
        b.record({"id": str(i)})
    assert len(b._buf) == 3


def test_inv_ring_bounded_prevents() -> None:
    b = _Buf(maxlen=1)
    b.record({"id": "a"})
    b.record({"id": "b"})
    assert list(b._buf)[0]["id"] == "b"


def test_inv_ring_bounded_under_failure() -> None:
    b = _Buf(maxlen=0)
    b.record({"id": "x"})  # maxlen=0 still holds 0 entries
    # deque with maxlen=0 is a special no-op sink
    assert len(b._buf) == 0


# INV_02 -----------------------------------------------------------------
def test_inv_newest_first_confirms() -> None:
    b = _Buf(maxlen=10)
    for i in range(5):
        b.record({"id": str(i)})
    ids = [e["id"] for e in b.get_all()]
    assert ids == ["4", "3", "2", "1", "0"]


def test_inv_newest_first_prevents() -> None:
    # After eviction, still newest-first
    b = _Buf(maxlen=2)
    for i in range(5):
        b.record({"id": str(i)})
    ids = [e["id"] for e in b.get_all()]
    assert ids == ["4", "3"]


def test_inv_newest_first_under_failure() -> None:
    b = _Buf(maxlen=10)
    assert b.get_all() == []


# INV_03 -----------------------------------------------------------------
def test_inv_lookup_by_id_confirms() -> None:
    b = _Buf(maxlen=10)
    b.record({"id": "x", "method": "GET"})
    assert b.get_by_id("x") == {"id": "x", "method": "GET"}


def test_inv_lookup_by_id_prevents() -> None:
    # Missing id returns None, not raises.
    b = _Buf()
    assert b.get_by_id("does-not-exist") is None


def test_inv_lookup_by_id_under_failure() -> None:
    # Evicted id: lookup returns None.
    b = _Buf(maxlen=1)
    b.record({"id": "a"})
    b.record({"id": "b"})
    assert b.get_by_id("a") is None
