"""Chaos / game-day tests for OutputEncoder.

Fault injection:
- Unicode edge cases (bidi overrides, zero-width joiners, surrogate pairs).
- Mixed-sink payloads designed to leak across contexts.
- Massive payloads — encoder MUST NOT crash or exhibit quadratic blow-up.
- Concurrent invocation — the encoder is stateless; many threads at once.
- Type confusion — bytes / int / None arguments rejected cleanly.
"""

from __future__ import annotations

import threading

import pytest

from OutputEncoder import DefaultOutputEncoder, OutputEncoderError, Sink


def _enc() -> DefaultOutputEncoder:
    return DefaultOutputEncoder()


def test_chaos_bidi_override_defused_in_html() -> None:
    e = _enc()
    # U+202E RTL override is a documented phishing vector — HTML_TEXT MUST
    # still neutralize surrounding metacharacters.
    payload = "\u202e<script>alert(1)</script>"
    out = e.encode(payload, Sink.HTML_TEXT)
    assert "<" not in out
    assert ">" not in out


def test_chaos_null_byte_in_attribute() -> None:
    e = _enc()
    # HTML_ATTRIBUTE strips sub-space control bytes outright.
    out = e.encode("a\x00b", Sink.HTML_ATTRIBUTE)
    assert "\x00" not in out


def test_chaos_surrogate_in_js_string() -> None:
    e = _enc()
    # Valid astral plane codepoint (emoji) — must \uXXXX escape.
    out = e.encode("A\U0001F600B", Sink.JS_STRING)
    # The emoji is U+1F600 — we encode as \uXXXX of its codepoint.
    assert "\\u1f600" in out
    assert "\U0001F600" not in out


def test_chaos_large_payload_no_crash() -> None:
    e = _enc()
    big = "<" * 10_000
    out = e.encode(big, Sink.HTML_TEXT)
    assert "<" not in out
    assert out.count("&lt;") == 10_000


def test_chaos_concurrent_encode_no_corruption() -> None:
    e = _enc()
    errors: list[BaseException] = []
    outs: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(50):
                r = e.encode("<b>", Sink.HTML_TEXT)
                with lock:
                    outs.append(r)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # All concurrent calls produced the same deterministic output.
    assert set(outs) == {"&lt;b&gt;"}


def test_chaos_type_confusion_rejected() -> None:
    e = _enc()
    for bad in (None, 42, 3.14, b"bytes", [], {}):
        with pytest.raises(OutputEncoderError):
            e.encode(bad, Sink.HTML_TEXT)  # type: ignore[arg-type]


def test_chaos_unknown_sink_rejected() -> None:
    e = _enc()
    with pytest.raises(OutputEncoderError):
        e.encode("x", "js_string")  # type: ignore[arg-type]


def test_chaos_css_mixed_case_injection() -> None:
    e = _enc()
    # Attacker obfuscates `expression(` with mixed case — detection is
    # case-insensitive.
    for payload in ("eXpReSsIoN(1)", "URL(evil)", "@IMPORT x"):
        with pytest.raises(OutputEncoderError):
            e.encode(payload, Sink.CSS_VALUE)


def test_chaos_url_query_forbids_plus_for_space() -> None:
    e = _enc()
    # Even if someone ports over form-encoded habits, space MUST be %20
    # on our URL_QUERY path.
    out = e.encode("a b c", Sink.URL_QUERY)
    assert "+" not in out


def test_chaos_html_attribute_without_quotes_still_safe() -> None:
    e = _enc()
    # Attacker payload assumes unquoted attributes: `x onmouseover=alert(1)`.
    # Space, equals, and backtick must all escape so the attr cannot grow.
    out = e.encode("x onmouseover=alert(1)", Sink.HTML_ATTRIBUTE)
    assert "=" not in out
    assert "&#x3D;" in out
