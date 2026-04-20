"""Metamorphic + differential tests for CurrentPrincipal.

Algebraic properties:
- equality is reflexive, symmetric, transitive over identical inputs
- roles are insertion-order-independent (frozenset semantics)
- claims read-only view equals source mapping element-wise
- anonymous() is idempotent (every call returns an equal value)
- for_log() is pure (same input → same output)
"""

from __future__ import annotations

from CurrentPrincipal import anonymous, authenticated


def test_metamorphic_equality_reflexive() -> None:
    p = authenticated("a", roles=["x"])
    assert p == p


def test_metamorphic_equality_symmetric_transitive() -> None:
    p1 = authenticated("a", tenant_id="t", roles=["x", "y"], claims={"k": "v"})
    p2 = authenticated("a", tenant_id="t", roles=["y", "x"], claims={"k": "v"})
    p3 = authenticated("a", tenant_id="t", roles=["x", "y"], claims={"k": "v"})
    assert p1 == p2 and p2 == p1
    assert p1 == p2 and p2 == p3 and p1 == p3


def test_metamorphic_roles_order_independent() -> None:
    p1 = authenticated("a", roles=["admin", "billing", "reader"])
    p2 = authenticated("a", roles=["reader", "admin", "billing"])
    assert p1.roles == p2.roles
    assert p1 == p2


def test_metamorphic_anonymous_is_idempotent() -> None:
    a1 = anonymous()
    a2 = anonymous()
    assert a1 == a2
    assert hash(a1) == hash(a2)


def test_metamorphic_for_log_pure() -> None:
    p = authenticated("a", roles=["x"], claims={"k": "v", "token": "t"})
    log1 = p.for_log()
    log2 = p.for_log()
    assert log1 == log2


def test_differential_has_role_matches_roles_set_membership() -> None:
    p = authenticated("a", roles=["admin", "user"])
    for r in ("admin", "user", "missing", ""):
        assert p.has_role(r) == (r != "" and r in p.roles)


def test_metamorphic_has_any_all_consistency() -> None:
    p = authenticated("a", roles=["admin", "billing"])
    assert p.has_any_role(["admin"]) is True
    assert p.has_all_roles(["admin"]) is True
    assert p.has_any_role(["missing"]) is False
    assert p.has_all_roles(["admin", "missing"]) is False
    # Empty "any" is False; empty "all" is True (vacuous truth).
    assert p.has_any_role([]) is False
    assert p.has_all_roles([]) is True


def test_metamorphic_claims_view_matches_source() -> None:
    src: dict[str, str] = {"a": "1", "b": "2", "c": "3"}
    p = authenticated("x", claims=src)
    for k, v in src.items():
        assert p.claim(k) == v
    assert len(p.claims) == len(src)
