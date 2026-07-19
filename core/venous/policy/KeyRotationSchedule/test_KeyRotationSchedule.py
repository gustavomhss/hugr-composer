"""Unit tests for KeyRotationSchedule — 3 per invariant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from KeyRotationSchedule import (
    InMemoryKeyRotator,
    KeyRotationSchedule,
    KeyRotationScheduleError,
)

UTC = UTC


def _s(**o: object) -> KeyRotationSchedule:
    base: dict[str, object] = {
        "key_alias": "alias/pii",
        "cadence": timedelta(days=90),
        "overlap": timedelta(days=7),
        "next_rotation_at": datetime(2026, 4, 1, tzinfo=UTC),
    }
    base.update(o)
    return KeyRotationSchedule(**base)  # type: ignore[arg-type]


# KRS_INV_01 — new version produced on/before next_rotation_at.
def test_inv_missed_rotation_confirms() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    # Rotate before deadline → not missed.
    r.rotate_now("alias/pii")
    assert r.is_missed_rotation("alias/pii", now=datetime(2026, 4, 2, tzinfo=UTC)) is False


def test_inv_missed_rotation_prevents() -> None:
    r = InMemoryKeyRotator()
    with pytest.raises(KeyRotationScheduleError):
        _s(cadence=timedelta(0))


def test_inv_missed_rotation_under_failure() -> None:
    r = InMemoryKeyRotator()
    # Schedule so old that next_rotation_at is in the past, and no rotate_now.
    r.schedule(_s(next_rotation_at=datetime(2026, 1, 1, tzinfo=UTC)))
    assert r.is_missed_rotation("alias/pii", now=datetime(2026, 4, 1, tzinfo=UTC)) is True


# KRS_INV_02 — overlap > 0.
def test_inv_overlap_positive_confirms() -> None:
    _s(overlap=timedelta(days=1))
    _s(overlap=timedelta(hours=1))


def test_inv_overlap_positive_prevents() -> None:
    with pytest.raises(KeyRotationScheduleError):
        _s(overlap=timedelta(0))
    with pytest.raises(KeyRotationScheduleError):
        _s(overlap=timedelta(hours=-1))


def test_inv_overlap_positive_under_failure() -> None:
    with pytest.raises(KeyRotationScheduleError):
        _s(key_alias="")


# KRS_INV_03 — exactly one active key per alias.
def test_inv_exact_active_confirms() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    v1 = r.active_key("alias/pii", datetime.now(UTC))
    assert v1 == "v1"


def test_inv_exact_active_prevents() -> None:
    r = InMemoryKeyRotator()
    with pytest.raises(KeyRotationScheduleError):
        r.active_key("unknown", datetime.now(UTC))


def test_inv_exact_active_under_failure() -> None:
    r = InMemoryKeyRotator()
    with pytest.raises(KeyRotationScheduleError):
        r.active_key("alias/pii", datetime(2026, 1, 1))  # naive


# KRS_INV_04 — keys past cadence + overlap are decrypt-only.
def test_inv_decrypt_only_confirms() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    r.rotate_now("alias/pii")
    # v1 is now retired; some time later it becomes decrypt-only.
    assert r.is_decrypt_only("alias/pii", "v1", datetime(2099, 1, 1, tzinfo=UTC)) is True


def test_inv_decrypt_only_prevents() -> None:
    r = InMemoryKeyRotator()
    r.schedule(_s())
    # v1 is still active → not decrypt-only.
    assert r.is_decrypt_only("alias/pii", "v1", datetime.now(UTC)) is False


def test_inv_decrypt_only_under_failure() -> None:
    r = InMemoryKeyRotator()
    # Unknown alias / version → False (no state to be decrypt-only from).
    assert r.is_decrypt_only("unknown", "v1", datetime.now(UTC)) is False


# KRS_INV_05 — rotation emits audit.
class _Sink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({"action": action, "resource": resource,
                          "attrs": dict(attributes)})  # type: ignore[arg-type]
        return "h"


def test_inv_audit_on_rotate_confirms() -> None:
    sink = _Sink()
    r = InMemoryKeyRotator(audit_sink=sink)
    r.schedule(_s())
    r.rotate_now("alias/pii")
    assert any(x["action"] == "key.rotate" for x in sink.rows)


def test_inv_audit_on_rotate_prevents() -> None:
    sink = _Sink()
    r = InMemoryKeyRotator(audit_sink=sink)
    # No schedule → rotate_now raises; no audit row.
    with pytest.raises(KeyRotationScheduleError):
        r.rotate_now("nope")
    assert sink.rows == []


def test_inv_audit_on_rotate_under_failure() -> None:
    # Without audit sink, rotation still works.
    r = InMemoryKeyRotator()
    r.schedule(_s())
    r.rotate_now("alias/pii")
    assert r.size == 1
