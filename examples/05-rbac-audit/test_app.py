"""Tests for RBAC + tamper-evident audit + break-glass example."""
from __future__ import annotations

import dataclasses

import pytest

from app import (
    AuditRecord,
    BreakGlassRegistry,
    RequestGuard,
    TamperEvidentAuditLog,
)


def test_allow_and_deny_both_audited() -> None:
    log = TamperEvidentAuditLog()
    guard = RequestGuard(log)

    d, _ = guard.check(user="alice", user_roles={"admin"}, resource="billing", required_role="admin")
    assert d == "allow"
    d, _ = guard.check(user="bob", user_roles={"viewer"}, resource="billing", required_role="admin")
    assert d == "deny"

    decisions = [r.decision for r in log.records()]
    assert decisions == ["allow", "deny"]


def test_hash_chain_verifies_clean_log() -> None:
    log = TamperEvidentAuditLog()
    guard = RequestGuard(log)
    for i in range(5):
        guard.check(user=f"u{i}", user_roles={"viewer"}, resource="x", required_role="admin")
    assert log.verify() is True


def test_tampering_with_reason_breaks_chain() -> None:
    log = TamperEvidentAuditLog()
    guard = RequestGuard(log)
    guard.check(user="a", user_roles={"admin"}, resource="r", required_role="admin")
    guard.check(user="b", user_roles={"viewer"}, resource="r", required_role="admin")

    records = log.records()
    # Attacker flips a deny to an allow-looking reason.
    tampered = [
        dataclasses.replace(records[0], reason="SYSTEM-OVERRIDE"),
        records[1],
    ]
    assert log.verify(tampered) is False


def test_break_glass_expires_and_cannot_renew_with_same_reason() -> None:
    bg = BreakGlassRegistry()
    bg.grant("on-call-1", reason="incident-1234", now=0.0, ttl_s=900.0)
    assert bg.active_role("on-call-1", now=100.0) == "break_glass_admin"

    # Cannot renew with same reason before expiry.
    with pytest.raises(ValueError, match="cannot be renewed"):
        bg.grant("on-call-1", reason="incident-1234", now=200.0, ttl_s=900.0)

    # After expiry — role is gone.
    assert bg.active_role("on-call-1", now=901.0) is None

    # A new reason creates a fresh grant.
    new = bg.grant("on-call-1", reason="incident-9999", now=1000.0, ttl_s=900.0)
    assert new.reason == "incident-9999"


def test_break_glass_requires_reason() -> None:
    bg = BreakGlassRegistry()
    with pytest.raises(ValueError, match="reason"):
        bg.grant("on-call", reason="", now=0.0, ttl_s=900.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
