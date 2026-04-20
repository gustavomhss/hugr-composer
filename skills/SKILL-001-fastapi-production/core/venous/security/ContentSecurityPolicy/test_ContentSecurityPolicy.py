"""Unit tests for ContentSecurityPolicy — three per invariant."""

from __future__ import annotations

import pytest

from ContentSecurityPolicy import (
    HEADER_ENFORCE,
    HEADER_REPORT_ONLY,
    CspDirectiveError,
    CspNonceError,
    CspPolicy,
    CspRenderError,
    Directive,
    PolicyDecorator,
    PolicyMode,
    _DEFAULT_REGISTRY,
    _NonceRegistry,
    apply_decorator,
    generate_nonce,
    nonce_request,
    policy_from_directives,
)


@pytest.fixture(autouse=True)
def _reset_nonce_registry() -> None:
    """Each test starts with a clean nonce registry so uniqueness checks
    don't bleed between cases."""
    _DEFAULT_REGISTRY.reset()


# ---------------------------------------------------------------------------
# CSP_INV_01 — default-src required
# ---------------------------------------------------------------------------
def test_inv_default_src_required_confirms() -> None:
    p = CspPolicy.strict_default()
    name, value = p.render_header()
    assert name == HEADER_ENFORCE
    assert "default-src 'self'" in value


def test_inv_default_src_required_prevents() -> None:
    # Policy without default-src MUST NOT render.
    p = CspPolicy().with_directive(Directive("script-src", ("'self'",)))
    with pytest.raises(CspRenderError):
        p.render_header()


def test_inv_default_src_required_under_failure() -> None:
    # Invalid directive name raises at the builder, before we ever reach render.
    with pytest.raises(CspDirectiveError):
        CspPolicy().with_directive(Directive("BAD NAME!", ("'self'",)))


# ---------------------------------------------------------------------------
# CSP_INV_02 — unsafe-inline + nonce are mutually exclusive
# ---------------------------------------------------------------------------
def test_inv_unsafe_inline_nonce_conflict_confirms() -> None:
    # A strict policy + nonce renders cleanly.
    nonce = generate_nonce()
    p = CspPolicy.strict_default().with_nonce(nonce)
    _, value = p.render_header()
    assert f"'nonce-{nonce}'" in value
    assert "'unsafe-inline'" not in value


def test_inv_unsafe_inline_nonce_conflict_prevents() -> None:
    # with_nonce on a script-src that already has 'unsafe-inline' MUST refuse.
    p = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("'self'", "'unsafe-inline'")),
    )
    with pytest.raises(CspNonceError):
        p.with_nonce(generate_nonce())


def test_inv_unsafe_inline_nonce_conflict_under_failure() -> None:
    # Even if the nonce slipped in somehow, render_header MUST refuse a
    # policy that ends up with BOTH on the same directive.
    nonce = generate_nonce()
    p = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("'self'", "'unsafe-inline'", f"'nonce-{nonce}'")),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


# ---------------------------------------------------------------------------
# CSP_INV_03 — nonce entropy + uniqueness
# ---------------------------------------------------------------------------
def test_inv_nonce_entropy_unique_confirms() -> None:
    seen: set[str] = set()
    for _ in range(128):
        n = generate_nonce()
        assert n not in seen
        seen.add(n)
        assert len(n) >= 22  # ≥128 bits base64-url


def test_inv_nonce_entropy_unique_prevents() -> None:
    # Below-entropy request MUST refuse.
    with pytest.raises(CspNonceError):
        generate_nonce(n_bytes=8)  # 64 bits
    # Caller-supplied nonce with too little entropy MUST refuse at with_nonce.
    p = CspPolicy.strict_default()
    with pytest.raises(CspNonceError):
        p.with_nonce("short")
    # Caller-supplied nonce with forbidden characters MUST refuse.
    with pytest.raises(CspNonceError):
        p.with_nonce("a" * 22 + "' DROP; --")


def test_inv_nonce_entropy_unique_under_failure() -> None:
    # Reuse check — the registry refuses a second record of the same value.
    reg = _NonceRegistry()
    reg.record("abcdefghijklmnopqrstuvwx")  # 24 chars
    with pytest.raises(CspNonceError):
        reg.record("abcdefghijklmnopqrstuvwx")


# ---------------------------------------------------------------------------
# CSP_INV_04 — object-src 'none' by default
# ---------------------------------------------------------------------------
def test_inv_object_src_none_confirms() -> None:
    p = CspPolicy.strict_default()
    _, value = p.render_header()
    assert "object-src 'none'" in value


def test_inv_object_src_none_prevents() -> None:
    # Override without rationale MUST fail.
    p = CspPolicy.strict_default().with_directive(
        Directive("object-src", ("https://cdn.example.com",)),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


def test_inv_object_src_none_under_failure() -> None:
    # Missing object-src entirely MUST fail render.
    p = policy_from_directives([
        Directive("default-src", ("'self'",)),
        Directive("base-uri", ("'self'",)),
        Directive("frame-ancestors", ("'none'",)),
    ])
    with pytest.raises(CspRenderError):
        p.render_header()


# ---------------------------------------------------------------------------
# CSP_INV_05 — base-uri / frame-ancestors closed list
# ---------------------------------------------------------------------------
def test_inv_closed_list_no_wildcard_confirms() -> None:
    p = CspPolicy.strict_default()
    _, value = p.render_header()
    assert "base-uri 'self'" in value
    assert "frame-ancestors 'none'" in value


def test_inv_closed_list_no_wildcard_prevents() -> None:
    # Wildcard on frame-ancestors MUST fail render.
    p = CspPolicy.strict_default().with_directive(
        Directive("frame-ancestors", ("*",)),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


def test_inv_closed_list_no_wildcard_under_failure() -> None:
    # A scheme-only wildcard on base-uri MUST also fail.
    p = CspPolicy.strict_default().with_directive(
        Directive("base-uri", ("https:",)),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


# ---------------------------------------------------------------------------
# CSP_INV_06 — enforce vs report-only separation
# ---------------------------------------------------------------------------
def test_inv_enforce_vs_report_only_confirms() -> None:
    # Enforce policy renders under the enforce header name.
    p = CspPolicy.strict_default()
    assert p.render_header()[0] == HEADER_ENFORCE
    # Report-only mode renders under the report-only header name.
    from dataclasses import replace
    p_ro = replace(p, mode=PolicyMode.REPORT_ONLY)
    assert p_ro.render_header()[0] == HEADER_REPORT_ONLY


def test_inv_enforce_vs_report_only_prevents() -> None:
    # render_dual refuses overlap: a directive in BOTH enforce and report-only.
    from dataclasses import replace
    p = CspPolicy.strict_default()
    p = replace(p, report_only_directives=frozenset({"script-src"}))
    # script-src is in both the enforce order and the report_only set —
    # render_dual MUST refuse because a directive can't block and report.
    # Our implementation actually SPLITS them: report_only carries script-src,
    # enforce drops it. So no overlap occurs. We construct the overlap case
    # by explicitly rendering via the internal path: a policy with mode=ENFORCE
    # and report_only_directives present should refuse on render_header().
    with pytest.raises(CspRenderError):
        p.render_header()


def test_inv_enforce_vs_report_only_under_failure() -> None:
    # Unknown mode MUST refuse.
    from dataclasses import replace
    p = CspPolicy.strict_default()
    bad = replace(p, mode="not-a-mode", report_only_directives=frozenset())
    with pytest.raises(CspRenderError):
        bad.render_header()


# ---------------------------------------------------------------------------
# Extension contract — decorator refuses widening
# ---------------------------------------------------------------------------
def test_decorator_refuses_default_src_widening() -> None:
    base = CspPolicy.strict_default()
    deco = PolicyDecorator(
        name="widen-default",
        applies=(Directive("default-src", ("'self'", "https://evil.example")),),
    )
    with pytest.raises(CspDirectiveError):
        apply_decorator(base, deco)


def test_decorator_refuses_unsafe_inline_without_flag() -> None:
    base = CspPolicy.strict_default()
    deco = PolicyDecorator(
        name="add-inline",
        applies=(Directive("script-src", ("'self'", "'unsafe-inline'")),),
    )
    with pytest.raises(CspNonceError):
        apply_decorator(base, deco)


def test_decorator_allows_unsafe_inline_with_flag_and_rationale() -> None:
    base = CspPolicy.strict_default()
    deco = PolicyDecorator(
        name="add-inline",
        applies=(Directive("script-src", ("'self'", "'unsafe-inline'")),),
        adds_unsafe_inline=True,
        adds_unsafe_inline_rationale="legacy-admin-console, tracked in JIRA-1234",
    )
    out = apply_decorator(base, deco)
    # With the flag+rationale, render succeeds (no nonce on script-src now).
    _, value = out.render_header()
    assert "'unsafe-inline'" in value


# ---------------------------------------------------------------------------
# Nonce context manager
# ---------------------------------------------------------------------------
def test_nonce_request_binds_and_forgets() -> None:
    reg = _NonceRegistry()
    with nonce_request(registry=reg) as nonce:
        assert len(nonce) >= 22
        # Within the block, the nonce is recorded — a second record MUST fail.
        with pytest.raises(CspNonceError):
            reg.record(nonce)
    # After exit, the registry forgets it, so re-recording succeeds.
    reg.record(nonce)


def test_policy_from_directives_roundtrips() -> None:
    p = policy_from_directives([
        Directive("default-src", ("'self'",)),
        Directive("object-src", ("'none'",)),
        Directive("base-uri", ("'self'",)),
        Directive("frame-ancestors", ("'none'",)),
    ])
    _, value = p.render_header()
    assert "default-src 'self'" in value
