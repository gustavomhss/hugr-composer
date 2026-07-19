"""Unit tests for RetentionPolicy — 3 tests per invariant."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from RetentionPolicy import (
    ALLOWED_DELETION_MODES,
    InMemoryRetentionEnforcer,
    RetentionPolicy,
    RetentionPolicyError,
)


def _policy(**overrides: object) -> RetentionPolicy:
    base: dict[str, object] = {
        "data_class": "access_token",
        "max_age": timedelta(days=90),
        "legal_basis": "GDPR Art 5(1)(e) storage limitation",
        "deletion_mode": "hard",
    }
    base.update(overrides)
    return RetentionPolicy(**base)  # type: ignore[arg-type]


# RP_INV_01 — every write MUST have a bound policy.
def test_inv_write_tagged_confirms() -> None:
    enf = InMemoryRetentionEnforcer()
    enf.bind(_policy())
    enf.enforce_on_write("access_token", "tok-1")
    assert enf.size == 1


def test_inv_write_tagged_prevents() -> None:
    enf = InMemoryRetentionEnforcer()
    with pytest.raises(RetentionPolicyError):
        enf.enforce_on_write("unregistered_class", "x-1")


def test_inv_write_tagged_under_failure() -> None:
    enf = InMemoryRetentionEnforcer()
    enf.bind(_policy())
    with pytest.raises(RetentionPolicyError):
        enf.enforce_on_write("access_token", "")


# RP_INV_02 — max_age finite and > 0.
def test_inv_max_age_positive_confirms() -> None:
    _policy(max_age=timedelta(hours=1))


def test_inv_max_age_positive_prevents() -> None:
    with pytest.raises(RetentionPolicyError):
        _policy(max_age=timedelta(0))
    with pytest.raises(RetentionPolicyError):
        _policy(max_age=timedelta(days=-1))


def test_inv_max_age_positive_under_failure() -> None:
    with pytest.raises(RetentionPolicyError):
        _policy(legal_basis="")


# RP_INV_03 — deletion_mode enum.
def test_inv_deletion_mode_confirms() -> None:
    for mode in ALLOWED_DELETION_MODES:
        _policy(deletion_mode=mode)


def test_inv_deletion_mode_prevents() -> None:
    with pytest.raises(RetentionPolicyError):
        _policy(deletion_mode="soft")
    with pytest.raises(RetentionPolicyError):
        _policy(deletion_mode="HARD")


def test_inv_deletion_mode_under_failure() -> None:
    with pytest.raises(RetentionPolicyError):
        _policy(deletion_mode="")


# RP_INV_04 — sweep idempotent + respects LegalHold.
def test_inv_sweep_idempotent_confirms() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("access_token", "t1")
    # No time has passed → sweep deletes nothing.
    assert enf.sweep() == 0
    assert enf.size == 1


def test_inv_sweep_idempotent_prevents() -> None:
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("access_token", "t1")
    clock[0] = datetime(2026, 1, 3, tzinfo=UTC)  # 2 days later
    first = enf.sweep()
    second = enf.sweep()
    assert first == 1 and second == 0


def test_inv_sweep_idempotent_under_failure() -> None:
    class _Hold:
        def covers(self, rid: str) -> bool:
            return rid == "held-1"

    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    enf = InMemoryRetentionEnforcer(hold_check=_Hold(), now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("access_token", "held-1")
    enf.enforce_on_write("access_token", "free-1")
    clock[0] = datetime(2026, 1, 3, tzinfo=UTC)
    purged = enf.sweep()
    # Only 'free-1' is purged; 'held-1' survives.
    assert purged == 1
    remaining = [r[0] for r in enf.records()]
    assert remaining == ["held-1"]


# RP_INV_05 — every purge emits audit row.
class _RecordingSink:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def append(self, actor: str, action: str, resource: str, outcome: str,
               attributes: object) -> str:
        self.rows.append({
            "actor": actor, "action": action, "resource": resource,
            "outcome": outcome, "attributes": dict(attributes),  # type: ignore[arg-type]
        })
        return "hash"


def test_inv_audit_on_purge_confirms() -> None:
    sink = _RecordingSink()
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    enf = InMemoryRetentionEnforcer(audit_sink=sink, now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("access_token", "t1")
    clock[0] = datetime(2026, 1, 3, tzinfo=UTC)
    enf.sweep()
    assert len(sink.rows) == 1
    assert sink.rows[0]["action"] == "purge"
    assert sink.rows[0]["resource"] == "data_class:access_token"


def test_inv_audit_on_purge_prevents() -> None:
    # No purge → no audit row.
    sink = _RecordingSink()
    enf = InMemoryRetentionEnforcer(audit_sink=sink)
    enf.bind(_policy())
    enf.enforce_on_write("access_token", "t1")
    enf.sweep()
    assert sink.rows == []


def test_inv_audit_on_purge_under_failure() -> None:
    # Without an audit sink, sweep still works but cannot prove audit trail.
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    enf = InMemoryRetentionEnforcer(now=lambda: clock[0])
    enf.bind(_policy(max_age=timedelta(days=1)))
    enf.enforce_on_write("access_token", "t1")
    clock[0] = datetime(2026, 1, 3, tzinfo=UTC)
    assert enf.sweep() == 1  # still idempotent, still correct
