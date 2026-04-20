"""Tests for multi-tenant admin example."""
from __future__ import annotations

import dataclasses

import pytest

from app import (
    AuditRecord,
    Principal,
    TamperEvidentAuditLog,
    TenantStore,
    impersonate,
)


def test_cross_tenant_read_returns_none_not_raises() -> None:
    store = TenantStore()
    alice = Principal(user_id="alice", tenant_id="t-acme")
    bob = Principal(user_id="bob", tenant_id="t-beta")
    store.put(alice, "order-1", {"amount": 100})
    # Alice reads her own — works.
    assert store.get(alice, "order-1") == {"amount": 100}
    # Bob asks for the same row — must see None (maps to 404, not 403).
    assert store.get(bob, "order-1") is None


def test_impersonation_records_real_user_in_audit() -> None:
    log = TamperEvidentAuditLog()
    sa = Principal(user_id="root", tenant_id="t-platform", is_super_admin=True)
    imp = impersonate(sa, "t-acme", log)
    assert imp.effective_tenant == "t-acme"
    records = log.records()
    assert len(records) == 1
    assert records[0].action == "IMPERSONATE"
    assert records[0].actor == "root"           # real super-admin id
    assert records[0].tenant_id == "t-acme"     # impersonated tenant


def test_non_super_admin_cannot_impersonate() -> None:
    log = TamperEvidentAuditLog()
    alice = Principal(user_id="alice", tenant_id="t-acme")
    with pytest.raises(PermissionError):
        impersonate(alice, "t-beta", log)


def test_tenant_purge_leaves_zero_rows() -> None:
    store = TenantStore()
    alice = Principal(user_id="alice", tenant_id="t-acme")
    bob = Principal(user_id="bob", tenant_id="t-beta")
    store.put(alice, "a1", {"x": 1})
    store.put(alice, "a2", {"x": 2})
    store.put(bob, "b1", {"x": 3})
    purged = store.purge_tenant("t-acme")
    assert purged == 2
    # Acme rows gone; Beta untouched.
    assert store.get(alice, "a1") is None
    assert store.get(bob, "b1") == {"x": 3}


def test_audit_hash_chain_detects_tampering() -> None:
    log = TamperEvidentAuditLog()
    log.append(actor="alice", tenant_id="t-acme", action="WRITE",
               resource="order-1", before="{}", after='{"amount":100}')
    log.append(actor="alice", tenant_id="t-acme", action="WRITE",
               resource="order-1", before='{"amount":100}', after='{"amount":200}')
    assert log.verify() is True
    # Attacker flips amount in the second record — chain breaks.
    records = log.records()
    tampered = [records[0], dataclasses.replace(records[1], after='{"amount":0}')]
    assert log.verify(tampered) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
