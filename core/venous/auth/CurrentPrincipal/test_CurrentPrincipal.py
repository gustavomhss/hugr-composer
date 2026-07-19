"""Unit tests for CurrentPrincipal — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import dataclasses

import pytest
from CurrentPrincipal import (
    REDACTED,
    CurrentPrincipal,
    PrincipalInvariantError,
    StaticPrincipalProvider,
    anonymous,
    authenticated,
)


# ---------------------------------------------------------------------------
# PRINCIPAL_INV_01 — immutability
# ---------------------------------------------------------------------------
def test_inv_immutable_confirms() -> None:
    p = authenticated("alice", tenant_id="acme", roles=["admin"], claims={"dept": "eng"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.subject_id = "mallory"  # type: ignore[misc]  # PRINCIPAL-INV-01: frozen dataclass rejects mutation.
    # claims Mapping is a read-only MappingProxy — mutation raises TypeError
    with pytest.raises(TypeError):
        p.claims["dept"] = "sales"  # type: ignore[index]  # PRINCIPAL-INV-01: MappingProxy is read-only.


def test_inv_immutable_prevents() -> None:
    p = authenticated("bob", roles=["reader"])
    # Cannot delete field either.
    with pytest.raises(dataclasses.FrozenInstanceError):
        del p.subject_id  # type: ignore[misc]  # PRINCIPAL-INV-01: deletion rejected.
    # Cannot add new attr — frozen dataclass's __setattr__ raises
    # FrozenInstanceError for any write attempt (which subsumes slots'
    # AttributeError at construction-time enforcement). Either exception
    # satisfies PRINCIPAL-INV-01.
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        p.extra = "x"  # type: ignore[attr-defined]  # PRINCIPAL-INV-01: mutation rejected.


def test_inv_immutable_under_failure() -> None:
    # Even when the source claims dict is mutated after construction, the
    # principal's view MUST remain unchanged.
    source: dict[str, str] = {"role": "viewer"}
    p = authenticated("carol", claims=source)
    source["role"] = "admin"
    source["new"] = "y"
    assert p.claims["role"] == "viewer"
    assert "new" not in p.claims


# ---------------------------------------------------------------------------
# PRINCIPAL_INV_02 — anonymity parity
# ---------------------------------------------------------------------------
def test_inv_anonymity_parity_confirms() -> None:
    anon = anonymous()
    assert anon.is_anonymous is True
    assert anon.subject_id == ""
    assert anon.roles == frozenset()
    authed = authenticated("dave", roles=["user"])
    assert authed.is_anonymous is False
    assert authed.subject_id == "dave"


def test_inv_anonymity_parity_prevents() -> None:
    # is_anonymous=True with a non-empty subject_id MUST raise.
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="eve",
            tenant_id=None,
            roles=frozenset(),
            claims={},
            is_anonymous=True,
        )
    # is_anonymous=False with empty subject_id MUST raise.
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="",
            tenant_id=None,
            roles=frozenset(),
            claims={},
            is_anonymous=False,
        )
    # Anonymous with roles MUST raise.
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="",
            tenant_id=None,
            roles=frozenset({"admin"}),
            claims={},
            is_anonymous=True,
        )


def test_inv_anonymity_parity_under_failure() -> None:
    anon = anonymous()
    # Scope checks consistently deny for anonymous, even for empty role probes.
    assert anon.has_role("admin") is False
    assert anon.has_any_role(["admin", "user"]) is False
    assert anon.has_all_roles([]) is False
    with pytest.raises(PermissionError):
        anon.require_role("admin")


# ---------------------------------------------------------------------------
# PRINCIPAL_INV_03 — roles frozen
# ---------------------------------------------------------------------------
def test_inv_roles_frozen_confirms() -> None:
    p = authenticated("frank", roles=["admin", "billing"])
    assert isinstance(p.roles, frozenset)
    assert p.roles == frozenset({"admin", "billing"})
    # frozenset has no add/remove — attribute missing.
    assert not hasattr(p.roles, "add")
    assert not hasattr(p.roles, "remove")


def test_inv_roles_frozen_prevents() -> None:
    # Plain set / list / tuple rejected by direct construction.
    for bad_roles in ({"admin"}, ["admin"], ("admin",)):
        with pytest.raises(PrincipalInvariantError):
            CurrentPrincipal(
                subject_id="grace",
                tenant_id=None,
                roles=bad_roles,  # type: ignore[arg-type]  # PRINCIPAL-INV-03: only frozenset accepted.
                claims={},
                is_anonymous=False,
            )
    # Empty / whitespace role string rejected.
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="grace",
            tenant_id=None,
            roles=frozenset({""}),
            claims={},
            is_anonymous=False,
        )
    with pytest.raises(PrincipalInvariantError):
        CurrentPrincipal(
            subject_id="grace",
            tenant_id=None,
            roles=frozenset({" admin "}),
            claims={},
            is_anonymous=False,
        )


def test_inv_roles_frozen_under_failure() -> None:
    p = authenticated("heidi", roles=["admin"])
    # Attempting to cast to a mutable set then mutate does NOT affect the principal.
    snapshot = set(p.roles)
    snapshot.add("superadmin")
    assert "superadmin" not in p.roles
    # has_role stays truthful.
    assert p.has_role("admin") is True
    assert p.has_role("superadmin") is False


# ---------------------------------------------------------------------------
# PRINCIPAL_INV_04 — subject_id stable / hygienic
# ---------------------------------------------------------------------------
def test_inv_subject_stable_confirms() -> None:
    # Same inputs produce equal principals (dataclass __eq__).
    p1 = authenticated("ivan", tenant_id="acme", roles=["user"], claims={"k": "v"})
    p2 = authenticated("ivan", tenant_id="acme", roles=["user"], claims={"k": "v"})
    assert p1 == p2
    assert hash(p1) == hash(p2)


def test_inv_subject_stable_prevents() -> None:
    # Whitespace-padded subject_id rejected.
    with pytest.raises(PrincipalInvariantError):
        authenticated(" judy ")
    # Whitespace-only rejected.
    with pytest.raises(PrincipalInvariantError):
        authenticated("   ")
    # Null byte rejected.
    with pytest.raises(PrincipalInvariantError):
        authenticated("judy\x00admin")
    # Newline injection rejected (log-forging vector).
    with pytest.raises(PrincipalInvariantError):
        authenticated("judy\nadmin=true")
    # Non-str rejected.
    with pytest.raises(PrincipalInvariantError):
        authenticated(123)  # type: ignore[arg-type]  # PRINCIPAL-INV-04: non-str rejected.


def test_inv_subject_stable_under_failure() -> None:
    # Tenant_id hygiene mirrors subject_id.
    with pytest.raises(PrincipalInvariantError):
        authenticated("kate", tenant_id=" acme")
    with pytest.raises(PrincipalInvariantError):
        authenticated("kate", tenant_id="")
    with pytest.raises(PrincipalInvariantError):
        authenticated("kate", tenant_id="acme\x00")


# ---------------------------------------------------------------------------
# PRINCIPAL_INV_05 — log redaction
# ---------------------------------------------------------------------------
def test_inv_log_redaction_confirms() -> None:
    p = authenticated(
        "leo",
        tenant_id="acme",
        roles=["admin"],
        claims={"email": "leo@example.com", "token": "sk-live-abcdef"},
    )
    log = p.for_log()
    assert log["subject_id"] == "leo"
    claims = log["claims"]
    assert isinstance(claims, dict)
    # EVERY claim value redacted by default (PRINCIPAL-INV-05).
    assert claims["email"] == REDACTED
    assert claims["token"] == REDACTED
    # Raw sensitive value MUST NOT appear in the serialised log.
    assert "sk-live-abcdef" not in repr(log)
    assert "leo@example.com" not in repr(log)


def test_inv_log_redaction_prevents() -> None:
    p = authenticated("mia", claims={"password": "hunter2", "api_key": "AKIA..."})
    # Default repr MUST NOT leak raw claim values.
    r = repr(p)
    assert "hunter2" not in r
    assert "AKIA" not in r
    # for_log output can be safely json-dumped without leaking secrets.
    import json

    payload = json.dumps(p.for_log(), sort_keys=True)
    assert "hunter2" not in payload
    assert "AKIA" not in payload


def test_inv_log_redaction_under_failure() -> None:
    # Even claims with sensitive-looking KEYS survive redaction.
    p = authenticated(
        "nate",
        claims={"Authorization": "Bearer x", "Cookie": "sid=y", "benign": "ok"},
    )
    log = p.for_log()
    claims = log["claims"]
    assert isinstance(claims, dict)
    for v in claims.values():
        assert v == REDACTED


# ---------------------------------------------------------------------------
# Provider protocol — read-only construction path
# ---------------------------------------------------------------------------
def test_provider_unknown_credential_returns_anonymous() -> None:
    provider = StaticPrincipalProvider({"tok-1": authenticated("olivia", roles=["user"])})
    assert provider.resolve(None).is_anonymous is True
    assert provider.resolve("").is_anonymous is True
    assert provider.resolve("nope").is_anonymous is True
    assert provider.resolve("tok-1").subject_id == "olivia"
