"""Unit tests for AccessLog — 3 per invariant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from AccessLog import AccessLogError, InMemoryAccessLog


UTC = timezone.utc
T = datetime(2026, 1, 1, tzinfo=UTC)


# AL_INV_01 — every read emits a row.
def test_inv_read_records_confirms() -> None:
    log = InMemoryAccessLog()
    log.record_read("dr-1", "phi:patient:42", "phi", "treatment", T)
    assert log.size == 1


def test_inv_read_records_prevents() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "", "phi", "treatment", T)
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "r", "", "treatment", T)
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "r", "phi", "treatment", datetime(2026, 1, 1))


def test_inv_read_records_under_failure() -> None:
    log = InMemoryAccessLog()
    # Naive ts rejected even inside count_by_actor.
    with pytest.raises(AccessLogError):
        log.count_by_actor("dr-1", datetime(2026, 1, 1))


# AL_INV_02 — purpose_of_use enum.
def test_inv_purpose_enum_confirms() -> None:
    log = InMemoryAccessLog()
    for p in ("treatment", "payment", "operations", "audit"):
        log.record_read("dr-1", "r", "phi", p, T)


def test_inv_purpose_enum_prevents() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "r", "phi", "marketing", T)
    with pytest.raises(AccessLogError):
        log.record_read("dr-1", "r", "phi", "", T)


def test_inv_purpose_enum_under_failure() -> None:
    # Constructing with empty purposes raises.
    with pytest.raises(AccessLogError):
        InMemoryAccessLog(allowed_purposes=[])


# AL_INV_03 — AccessLog is a distinct class from TamperEvidentAuditLog.
def test_inv_distinct_from_audit_confirms() -> None:
    from AccessLog import AccessLog as AccessLogProto
    log = InMemoryAccessLog()
    # Ducktype: AccessLog does NOT implement the TEAL Protocol.
    assert not hasattr(log, "verify_chain")
    assert isinstance(log, AccessLogProto)


def test_inv_distinct_from_audit_prevents() -> None:
    log = InMemoryAccessLog()
    # No `append` method with TEAL signature.
    assert not hasattr(log, "append")


def test_inv_distinct_from_audit_under_failure() -> None:
    # Even a large burst of reads doesn't expose a hash-chain surface.
    log = InMemoryAccessLog()
    for i in range(100):
        log.record_read("dr-1", f"r:{i}", "phi", "treatment", T)
    assert not hasattr(log, "verify_chain")


# AL_INV_04 — actor MUST be concrete identity.
def test_inv_concrete_actor_confirms() -> None:
    log = InMemoryAccessLog()
    log.record_read("system:billing-job", "r", "phi", "payment", T)


def test_inv_concrete_actor_prevents() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("system", "r", "phi", "treatment", T)
    with pytest.raises(AccessLogError):
        log.record_read("", "r", "phi", "treatment", T)


def test_inv_concrete_actor_under_failure() -> None:
    log = InMemoryAccessLog()
    with pytest.raises(AccessLogError):
        log.record_read("   ", "r", "phi", "treatment", T)


# AL_INV_05 — retention bound at registration.
def test_inv_retention_bound_confirms() -> None:
    log = InMemoryAccessLog(retention=timedelta(days=30))
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    log.record_read("dr-1", "r", "phi", "treatment", t0)
    dropped = log.sweep_retention(now=datetime(2026, 3, 1, tzinfo=UTC))
    assert dropped == 1


def test_inv_retention_bound_prevents() -> None:
    with pytest.raises(AccessLogError):
        InMemoryAccessLog(retention=None)


def test_inv_retention_bound_under_failure() -> None:
    log = InMemoryAccessLog(retention=timedelta(days=30))
    log.record_read("dr-1", "r", "phi", "treatment", T)
    # Before retention lapse → nothing dropped.
    assert log.sweep_retention(now=T + timedelta(days=10)) == 0
