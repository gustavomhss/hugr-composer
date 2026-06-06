"""Tests for realtime-chat example."""
from __future__ import annotations

import pytest

from app import ConnectionBulkhead, DrainCoordinator, OffsetCache, RoomStream


def test_publish_assigns_monotonic_offsets_per_room() -> None:
    s = RoomStream()
    a1 = s.publish("alpha", "u1", "hi")
    a2 = s.publish("alpha", "u2", "there")
    b1 = s.publish("beta", "u3", "first")
    assert a1.offset == 1 and a2.offset == 2 and b1.offset == 1


def test_reconnect_replays_missed_messages_in_order_no_dup() -> None:
    s = RoomStream()
    cache = OffsetCache(ttl_s=30.0)

    # Client connects, receives m1.
    m1 = s.publish("alpha", "u1", "one")
    cache.set("conn-1", m1.offset, now=100.0)

    # Client disconnects. Messages m2, m3 arrive while away.
    m2 = s.publish("alpha", "u1", "two")
    m3 = s.publish("alpha", "u1", "three")

    # Reconnect within TTL — replay from last-seen offset.
    last = cache.get("conn-1", now=105.0)
    assert last == 1
    missed = s.replay("alpha", since=last)
    assert [m.offset for m in missed] == [m2.offset, m3.offset]  # strict order
    assert len(set(m.offset for m in missed)) == len(missed)      # no dup


def test_session_cache_ttl_expiry_drops_offset() -> None:
    cache = OffsetCache(ttl_s=30.0)
    cache.set("conn-1", 42, now=100.0)
    assert cache.get("conn-1", now=129.0) == 42  # within TTL
    assert cache.get("conn-1", now=131.0) is None  # expired


def test_bulkhead_caps_per_user_per_room() -> None:
    bh = ConnectionBulkhead(max_per_room=3)
    assert all(bh.open("alice", "general") for _ in range(3))
    assert bh.open("alice", "general") is False        # 4th refused
    assert bh.open("alice", "random") is True          # different room ok
    assert bh.open("bob", "general") is True           # different user ok
    bh.close("alice", "general")
    assert bh.open("alice", "general") is True         # slot freed


def test_drain_coordinator_emits_reconnect_hint_for_connected_clients() -> None:
    d = DrainCoordinator()
    d.begin_drain(["c1", "c2", "c3"])
    assert d.draining is True
    assert d.drained_hints() == ["c1", "c2", "c3"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
