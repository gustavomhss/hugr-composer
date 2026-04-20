"""Behavioral scenarios for CorsPolicy — end-to-end flows proving invariants."""

from __future__ import annotations

import pytest

from CorsPolicy import CorsPolicyError, build_policy


def test_scenario_preflight_allows_known_origin() -> None:
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        allowed_methods=["GET", "POST", "PUT", "OPTIONS"],
        allowed_headers=["Content-Type", "Authorization"],
        allow_credentials=True,
        max_age_seconds=3_600,
    )
    decision = policy.evaluate(
        origin="https://app.example.com",
        method="OPTIONS",
        requested_headers=("Content-Type", "Authorization"),
    )
    assert decision.allow_origin == "https://app.example.com"
    assert decision.allow_credentials is True
    assert "GET" in decision.allow_methods and "POST" in decision.allow_methods
    # Headers are filtered to intersection with allowlist.
    assert set(decision.allow_headers) <= {"content-type", "authorization", "Content-Type", "Authorization"}
    assert decision.max_age_seconds == 3_600


def test_scenario_preflight_denies_unknown_origin_silently() -> None:
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        allow_credentials=False,
        max_age_seconds=300,
    )
    decision = policy.evaluate(
        origin="https://attacker.example.com",
        method="OPTIONS",
        requested_headers=("Content-Type",),
    )
    # CP_INV_01: never echo unknown origin.
    assert decision.allow_origin is None
    assert decision.allow_methods == ()
    assert decision.allow_headers == ()


def test_scenario_credentialed_null_origin_raises() -> None:
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        allow_credentials=True,
        max_age_seconds=60,
    )
    with pytest.raises(CorsPolicyError):
        policy.evaluate("null", "GET", ())


def test_scenario_suffix_matcher_per_tenant_flow() -> None:
    policy = build_policy(
        suffix_tenants=[("https", ".tenants.example.com")],
        allowed_methods=["GET", "POST"],
        allowed_headers=["Content-Type"],
        allow_credentials=False,
        max_age_seconds=600,
    )
    good = policy.evaluate("https://acme.tenants.example.com", "GET", ("Content-Type",))
    assert good.allow_origin == "https://acme.tenants.example.com"
    bad = policy.evaluate("https://evil.tenants.example.com.attacker.com", "GET", ())
    assert bad.allow_origin is None


def test_scenario_requested_headers_never_reflected_verbatim() -> None:
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        allowed_headers=["Content-Type"],
        allow_credentials=False,
        max_age_seconds=60,
    )
    decision = policy.evaluate(
        origin="https://app.example.com",
        method="OPTIONS",
        requested_headers=("Content-Type", "X-Evil-Header", "Authorization"),
    )
    assert decision.allow_origin == "https://app.example.com"
    # Only Content-Type survives the filter — attacker headers are dropped.
    lowered = {h.lower() for h in decision.allow_headers}
    assert lowered == {"content-type"}


def test_scenario_max_age_ceiling_enforced_at_bind() -> None:
    with pytest.raises(CorsPolicyError):
        build_policy(
            exact_origins=["https://app.example.com"],
            max_age_seconds=90_000,  # > 86400 cap
        )


def test_scenario_wildcard_never_echoed() -> None:
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        allow_credentials=False,
        max_age_seconds=60,
    )
    decision = policy.evaluate("*", "GET", ())
    assert decision.allow_origin is None
