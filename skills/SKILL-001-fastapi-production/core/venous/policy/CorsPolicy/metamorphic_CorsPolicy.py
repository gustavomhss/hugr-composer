"""Metamorphic + differential tests for CorsPolicy."""

from __future__ import annotations

from CorsPolicy import ClosedAllowlistCorsPolicy, build_policy


def _p() -> ClosedAllowlistCorsPolicy:
    return build_policy(
        exact_origins=["https://a.example.com", "https://b.example.com"],
        allowed_methods=["GET", "POST"],
        allowed_headers=["Content-Type"],
        allow_credentials=False,
        max_age_seconds=600,
    )


def test_metamorphic_evaluate_is_pure() -> None:
    # Calling evaluate() twice with the same inputs yields equal decisions.
    policy = _p()
    d1 = policy.evaluate("https://a.example.com", "GET", ("Content-Type",))
    d2 = policy.evaluate("https://a.example.com", "GET", ("Content-Type",))
    assert d1 == d2


def test_metamorphic_order_independent_across_origins() -> None:
    # Re-ordering origins in the allowlist doesn't change decisions.
    p1 = build_policy(
        exact_origins=["https://a.example.com", "https://b.example.com"],
        max_age_seconds=60,
    )
    p2 = build_policy(
        exact_origins=["https://b.example.com", "https://a.example.com"],
        max_age_seconds=60,
    )
    assert p1.evaluate("https://a.example.com", "GET", ()).allow_origin == \
        p2.evaluate("https://a.example.com", "GET", ()).allow_origin


def test_metamorphic_adding_origin_monotonic() -> None:
    # Adding an origin to the allowlist can only increase the accepted set,
    # never change decisions for previously accepted/denied origins.
    p_small = build_policy(exact_origins=["https://a.example.com"], max_age_seconds=60)
    p_large = build_policy(
        exact_origins=["https://a.example.com", "https://b.example.com"],
        max_age_seconds=60,
    )
    assert p_small.evaluate("https://a.example.com", "GET", ()).allow_origin == "https://a.example.com"
    assert p_large.evaluate("https://a.example.com", "GET", ()).allow_origin == "https://a.example.com"
    # Previously denied origin that remains unlisted stays denied.
    assert p_small.evaluate("https://c.example.com", "GET", ()).allow_origin is None
    assert p_large.evaluate("https://c.example.com", "GET", ()).allow_origin is None


def test_metamorphic_header_subset_monotonic() -> None:
    # Filtering requested headers against the allowlist is a set intersection,
    # so dropping a header from the request cannot add a header to the output.
    policy = build_policy(
        exact_origins=["https://a.example.com"],
        allowed_headers=["Content-Type", "Authorization"],
        max_age_seconds=60,
    )
    big = policy.evaluate(
        "https://a.example.com", "OPTIONS",
        ("Content-Type", "Authorization", "X-Other"),
    )
    small = policy.evaluate(
        "https://a.example.com", "OPTIONS",
        ("Content-Type",),
    )
    assert set(small.allow_headers) <= set(big.allow_headers)


def test_differential_unknown_origin_always_denied() -> None:
    # Unknown origin + any method + any requested headers -> always denied.
    policy = _p()
    for meth in ("GET", "POST", "OPTIONS", "DELETE"):
        for hdrs in ((), ("Content-Type",), ("X-Anything",)):
            d = policy.evaluate("https://unknown.example.com", meth, hdrs)
            assert d.allow_origin is None
            assert d.allow_methods == ()
            assert d.allow_headers == ()


def test_metamorphic_frozen_equality() -> None:
    # Frozen dataclass equality/hash is stable for equal configs.
    p1 = build_policy(exact_origins=["https://a.example.com"], max_age_seconds=60)
    p2 = build_policy(exact_origins=["https://a.example.com"], max_age_seconds=60)
    # Tuples of matchers have equal contents but independent identity; the
    # dataclass equality compares by field values.
    assert p1 == p2
    assert hash(p1) == hash(p2)
