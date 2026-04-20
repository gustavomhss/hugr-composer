"""Metamorphic tests for KeyRotationSchedule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from KeyRotationSchedule import InMemoryKeyRotator, KeyRotationSchedule


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


def test_metamorphic_version_numbers_monotonic() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    versions = [r.rotate_now("alias/x") for _ in range(4)]
    assert versions == ["v2", "v3", "v4", "v5"]


def test_metamorphic_active_key_newest_at_now() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    r.rotate_now("alias/x")
    r.rotate_now("alias/x")
    assert r.active_key("alias/x", datetime.now(UTC)) == "v3"


def test_metamorphic_rotation_idempotent_in_schedule_registration() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    r.schedule(_s())  # re-schedule same alias
    assert r.size == 1


def test_differential_two_aliases_independent() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s(key_alias="alias/a"))
    r.schedule(_s(key_alias="alias/b"))
    r.rotate_now("alias/a")
    assert r.active_key("alias/b", datetime.now(UTC)) == "v1"


def test_metamorphic_missed_rotation_resets_after_rotate() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s(next_rotation_at=datetime(2026, 1, 1, tzinfo=UTC)))
    assert r.is_missed_rotation("alias/x", now=datetime(2026, 3, 1, tzinfo=UTC)) is True
    r.rotate_now("alias/x")
    assert r.is_missed_rotation("alias/x", now=datetime(2026, 3, 1, tzinfo=UTC)) is False
