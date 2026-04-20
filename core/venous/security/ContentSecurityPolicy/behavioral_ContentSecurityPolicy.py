"""Behavioral end-to-end scenarios for ContentSecurityPolicy.

Each scenario walks a realistic request/response flow — building a strict
default, attaching a per-response nonce, composing a per-route decorator,
switching to report-only for a staged rollout, and catching regressions —
proving the CSP invariants hold at runtime, not just at the unit level.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ContentSecurityPolicy import (
    HEADER_ENFORCE,
    HEADER_REPORT_ONLY,
    CspNonceError,
    CspPolicy,
    CspRenderError,
    Directive,
    PolicyDecorator,
    PolicyMode,
    _DEFAULT_REGISTRY,
    apply_decorator,
    generate_nonce,
    nonce_request,
)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    _DEFAULT_REGISTRY.reset()


def test_scenario_strict_default_renders_clean_enforce_header() -> None:
    """The shipping strict default must compose into a valid enforce header
    covering every OWASP ASVS V14.4-required directive."""
    name, value = CspPolicy.strict_default().render_header()
    assert name == HEADER_ENFORCE
    for required in (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ):
        assert required in value


def test_scenario_per_response_nonce_attaches_to_script_src() -> None:
    """A per-response nonce rides the script-src source list; a second
    response gets a distinct nonce value."""
    base = CspPolicy.strict_default()
    with nonce_request() as n1:
        _, v1 = base.with_nonce(n1).render_header()
    with nonce_request() as n2:
        _, v2 = base.with_nonce(n2).render_header()
    assert n1 != n2
    assert f"'nonce-{n1}'" in v1
    assert f"'nonce-{n2}'" in v2
    assert f"'nonce-{n1}'" not in v2


def test_scenario_decorator_narrows_img_src_for_one_route() -> None:
    """A per-route decorator that ADDS a CDN to img-src must compose cleanly
    on top of the base without widening default-src."""
    base = CspPolicy.strict_default()
    deco = PolicyDecorator(
        name="allow-cdn-on-avatars",
        applies=(Directive("img-src", ("'self'", "https://cdn.example.com")),),
    )
    out = apply_decorator(base, deco)
    _, value = out.render_header()
    assert "img-src 'self' https://cdn.example.com" in value
    # default-src still 'self' — NOT widened.
    assert "default-src 'self'" in value


def test_scenario_decorator_refuses_default_src_widening() -> None:
    """Extension contract: a decorator that tries to widen default-src is
    refused at compose time (no need to wait for render)."""
    base = CspPolicy.strict_default()
    rogue = PolicyDecorator(
        name="widen-default",
        applies=(Directive("default-src", ("'self'", "*")),),
    )
    with pytest.raises(Exception):  # noqa: BLE001 — scenario asserts *any* refusal per CSP_INV_01.
        apply_decorator(base, rogue)


def test_scenario_report_only_rollout_is_a_separate_header() -> None:
    """A staged-rollout policy is emitted under the report-only header; it
    MUST NOT stamp the enforce header, so browsers only report without
    breaking the page."""
    p = replace(CspPolicy.strict_default(), mode=PolicyMode.REPORT_ONLY)
    header_name, _ = p.render_header()
    assert header_name == HEADER_REPORT_ONLY


def test_scenario_render_dual_emits_both_headers_without_overlap() -> None:
    """Dual mode: script-src only in report-only (carve-out for a planned
    tightening), rest of the policy in enforce. No directive appears on both."""
    base = CspPolicy.strict_default()
    p = replace(base, report_only_directives=frozenset({"script-src"}))
    enforce, report_only = p.render_dual()
    assert enforce[0] == HEADER_ENFORCE
    assert report_only is not None
    assert report_only[0] == HEADER_REPORT_ONLY
    assert "script-src" not in enforce[1]
    assert "script-src" in report_only[1]


def test_scenario_xss_attempt_via_unsafe_inline_is_caught() -> None:
    """Adversarial: an attacker-crafted middleware tries to splice
    'unsafe-inline' onto script-src. The builder refuses the combination of
    that splice PLUS a per-response nonce, which would silently disable the
    nonce under CSP3."""
    base = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("'self'", "'unsafe-inline'")),
    )
    with pytest.raises(CspNonceError):
        with nonce_request() as n:
            base.with_nonce(n)


def test_scenario_enforce_mode_cannot_carry_report_only_directives() -> None:
    """An enforce-mode policy that accidentally lists report_only_directives
    MUST refuse to render — the caller has to either split via render_dual
    or clear the list. This catches the misconfiguration rather than letting
    it silently drop headers."""
    p = replace(
        CspPolicy.strict_default(),
        report_only_directives=frozenset({"script-src"}),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


def test_scenario_rotate_policy_across_requests_keeps_nonces_unique() -> None:
    """Simulate 50 requests; each gets its own nonce; no two headers match."""
    base = CspPolicy.strict_default()
    values: list[str] = []
    for _ in range(50):
        with nonce_request() as n:
            _, v = base.with_nonce(n).render_header()
            values.append(v)
    assert len(set(values)) == 50
