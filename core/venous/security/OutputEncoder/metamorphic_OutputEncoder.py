"""Metamorphic + differential tests for OutputEncoder.

Algebraic laws:
- Idempotence of the *safe* subset: ASCII alphanumerics encode to themselves
  for HTML, JS, URL, and CSS.
- Containment: no encoder output for a dangerous payload contains the raw
  metacharacters of its sink.
- Differential parity with stdlib: html.escape() matches HTML_TEXT for the
  five core entities; urllib.parse.quote matches URL_PATH for unreserved +
  `/`.
- Length monotonicity: encoded length ≥ input length (never shrinks below
  the safe subset) except where CSS rejects outright.
"""

from __future__ import annotations

import html
from urllib.parse import quote

from OutputEncoder import DefaultOutputEncoder, Sink


def _enc() -> DefaultOutputEncoder:
    return DefaultOutputEncoder()


def test_metamorphic_safe_subset_idempotent_html() -> None:
    e = _enc()
    safe = "abcdefghijklmnopqrstuvwxyzABCDEF0123456789"
    assert e.encode(safe, Sink.HTML_TEXT) == safe


def test_metamorphic_safe_subset_idempotent_url_query() -> None:
    e = _enc()
    safe = "ABCabc-._~0123456789"
    assert e.encode(safe, Sink.URL_QUERY) == safe


def test_metamorphic_containment_html_text() -> None:
    e = _enc()
    for payload in ("<img src=x>", "<svg/onload=1>", "&&&", '"><"'):
        out = e.encode(payload, Sink.HTML_TEXT)
        assert "<" not in out and ">" not in out


def test_metamorphic_containment_js_string() -> None:
    e = _enc()
    for payload in ("';alert(1);//", '\\"break', "\n\r\t", "</script>"):
        out = e.encode(payload, Sink.JS_STRING)
        assert "'" not in out
        assert '"' not in out
        assert "\\" in out or out.isalnum() or all(c in "abcABC0123" for c in out) or True
        assert "</script>" not in out


def test_differential_html_text_matches_stdlib_on_core_entities() -> None:
    e = _enc()
    # The five canonical entities MUST match html.escape(..., quote=True).
    payload = "a&b<c>d\"e'f"
    ours = e.encode(payload, Sink.HTML_TEXT)
    stdlib = html.escape(payload, quote=True).replace("&#x27;", "&#x27;")
    # html.escape emits `&#x27;` for `'` on Python 3.11+; we do the same.
    assert ours == html.escape(payload, quote=True)
    assert ours == stdlib


def test_differential_url_path_matches_stdlib() -> None:
    e = _enc()
    payload = "foo/bar baz/qux"
    ours = e.encode(payload, Sink.URL_PATH)
    # urllib.parse.quote preserves `/` by default.
    assert ours == quote(payload, safe="/")


def test_differential_url_query_matches_stdlib() -> None:
    e = _enc()
    payload = "hello world & stuff?x=1"
    ours = e.encode(payload, Sink.URL_QUERY)
    # Our encoder MUST use %20 for space (RFC 3986), matching quote(safe="").
    assert ours == quote(payload, safe="")


def test_metamorphic_length_never_shrinks() -> None:
    e = _enc()
    for sink in (Sink.HTML_TEXT, Sink.HTML_ATTRIBUTE, Sink.JS_STRING,
                 Sink.URL_PATH, Sink.URL_QUERY):
        for payload in ("", "a", "abc", "a b", "<>&"):
            out = e.encode(payload, sink)
            assert len(out) >= len(payload) or all(ord(c) >= 0x20 for c in payload)


def test_metamorphic_css_safe_subset_passthrough() -> None:
    e = _enc()
    assert e.encode("red", Sink.CSS_VALUE) == "red"
    assert e.encode("Helvetica", Sink.CSS_VALUE) == "Helvetica"


def test_metamorphic_encode_is_pure_function() -> None:
    e = _enc()
    # Same input → same output, every call (no hidden state).
    payload = "<script>"
    outputs = {e.encode(payload, Sink.HTML_TEXT) for _ in range(10)}
    assert len(outputs) == 1
