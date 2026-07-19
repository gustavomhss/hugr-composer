"""Unit tests for OutputEncoder — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import pytest
from OutputEncoder import (
    DefaultOutputEncoder,
    EncodedFragment,
    OutputEncoderError,
    SingleEncodeGuard,
    Sink,
)


def _enc() -> DefaultOutputEncoder:
    return DefaultOutputEncoder()


# ---------------------------------------------------------------------------
# OE_INV_01 — sink containment
# ---------------------------------------------------------------------------
def test_inv_sink_containment_confirms() -> None:
    e = _enc()
    # HTML_TEXT: `<script>` MUST be neutralized.
    out_text = e.encode("<script>alert(1)</script>", Sink.HTML_TEXT)
    assert "<" not in out_text
    assert "&lt;" in out_text
    # HTML_ATTRIBUTE: `"` breakout must be encoded.
    out_attr = e.encode('" onclick="alert(1)', Sink.HTML_ATTRIBUTE)
    assert '"' not in out_attr
    assert "&quot;" in out_attr
    # JS_STRING: cannot break out of a single-quoted JS literal.
    out_js = e.encode("');alert('xss", Sink.JS_STRING)
    assert "'" not in out_js


def test_inv_sink_containment_prevents() -> None:
    e = _enc()
    # Attempt to inject an HTML comment via attribute context — `<` and `>` escaped.
    payload = "--><script>alert(1)</script><!--"
    out = e.encode(payload, Sink.HTML_ATTRIBUTE)
    assert "<script" not in out.lower()
    assert "-->" not in out  # `>` got `&gt;`
    # Backtick attack on old IE breakouts.
    out2 = e.encode("`onmouseover=`alert(1)`", Sink.HTML_ATTRIBUTE)
    assert "`" not in out2


def test_inv_sink_containment_under_failure() -> None:
    e = _enc()
    # Even when the encoder is called with odd unicode, output MUST remain
    # contained (no `<` or unescaped quote survives).
    for bad in ("\u202e<img>", "<\u0000script>", "\u2028</script>"):
        out = e.encode(bad, Sink.HTML_TEXT)
        assert "<" not in out
        assert ">" not in out


# ---------------------------------------------------------------------------
# OE_INV_02 — explicit sink declaration
# ---------------------------------------------------------------------------
def test_inv_explicit_sink_confirms() -> None:
    e = _enc()
    # Every Sink member is a valid, accepted argument.
    for s in Sink:
        if s is Sink.CSS_VALUE:
            out = e.encode("abc", s)
        else:
            out = e.encode("abc", s)
        assert isinstance(out, str)


def test_inv_explicit_sink_prevents() -> None:
    e = _enc()
    # Passing a raw string ("html_text") instead of the Sink enum MUST fail.
    with pytest.raises(OutputEncoderError):
        e.encode("x", "html_text")  # type: ignore[arg-type]
    with pytest.raises(OutputEncoderError):
        e.encode("x", None)  # type: ignore[arg-type]
    with pytest.raises(OutputEncoderError):
        e.encode("x", 42)  # type: ignore[arg-type]


def test_inv_explicit_sink_under_failure() -> None:
    e = _enc()
    # An attacker-controlled "sink" (e.g. str value from a form field) MUST
    # be rejected even if it happens to equal a valid enum's value.
    class Faux:
        value = "html_text"

    with pytest.raises(OutputEncoderError):
        e.encode("x", Faux())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OE_INV_03 — no double encoding (EncodedFragment guard)
# ---------------------------------------------------------------------------
def test_inv_no_double_encode_confirms() -> None:
    g = SingleEncodeGuard()
    frag = g.encode("<b>hi</b>", Sink.HTML_TEXT)
    assert isinstance(frag, EncodedFragment)
    assert "&lt;b&gt;" in frag.payload
    assert frag.sink is Sink.HTML_TEXT


def test_inv_no_double_encode_prevents() -> None:
    g = SingleEncodeGuard()
    frag = g.encode("<b>", Sink.HTML_TEXT)
    with pytest.raises(OutputEncoderError):
        g.encode(frag, Sink.HTML_TEXT)  # type: ignore[arg-type]


def test_inv_no_double_encode_under_failure() -> None:
    g = SingleEncodeGuard()
    frag = g.encode("&", Sink.HTML_TEXT)
    # If the caller bypasses the guard by unwrapping .payload they get the
    # one-encode string. Re-encoding THAT would produce `&amp;amp;`, which we
    # demonstrate but refuse by construction of the guard.
    assert frag.payload == "&amp;"
    # A repr() MUST NOT leak the payload (defense-in-depth for OE_INV_03).
    assert "&amp;" not in repr(frag)


# ---------------------------------------------------------------------------
# OE_INV_04 — CSS hardening
# ---------------------------------------------------------------------------
def test_inv_css_hardening_confirms() -> None:
    e = _enc()
    out = e.encode("red", Sink.CSS_VALUE)
    # Alphanumerics pass through untouched.
    assert out == "red"
    # A space character gets hex-escaped (not alphanumeric).
    out2 = e.encode("a b", Sink.CSS_VALUE)
    assert "\\000020 " in out2


def test_inv_css_hardening_prevents() -> None:
    e = _enc()
    for payload in (
        "expression(alert(1))",
        "EXPRESSION(1)",
        "url(javascript:alert(1))",
        "@import url(evil.css)",
        "abc/*comment*/def",
        "javascript:alert(1)",
    ):
        with pytest.raises(OutputEncoderError):
            e.encode(payload, Sink.CSS_VALUE)


def test_inv_css_hardening_under_failure() -> None:
    e = _enc()
    # Control characters MUST be hex-escaped, not passed through.
    out = e.encode("a\x00b\x1fc", Sink.CSS_VALUE)
    assert "\x00" not in out
    assert "\x1f" not in out
    assert "\\000000 " in out
    assert "\\00001f " in out


# ---------------------------------------------------------------------------
# OE_INV_05 — URL RFC 3986
# ---------------------------------------------------------------------------
def test_inv_url_rfc3986_confirms() -> None:
    e = _enc()
    # Unreserved chars pass through.
    assert e.encode("ABCabc-._~", Sink.URL_QUERY) == "ABCabc-._~"
    # Space in query → %20, never `+`.
    assert e.encode("a b", Sink.URL_QUERY) == "a%20b"
    # Path preserves `/`.
    assert e.encode("foo/bar baz", Sink.URL_PATH) == "foo/bar%20baz"


def test_inv_url_rfc3986_prevents() -> None:
    e = _enc()
    # Reserved chars MUST be percent-encoded.
    out = e.encode("a&b=c?d#e", Sink.URL_QUERY)
    assert "&" not in out and "=" not in out and "?" not in out and "#" not in out
    # `+` MUST NEVER appear as a space substitute — space is %20.
    out2 = e.encode("hello world", Sink.URL_QUERY)
    assert "+" not in out2
    assert "%20" in out2


def test_inv_url_rfc3986_under_failure() -> None:
    e = _enc()
    # Non-ASCII → UTF-8 → percent-encoded bytes.
    out = e.encode("café", Sink.URL_QUERY)
    # 'é' is U+00E9 → 0xC3 0xA9 in UTF-8.
    assert "%C3%A9" in out
    # Query encoder MUST NOT leak a literal slash (query has no `/` privilege).
    out2 = e.encode("a/b", Sink.URL_QUERY)
    assert "/" not in out2
    assert "%2F" in out2
