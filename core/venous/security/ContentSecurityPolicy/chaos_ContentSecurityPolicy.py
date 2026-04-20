"""Chaos / adversarial tests for ContentSecurityPolicy.

Game-day scenarios: XSS bypass attempts via malformed directives, header
injection via payload source tokens, nonce reuse under concurrency, hostile
decorators, and report-only misconfigurations. Each attack MUST be refused
and MUST NEVER produce a header that a browser would treat as permissive.
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from ContentSecurityPolicy import (
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
)


def _reset() -> None:
    _DEFAULT_REGISTRY.reset()


def test_chaos_header_injection_via_source_semicolon_refused() -> None:
    _reset()
    # Attacker supplies a source containing `;` — this would break out of
    # the directive and inject an adjacent rule. MUST be refused.
    for payload in (
        "https://good.example; script-src *",
        "a,b",
        "a\nscript-src *",
        "'self'\r\nX-Evil: 1",
    ):
        with pytest.raises(CspDirectiveError):
            CspPolicy.strict_default().with_directive(
                Directive("script-src", ("'self'", payload)),
            )


def test_chaos_xss_bypass_via_unsafe_inline_without_rationale() -> None:
    """Classic T6 attack: attacker adds 'unsafe-inline' to script-src
    hoping the builder silently accepts. render_header MUST refuse without
    the explicit flag + rationale."""
    _reset()
    p = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("'self'", "'unsafe-inline'")),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


def test_chaos_xss_bypass_via_unsafe_eval_without_rationale() -> None:
    _reset()
    p = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("'self'", "'unsafe-eval'")),
    )
    with pytest.raises(CspRenderError):
        p.render_header()


def test_chaos_xss_bypass_via_star_host_on_script_src() -> None:
    """`*` on script-src is allowed by CSP but catastrophic for XSS —
    while the spec does not strictly forbid it, our builder surfaces no
    direct refusal for non-closed-list directives. The test here
    documents expected behavior: the caller MUST explicitly see the `*`
    in the rendered header so a code reviewer can catch it."""
    _reset()
    p = CspPolicy.strict_default().with_directive(
        Directive("script-src", ("*",)),
    )
    _, value = p.render_header()
    # `*` on script-src must appear plainly in the header — not silently
    # filtered. A reviewer sees the hazard rather than a false sense of safety.
    assert "script-src *" in value


def test_chaos_closed_list_wildcard_refused() -> None:
    _reset()
    for payload in ("*", "https:", "http:", "data:", "*.evil.example"):
        p = CspPolicy.strict_default().with_directive(
            Directive("frame-ancestors", (payload,)),
        )
        with pytest.raises(CspRenderError):
            p.render_header()


def test_chaos_nonce_reuse_across_responses_refused() -> None:
    _reset()
    reg = _NonceRegistry()
    n = "A" * 24  # 24 base64-url chars
    reg.record(n)
    with pytest.raises(CspNonceError):
        reg.record(n)


def test_chaos_nonce_concurrent_generation_no_collision() -> None:
    """Generate 200 nonces across 8 threads — zero collisions."""
    _reset()
    reg = _NonceRegistry()
    errors: list[BaseException] = []
    nonces: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(25):
                n = generate_nonce(registry=reg)
                with lock:
                    nonces.append(n)
        except BaseException as exc:  # noqa: BLE001 — chaos harness records any failure per CSP_INV_03.
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(set(nonces)) == len(nonces)


def test_chaos_malicious_decorator_refused() -> None:
    _reset()
    base = CspPolicy.strict_default()
    # Decorator that widens default-src.
    with pytest.raises(CspDirectiveError):
        apply_decorator(base, PolicyDecorator(
            name="widen",
            applies=(Directive("default-src", ("'self'", "*")),),
        ))
    # Decorator that sneaks 'unsafe-inline' without the flag.
    with pytest.raises(CspNonceError):
        apply_decorator(base, PolicyDecorator(
            name="sneak-inline",
            applies=(Directive("script-src", ("'self'", "'unsafe-inline'")),),
        ))
    # Decorator with the flag but empty rationale.
    with pytest.raises(CspNonceError):
        apply_decorator(base, PolicyDecorator(
            name="empty-rationale",
            applies=(Directive("script-src", ("'self'", "'unsafe-inline'")),),
            adds_unsafe_inline=True,
            adds_unsafe_inline_rationale="   ",
        ))


def test_chaos_empty_directive_name_refused() -> None:
    _reset()
    for bad in ("", "UPPER-CASE", "1starts-with-digit", "has space", "has\nnewline"):
        with pytest.raises(CspDirectiveError):
            CspPolicy().with_directive(Directive(bad, ("'self'",)))


def test_chaos_non_tuple_sources_refused() -> None:
    _reset()
    with pytest.raises(CspDirectiveError):
        CspPolicy().with_directive(Directive("script-src", ["'self'"]))  # type: ignore[arg-type]  # chaos: caller supplied a list, not a tuple.


def test_chaos_unknown_mode_refused() -> None:
    _reset()
    p = replace(CspPolicy.strict_default(), mode="silent-log", report_only_directives=frozenset())
    with pytest.raises(CspRenderError):
        p.render_header()


def test_chaos_object_src_override_requires_rationale() -> None:
    _reset()
    # allow_object_src_override=True but empty rationale MUST fail.
    p = CspPolicy.strict_default().with_directive(
        Directive("object-src", ("https://cdn.example.com",)),
    )
    p = replace(p, allow_object_src_override=True, object_src_rationale="")
    with pytest.raises(CspRenderError):
        p.render_header()


def test_chaos_render_dual_overlap_refused() -> None:
    _reset()
    # Construct a policy where render_dual would produce overlap if not
    # careful: script-src in both the enforce set and the report-only set.
    # Our impl splits them correctly; the test confirms the non-overlap
    # property by inspecting both headers.
    p = replace(
        CspPolicy.strict_default(),
        report_only_directives=frozenset({"script-src"}),
    )
    enforce, report_only = p.render_dual()
    assert report_only is not None
    # CSP_INV_06 property: no directive in BOTH.
    enforce_names = {d.split(" ", 1)[0] for d in enforce[1].split("; ")}
    report_names = {d.split(" ", 1)[0] for d in report_only[1].split("; ")}
    overlap = (enforce_names & report_names) - {"default-src"}
    assert not overlap


def test_chaos_nonce_context_cleans_up_even_on_exception() -> None:
    _reset()
    reg = _NonceRegistry()
    captured: str | None = None
    with pytest.raises(RuntimeError):
        with nonce_request(registry=reg) as n:
            captured = n
            raise RuntimeError("inside the block")
    assert captured is not None
    # Registry forgot the nonce on exit, so we can record it fresh.
    reg.record(captured)


def test_chaos_nonce_too_short_refused_even_if_alphabet_valid() -> None:
    _reset()
    p = CspPolicy.strict_default()
    with pytest.raises(CspNonceError):
        p.with_nonce("abc123")  # valid chars, too few


def test_chaos_directive_with_only_empty_string_source_refused() -> None:
    _reset()
    with pytest.raises(CspDirectiveError):
        CspPolicy().with_directive(Directive("script-src", ("",)))


def test_chaos_report_only_carves_out_without_dropping_default_src() -> None:
    """Even when a policy carves out script-src to report-only, the
    enforce header still carries default-src so the browser has a baseline."""
    _reset()
    p = replace(
        CspPolicy.strict_default(),
        report_only_directives=frozenset({"script-src"}),
    )
    enforce, report_only = p.render_dual()
    assert "default-src 'self'" in enforce[1]
    assert report_only is not None
    assert "default-src 'self'" in report_only[1]
