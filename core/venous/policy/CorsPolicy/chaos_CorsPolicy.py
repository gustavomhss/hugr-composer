"""Chaos / game-day tests for CorsPolicy — fault injection at the boundary."""

from __future__ import annotations

import pytest

from CorsPolicy import (
    CorsPolicyError,
    ExactOriginMatcher,
    RegexOriginMatcher,
    SuffixTenantMatcher,
    build_policy,
)


def test_chaos_malformed_origin_denied() -> None:
    policy = build_policy(
        exact_origins=["https://a.example.com"],
        max_age_seconds=60,
    )
    for weird in (
        "javascript:alert(1)",
        "data:text/html,<h1>x</h1>",
        "https://a.example.com/path?q=1",  # path/query not in Origin
        "https://a.example.com\nX-Injected: yes",
        "https://a.example.com ",  # trailing space
        "",
    ):
        d = policy.evaluate(weird, "GET", ())
        assert d.allow_origin is None, weird


def test_chaos_open_regex_refused() -> None:
    for bad in (".*", ".+", "", "^.*$", "^.+$"):
        with pytest.raises(CorsPolicyError):
            RegexOriginMatcher(pattern=bad, review_ticket="SEC-001")


def test_chaos_regex_matching_empty_refused() -> None:
    # A regex that happens to match the empty string (e.g. via `*` quantifier)
    # MUST be rejected — it's an open allowlist in disguise.
    for bad in ("a?", "(foo)?", "x*"):
        with pytest.raises(CorsPolicyError):
            RegexOriginMatcher(pattern=bad, review_ticket="SEC-002")


def test_chaos_wildcard_exact_matcher_refused() -> None:
    with pytest.raises(CorsPolicyError):
        ExactOriginMatcher("*")


def test_chaos_null_origin_bind_refused() -> None:
    with pytest.raises(CorsPolicyError):
        ExactOriginMatcher("null")


def test_chaos_suffix_matcher_host_confusion() -> None:
    m = SuffixTenantMatcher("https", ".tenants.example.com")
    # Attacker host that embeds the suffix as a prefix of their own domain.
    assert not m.matches("https://evil.tenants.example.com.attacker.com")
    # Nested subdomain is not permitted (matcher is one level deep).
    assert not m.matches("https://a.b.tenants.example.com")
    # Origin with path/query must not be treated as matching.
    assert not m.matches("https://acme.tenants.example.com/evil")


def test_chaos_credentialed_bind_without_exact_refused() -> None:
    with pytest.raises(CorsPolicyError):
        build_policy(
            suffix_tenants=[("https", ".tenants.example.com")],
            allow_credentials=True,
            max_age_seconds=60,
        )


def test_chaos_max_age_overflow_refused() -> None:
    for bad in (86_401, 10**9, -1, -86_400):
        with pytest.raises(CorsPolicyError):
            build_policy(
                exact_origins=["https://a.example.com"],
                max_age_seconds=bad,
            )


def test_chaos_method_injection_denied() -> None:
    policy = build_policy(
        exact_origins=["https://a.example.com"],
        allowed_methods=["GET", "POST"],
        max_age_seconds=60,
    )
    # DELETE is not in the allowlist — simple request denied.
    d = policy.evaluate("https://a.example.com", "DELETE", ())
    assert d.allow_origin is None


def test_chaos_header_case_injection_filtered() -> None:
    policy = build_policy(
        exact_origins=["https://a.example.com"],
        allowed_headers=["Content-Type"],
        max_age_seconds=60,
    )
    d = policy.evaluate(
        "https://a.example.com", "OPTIONS",
        ("X-Evil", "AUTHORIZATION", "content-type"),
    )
    # Only Content-Type (case-insensitive) survives.
    lowered = {h.lower() for h in d.allow_headers}
    assert "content-type" in lowered
    assert "x-evil" not in lowered
    assert "authorization" not in lowered
