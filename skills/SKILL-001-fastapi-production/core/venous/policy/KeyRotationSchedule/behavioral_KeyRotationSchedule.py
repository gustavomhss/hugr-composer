"""Behavioral scenarios for KeyRotationSchedule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from KeyRotationSchedule import (
    InMemoryKeyRotator,
    KeyRotationSchedule,
    KeyRotationScheduleError,
)


UTC = timezone.utc


def test_scenario_quarterly_rotation_flow() -> None:
    r = InMemoryKeyRotator()
    r.schedule(KeyRotationSchedule(
        key_alias="alias/pii",
        cadence=timedelta(days=90),
        overlap=timedelta(days=7),
        next_rotation_at=datetime(2026, 4, 1, tzinfo=UTC),
    ))
    r.rotate_now("alias/pii")
    # rotate_now stamps at wall_now; v2 is active at any forward query.
    future = datetime.now(UTC) + timedelta(seconds=1)
    assert r.active_key("alias/pii", future) == "v2"


def test_scenario_overlap_decrypts_prior_version() -> None:
    r = InMemoryKeyRotator()
    r.schedule(KeyRotationSchedule(
        key_alias="alias/pci",
        cadence=timedelta(days=30),
        overlap=timedelta(days=1),
        next_rotation_at=datetime(2026, 5, 1, tzinfo=UTC),
    ))
    r.rotate_now("alias/pci")
    # v1 retired_at = wall_now + 1 day; within overlap it stays decrypt-usable.
    within_overlap = datetime.now(UTC) + timedelta(hours=1)
    assert r.is_decrypt_only("alias/pci", "v1", within_overlap) is False


def test_scenario_missed_rotation_alert() -> None:
    r = InMemoryKeyRotator()
    r.schedule(KeyRotationSchedule(
        key_alias="alias/old",
        cadence=timedelta(days=30),
        overlap=timedelta(days=1),
        next_rotation_at=datetime(2026, 1, 1, tzinfo=UTC),
    ))
    assert r.is_missed_rotation("alias/old", now=datetime(2026, 3, 1, tzinfo=UTC)) is True


def test_scenario_overlap_zero_rejected() -> None:
    with pytest.raises(KeyRotationScheduleError):
        KeyRotationSchedule(
            key_alias="alias/x",
            cadence=timedelta(days=30),
            overlap=timedelta(0),
            next_rotation_at=datetime(2026, 5, 1, tzinfo=UTC),
        )


def test_scenario_rotate_without_schedule_rejected() -> None:
    r = InMemoryKeyRotator()
    with pytest.raises(KeyRotationScheduleError):
        r.rotate_now("no-alias")
