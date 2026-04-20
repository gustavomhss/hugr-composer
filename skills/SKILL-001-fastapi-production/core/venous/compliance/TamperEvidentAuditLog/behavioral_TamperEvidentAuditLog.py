"""End-to-end behavioral scenarios that PROVE invariants at runtime."""

from __future__ import annotations

import pytest

from TamperEvidentAuditLog import (
    HmacReferenceSigner,
    InMemoryTamperEvidentAuditLog,
    TamperEvidentAuditLogError,
)


def _log() -> InMemoryTamperEvidentAuditLog:
    return InMemoryTamperEvidentAuditLog(HmacReferenceSigner(b"seed-bytes-32bytes-min-length!", "kid-1"))


def test_scenario_admin_password_reset_flow() -> None:
    log = _log()
    h = log.append(
        actor="admin-42",
        action="user.password_reset",
        resource="user:1138",
        outcome="success",
        attributes={"via": "admin_console", "ip": "10.0.0.1"},
    )
    assert h
    assert log.verify_chain() is True


def test_scenario_denied_access_chain() -> None:
    log = _log()
    log.append("u-1", "READ", "phi:patient:42", "denied", {"reason": "role"})
    log.append("u-1", "READ", "phi:patient:42", "denied", {"reason": "role"})
    log.append("admin", "GRANT", "role:clinician", "success", {})
    log.append("u-1", "READ", "phi:patient:42", "success", {})
    assert log.verify_chain() is True
    assert log.size == 4


def test_scenario_partial_verification() -> None:
    log = _log()
    for i in range(10):
        log.append("svc", "READ", f"obj:{i}", "success", {})
    # Partial: just the middle of the chain.
    assert log.verify_chain(start_seq=3, end_seq=7) is True


def test_scenario_export_ndjson_roundtrip() -> None:
    log = _log()
    log.append("a", "EXPORT", "user:1", "success", {"reason": "dsar"})
    log.append("a", "EXPORT", "user:2", "success", {"reason": "dsar"})
    blob = log.export(since_seq=1)
    assert blob.count(b"\n") == 2
    # Second export since_seq=2 yields only the second row.
    blob2 = log.export(since_seq=2)
    assert blob2.count(b"\n") == 1


def test_scenario_signature_detects_forgery() -> None:
    log = _log()
    log.append("a", "READ", "r", "success", {})
    # Forge: replace signature with bogus value.
    from dataclasses import replace
    log._entries[0] = replace(log._entries[0], signature="0" * 64)
    assert log.verify_chain() is False


def test_scenario_empty_actor_rejected() -> None:
    log = _log()
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("", "READ", "r", "success", {})


def test_scenario_invalid_outcome_rejected() -> None:
    log = _log()
    with pytest.raises(TamperEvidentAuditLogError):
        log.append("a", "READ", "r", "partial", {})
