"""Unit tests for CorsPolicy — 3 per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest

from CorsPolicy import (
    ClosedAllowlistCorsPolicy,
    CorsPolicyError,
    ExactOriginMatcher,
    RegexOriginMatcher,
    SuffixTenantMatcher,
    build_policy,
)


def _p(**overrides: object) -> ClosedAllowlistCorsPolicy:
    """Policy factory for tests — credential-free by default."""
    kwargs: dict[str, object] = {
        "exact_origins": ["https://app.example.com"],
        "allowed_methods": ["GET", "POST", "OPTIONS"],
        "allowed_headers": ["Content-Type", "Authorization"],
        "allow_credentials": False,
        "max_age_seconds": 600,
    }
    kwargs.update(overrides)
    return build_policy(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CP_INV_01 — allowlist is closed, Origin never reflected unless matched.
# ---------------------------------------------------------------------------
def test_inv_allowlist_closed_confirms() -> None:
    policy = _p()
    decision = policy.evaluate("https://app.example.com", "GET", ())
    assert decision.allow_origin == "https://app.example.com"


def test_inv_allowlist_closed_prevents() -> None:
    policy = _p()
    for attacker in (
        "https://evil.example.com",
        "https://app.example.com.attacker.com",
        "http://app.example.com",  # scheme mismatch
        "*",
        "",
    ):
        decision = policy.evaluate(attacker, "GET", ())
        assert decision.allow_origin is None, attacker


def test_inv_allowlist_closed_under_failure() -> None:
    # Regex matcher MUST refuse open patterns even with a review ticket.
    for bad in (".*", ".+", "", "^.*$"):
        with pytest.raises(CorsPolicyError):
            RegexOriginMatcher(pattern=bad, review_ticket="SEC-123")
    # An empty matcher set is refused at policy construction.
    with pytest.raises(CorsPolicyError):
        ClosedAllowlistCorsPolicy(
            matchers=(),
            allowed_methods=frozenset({"GET"}),
            allowed_headers=frozenset({"Content-Type"}),
            allow_credentials=False,
            max_age_seconds=60,
        )


# ---------------------------------------------------------------------------
# CP_INV_02 — credentialed mode requires exact origin, rejects wildcard.
# ---------------------------------------------------------------------------
def test_inv_credentials_exact_confirms() -> None:
    policy = _p(allow_credentials=True)
    decision = policy.evaluate("https://app.example.com", "GET", ())
    assert decision.allow_origin == "https://app.example.com"
    assert decision.allow_credentials is True
    assert decision.allow_origin != "*"


def test_inv_credentials_exact_prevents() -> None:
    # Suffix-only credentialed policy MUST be refused at bind time.
    with pytest.raises(CorsPolicyError):
        build_policy(
            suffix_tenants=[("https", ".tenants.example.com")],
            allow_credentials=True,
            max_age_seconds=60,
        )
    # And the ExactOriginMatcher itself rejects '*'.
    with pytest.raises(CorsPolicyError):
        ExactOriginMatcher("*")


def test_inv_credentials_exact_under_failure() -> None:
    # Suffix matcher would match but credentialed mode still denies because
    # the matched origin is not in the exact-origin set.
    policy = build_policy(
        exact_origins=["https://app.example.com"],
        suffix_tenants=[("https", ".tenants.example.com")],
        allow_credentials=True,
        max_age_seconds=60,
    )
    decision = policy.evaluate("https://acme.tenants.example.com", "GET", ())
    assert decision.allow_origin is None


# ---------------------------------------------------------------------------
# CP_INV_03 — Vary: Origin MUST be pinned True.
# ---------------------------------------------------------------------------
def test_inv_vary_origin_confirms() -> None:
    policy = _p()
    assert policy.vary_origin is True


def test_inv_vary_origin_prevents() -> None:
    with pytest.raises(CorsPolicyError):
        ClosedAllowlistCorsPolicy(
            matchers=(ExactOriginMatcher("https://a.example.com"),),
            allowed_methods=frozenset({"GET"}),
            allowed_headers=frozenset({"Content-Type"}),
            allow_credentials=False,
            max_age_seconds=60,
            vary_origin=False,
        )


def test_inv_vary_origin_under_failure() -> None:
    # Even if runtime mutation attempts to unset vary_origin via
    # object.__setattr__, evaluate() defensively re-checks.
    policy = _p()
    object.__setattr__(policy, "vary_origin", False)
    with pytest.raises(CorsPolicyError):
        policy.evaluate("https://app.example.com", "GET", ())


# ---------------------------------------------------------------------------
# CP_INV_04 — max-age cap <= 86400, never unbounded.
# ---------------------------------------------------------------------------
def test_inv_max_age_cap_confirms() -> None:
    _p(max_age_seconds=0)
    _p(max_age_seconds=60)
    _p(max_age_seconds=86_400)


def test_inv_max_age_cap_prevents() -> None:
    with pytest.raises(CorsPolicyError):
        _p(max_age_seconds=86_401)
    with pytest.raises(CorsPolicyError):
        _p(max_age_seconds=10**9)
    with pytest.raises(CorsPolicyError):
        _p(max_age_seconds=-1)


def test_inv_max_age_cap_under_failure() -> None:
    # Boolean is a subclass of int — reject to avoid True coercing to 1 silently.
    with pytest.raises(CorsPolicyError):
        _p(max_age_seconds=True)


# ---------------------------------------------------------------------------
# CP_INV_05 — 'null' origin rejected in credentialed mode.
# ---------------------------------------------------------------------------
def test_inv_null_origin_confirms() -> None:
    # Non-credentialed mode returns a silent deny (no exception) — still
    # never echoes 'null'.
    policy = _p(allow_credentials=False)
    decision = policy.evaluate("null", "GET", ())
    assert decision.allow_origin is None


def test_inv_null_origin_prevents() -> None:
    policy = _p(allow_credentials=True)
    with pytest.raises(CorsPolicyError):
        policy.evaluate("null", "GET", ())


def test_inv_null_origin_under_failure() -> None:
    # 'null' MUST NOT be bindable as an exact allowlist entry either.
    with pytest.raises(CorsPolicyError):
        ExactOriginMatcher("null")


# ---------------------------------------------------------------------------
# Built-in matcher sanity (not an invariant test — kept separate).
# ---------------------------------------------------------------------------
def test_suffix_tenant_matcher_basic() -> None:
    m = SuffixTenantMatcher("https", ".tenants.example.com")
    assert m.matches("https://acme.tenants.example.com")
    assert not m.matches("https://attacker.com")
    assert not m.matches("https://evil.tenants.example.com.attacker.com")
    assert not m.matches("http://acme.tenants.example.com")  # scheme mismatch
