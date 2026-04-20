"""Chaos tests for KeyRotationSchedule."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from KeyRotationSchedule import (
    InMemoryKeyRotator,
    KeyRotationSchedule,
    KeyRotationScheduleError,
)


UTC = timezone.utc


def _s(**o: object) -> KeyRotationSchedule:
    base: dict[str, object] = {
        "key_alias": "alias/x",
        "cadence": timedelta(days=30),
        "overlap": timedelta(days=1),
        "next_rotation_at": datetime(2026, 5, 1, tzinfo=UTC),
    }
    base.update(o)
    return KeyRotationSchedule(**base)  # type: ignore[arg-type]


def test_chaos_concurrent_rotations_produce_sequential_versions() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    produced: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        v = r.rotate_now("alias/x")
        with lock:
            produced.append(v)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Versions v2..v21 were produced (initial v1 + 20 rotations); order
    # is concurrent so sort numerically.
    assert sorted(produced, key=lambda v: int(v[1:])) == [f"v{i}" for i in range(2, 22)]


def test_chaos_invalid_schedule_rejected_many_times() -> None:
    for bad in (timedelta(0), timedelta(hours=-1)):
        with pytest.raises(KeyRotationScheduleError):
            _s(overlap=bad)


def test_chaos_active_key_naive_time() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    with pytest.raises(KeyRotationScheduleError):
        r.active_key("alias/x", datetime(2026, 1, 1))


def test_chaos_rotate_unknown_alias_repeatedly() -> None:
    r = InMemoryKeyRotator()
    for _ in range(5):
        with pytest.raises(KeyRotationScheduleError):
            r.rotate_now("no-such")


def test_chaos_rotate_many_times_no_leak_of_versions() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    for _ in range(50):
        r.rotate_now("alias/x")
    assert r.active_key("alias/x", datetime.now(UTC)) == "v51"
