"""Behavioral end-to-end scenarios for OutputEncoder.

These scenarios compose the encoder with realistic rendering patterns (HTML
templates, JS event handlers, CSS style attributes, URL building) and prove
that each OE invariant holds across the integration.
"""

from __future__ import annotations

import pytest

from OutputEncoder import (
    DefaultOutputEncoder,
    OutputEncoderError,
    SingleEncodeGuard,
    Sink,
)


def _render_user_mention(user_name: str) -> str:
    e = DefaultOutputEncoder()
    safe = e.encode(user_name, Sink.HTML_TEXT)
    return f"<span class='mention'>@{safe}</span>"


def _render_attr_tooltip(tooltip: str) -> str:
    e = DefaultOutputEncoder()
    safe = e.encode(tooltip, Sink.HTML_ATTRIBUTE)
    return f'<button title="{safe}">hover</button>'


def _render_js_snippet(data: str) -> str:
    e = DefaultOutputEncoder()
    safe = e.encode(data, Sink.JS_STRING)
    return f"<script>var x = '{safe}';</script>"


def _render_link(path: str, q: str) -> str:
    e = DefaultOutputEncoder()
    sp = e.encode(path, Sink.URL_PATH)
    sq = e.encode(q, Sink.URL_QUERY)
    return f'<a href="/api/{sp}?q={sq}">go</a>'


def test_scenario_mention_defuses_script_tag() -> None:
    html = _render_user_mention("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_scenario_attribute_breakout_defeated() -> None:
    # Attacker tries `" onclick="alert(1)` to break out of the title attribute.
    html = _render_attr_tooltip('" onclick="alert(1)')
    assert 'onclick="alert' not in html
    assert "&quot;" in html


def test_scenario_js_literal_cannot_be_broken() -> None:
    html = _render_js_snippet("');alert('xss")
    # The single-quote terminator the attacker needed is gone.
    assert "');alert" not in html
    assert "\\x27" in html


def test_scenario_url_query_rejects_plus_as_space() -> None:
    html = _render_link("search/results", "hello world")
    assert "q=hello%20world" in html
    # Path slash preserved, space encoded as %20.
    assert "/api/search/results?" in html


def test_scenario_css_injection_rejected() -> None:
    e = DefaultOutputEncoder()
    with pytest.raises(OutputEncoderError):
        e.encode("expression(alert(1))", Sink.CSS_VALUE)


def test_scenario_double_encode_guard_blocks_reencode() -> None:
    g = SingleEncodeGuard()
    safe = g.encode("A&B", Sink.HTML_TEXT)
    assert safe.payload == "A&amp;B"
    with pytest.raises(OutputEncoderError):
        # A developer refactoring a template tries to encode twice; the guard
        # raises so the bug is loud rather than silent (`&amp;amp;B`).
        g.encode(safe, Sink.HTML_TEXT)  # type: ignore[arg-type]


def test_scenario_cross_sink_isolation() -> None:
    # The same payload produces wildly different safe output per sink.
    e = DefaultOutputEncoder()
    payload = "<a href='x'>"
    as_text = e.encode(payload, Sink.HTML_TEXT)
    as_attr = e.encode(payload, Sink.HTML_ATTRIBUTE)
    as_js = e.encode(payload, Sink.JS_STRING)
    as_query = e.encode(payload, Sink.URL_QUERY)
    assert as_text != as_attr != as_js != as_query
    # Every variant neutralizes `<`.
    for v in (as_text, as_attr, as_js, as_query):
        assert "<" not in v


def test_scenario_roundtrip_decode_url_path() -> None:
    from urllib.parse import unquote

    e = DefaultOutputEncoder()
    original = "hello world / é"
    encoded = e.encode(original, Sink.URL_PATH)
    assert unquote(encoded) == original
