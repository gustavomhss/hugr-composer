"""Behavioral end-to-end scenarios for CurrentPrincipal — proves invariants at runtime."""

from __future__ import annotations

import json

import pytest

from CurrentPrincipal import (
    REDACTED,
    CurrentPrincipal,
    PrincipalInvariantError,
    StaticPrincipalProvider,
    anonymous,
    authenticated,
)


def test_scenario_request_with_anonymous_default() -> None:
    # A request without credentials resolves to the explicit Anonymous default.
    provider = StaticPrincipalProvider()
    principal = provider.resolve(None)
    assert principal.is_anonymous is True
    # Scope checks deny everything.
    assert principal.has_role("admin") is False
    with pytest.raises(PermissionError):
        principal.require_role("admin")


def test_scenario_authenticated_request_with_roles_and_tenant() -> None:
    alice = authenticated(
        "alice",
        tenant_id="acme",
        roles=["admin", "billing"],
        claims={"email": "alice@example.com"},
    )
    provider = StaticPrincipalProvider({"tok-alice": alice})
    p = provider.resolve("tok-alice")
    assert p.subject_id == "alice"
    assert p.tenant_id == "acme"
    assert p.has_role("admin")
    assert p.has_any_role(["billing", "unknown"])
    assert p.has_all_roles(["admin", "billing"])
    assert not p.has_all_roles(["admin", "missing"])


def test_scenario_middleware_cannot_mutate_principal() -> None:
    # Simulate a malicious middleware that receives the principal and tries to
    # escalate by swapping subject_id. The frozen dataclass rejects it.
    p = authenticated("carol", roles=["user"])
    with pytest.raises(Exception):
        p.subject_id = "root"  # type: ignore[misc]  # PRINCIPAL-INV-01: frozen rejects write.
    with pytest.raises(TypeError):
        p.claims["injected"] = "yes"  # type: ignore[index]  # PRINCIPAL-INV-01.


def test_scenario_call_site_cannot_add_role() -> None:
    # A consumer tries to grant themselves a role at call time.
    p = authenticated("dave", roles=["reader"])
    # frozenset has no .add; this raises AttributeError at call site.
    with pytest.raises(AttributeError):
        p.roles.add("admin")  # type: ignore[attr-defined]  # PRINCIPAL-INV-03.
    assert p.has_role("admin") is False


def test_scenario_log_line_never_leaks_secrets() -> None:
    # Typical downstream logging pattern: json.dumps(p.for_log()).
    p = authenticated(
        "eve",
        roles=["admin"],
        claims={
            "password": "s3cret!",
            "api_key": "AKIA-REAL-KEY",
            "email": "eve@example.com",
        },
    )
    line = json.dumps(p.for_log(), sort_keys=True)
    assert "s3cret" not in line
    assert "AKIA-REAL-KEY" not in line
    assert "eve@example.com" not in line
    # The KEYS survive for auditability.
    assert "password" in line
    assert "api_key" in line


def test_scenario_require_role_short_circuits_on_anonymous() -> None:
    anon = anonymous()
    with pytest.raises(PermissionError):
        anon.require_role("anything")


def test_scenario_equality_and_hashing_enable_caching() -> None:
    # Two principals with identical inputs are equal and share a hash, enabling
    # safe use as dict keys or set members for request-scoped caches.
    p1 = authenticated("frank", tenant_id="t1", roles=["user"], claims={"k": "v"})
    p2 = authenticated("frank", tenant_id="t1", roles=["user"], claims={"k": "v"})
    bucket: dict[CurrentPrincipal, int] = {p1: 1}
    assert bucket[p2] == 1


def test_scenario_reject_injected_subject_id_from_malicious_header() -> None:
    # A malicious provider returning a subject_id with CR/LF cannot poison logs.
    with pytest.raises(PrincipalInvariantError):
        authenticated("admin\nis_admin=true")
    with pytest.raises(PrincipalInvariantError):
        authenticated("user\x00root")


def test_scenario_anonymous_has_empty_claims_in_log() -> None:
    anon = anonymous()
    log = anon.for_log()
    assert log["subject_id"] == ""
    assert log["is_anonymous"] is True
    assert log["roles"] == []
    assert log["claims"] == {}


def test_scenario_claim_lookup_returns_raw_value_for_deliberate_reads() -> None:
    # for_log redacts; but explicit .claim(key) reads the real value for
    # deliberate downstream use (e.g., audit writers that have their own redaction).
    p = authenticated("gina", claims={"locale": "en-US"})
    assert p.claim("locale") == "en-US"
    assert p.claim("missing", "default") == "default"
    # Non-str key returns default.
    assert p.claim(123, "x") == "x"  # type: ignore[arg-type]  # PRINCIPAL-INV-05 guard: non-str returns default.
    # Redacted form still shows only the marker.
    assert p.for_log()["claims"]["locale"] == REDACTED  # type: ignore[index]  # Mapping value access.
