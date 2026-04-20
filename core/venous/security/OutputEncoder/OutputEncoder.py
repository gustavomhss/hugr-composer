"""OutputEncoder primitive — context-aware sink encoder for untrusted values.

Implements the catalog Protocol for `security.OutputEncoder`. Produces escaped
output for a *named* sink: HTML text, HTML attribute, JavaScript string, URL
path, URL query, or CSS value. Every sink has distinct rules; mis-encoding
across sinks is the dominant root cause of XSS (OWASP ASVS V5.3, A03:2021).

Import is side-effect-free; the module only uses the standard library.

Invariant IDs (enforced at runtime):

- OE_INV_01: encoded output MUST NEVER break out of its sink; a value encoded
  for HTML_ATTRIBUTE cannot introduce new attributes or execute script.
- OE_INV_02: the caller MUST declare the sink; the encoder SHALL NEVER infer
  context from the input's shape.
- OE_INV_03: callers MUST encode at emission; pre-encoded storage is
  FORBIDDEN (the Guard class enforces "one encode per value").
- OE_INV_04: CSS_VALUE encoding MUST reject expression()/url()/@import style
  sequences and MUST hex-escape control characters.
- OE_INV_05: URL_QUERY encoding MUST percent-encode per RFC 3986; space
  becomes %20 in paths; `+` is FORBIDDEN as a space replacement on this path.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Final, Protocol, runtime_checkable


class OutputEncoderError(ValueError):
    """Runtime invariant violation on an OutputEncoder operation.

    The error message cites the violated OE_INV_* id; it NEVER contains the
    raw untrusted value to avoid exfiltrating the attacker payload through
    structured logs.
    """


# ---------------------------------------------------------------------------
# Sink enum — catalog-mandated set of context codes
# ---------------------------------------------------------------------------
class Sink(str, Enum):
    """Declared emission context for an encoded value.

    OE_INV_02: the caller picks the sink; the encoder MUST NOT guess.
    """

    HTML_TEXT = "html_text"
    HTML_ATTRIBUTE = "html_attribute"
    JS_STRING = "js_string"
    URL_PATH = "url_path"
    URL_QUERY = "url_query"
    CSS_VALUE = "css_value"


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog byte-for-byte)
# ---------------------------------------------------------------------------
@runtime_checkable
class OutputEncoder(Protocol):
    def encode(self, value: str, sink: Sink) -> str: ...


# ---------------------------------------------------------------------------
# HTML text and attribute encoding — OWASP ASVS V5.3
# ---------------------------------------------------------------------------
# Five mandatory HTML entities per OWASP XSS prevention cheat sheet.
_HTML_TEXT_MAP: Final[Mapping[str, str]] = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#x27;",
}

# Attribute context additionally escapes `/`, backtick, and equals to defend
# against unquoted-attribute breakouts (OWASP Rule 2).
_HTML_ATTR_EXTRA: Final[Mapping[str, str]] = {
    "/": "&#x2F;",
    "`": "&#x60;",
    "=": "&#x3D;",
}


def _encode_html_text(value: str) -> str:
    # Replace `&` first so we do not double-encode `&lt;` → `&amp;lt;`.
    out = value.replace("&", "&amp;")
    for ch, ent in _HTML_TEXT_MAP.items():
        if ch == "&":
            continue
        out = out.replace(ch, ent)
    return out


def _encode_html_attribute(value: str) -> str:
    out = _encode_html_text(value)
    for ch, ent in _HTML_ATTR_EXTRA.items():
        out = out.replace(ch, ent)
    # Non-alphanumeric ASCII below 0x20 MUST be dropped / hex-escaped; the
    # HTML spec ignores most control bytes inside attribute values, but they
    # can trip up downstream parsers. Strip them outright.
    return "".join(c if (c >= " " or c in "\t\n\r") else "" for c in out)


# ---------------------------------------------------------------------------
# JavaScript string encoding — must survive inside a quoted JS literal
# ---------------------------------------------------------------------------
# Any ASCII < 0x20, plus `\`, `'`, `"`, `/`, `<`, `>`, `&`, ``` `, `=` are
# escaped as \xHH. This matches OWASP Rule 3 (JavaScript Escape Before Insert).
_JS_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9,\._]")


def _encode_js_string(value: str) -> str:
    out_parts: list[str] = []
    for ch in value:
        cp = ord(ch)
        if _JS_SAFE_RE.match(ch):
            out_parts.append(ch)
        elif cp < 0x100:
            out_parts.append(f"\\x{cp:02x}")
        else:
            out_parts.append(f"\\u{cp:04x}")
    return "".join(out_parts)


# ---------------------------------------------------------------------------
# URL path / query encoding — RFC 3986 unreserved set
# ---------------------------------------------------------------------------
# Unreserved per RFC 3986 §2.3: ALPHA / DIGIT / "-" / "." / "_" / "~".
_URL_UNRESERVED: Final[frozenset[str]] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789-._~"
)


def _percent_encode(value: str, *, allow_slash: bool) -> str:
    out_parts: list[str] = []
    for ch in value:
        if ch in _URL_UNRESERVED:
            out_parts.append(ch)
            continue
        if allow_slash and ch == "/":
            out_parts.append(ch)
            continue
        # Percent-encode every byte of the UTF-8 representation.
        for byte in ch.encode("utf-8"):
            out_parts.append(f"%{byte:02X}")
    return "".join(out_parts)


def _encode_url_path(value: str) -> str:
    # OE_INV_05: path segments keep `/` boundaries; space MUST be %20.
    return _percent_encode(value, allow_slash=True)


def _encode_url_query(value: str) -> str:
    # OE_INV_05: RFC 3986 query component; `+` substitution is FORBIDDEN on
    # this path — this encoder is for URL query components, not form bodies.
    return _percent_encode(value, allow_slash=False)


# ---------------------------------------------------------------------------
# CSS value encoding — OE_INV_04
# ---------------------------------------------------------------------------
# `expression(...)`, `url(...)`, `@import`, `/*...*/` are well-known CSS
# injection vectors; reject them outright rather than try to escape.
_CSS_FORBIDDEN_RE: Final[re.Pattern[str]] = re.compile(
    r"(expression\s*\(|url\s*\(|@import|/\*|\*/|</style|javascript\s*:|behaviour\s*:|behavior\s*:)",
    re.IGNORECASE,
)

# Characters that are always safe in a CSS identifier / value context.
_CSS_SAFE_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]")


def _encode_css_value(value: str) -> str:
    # OE_INV_04: blanket-reject known CSS injection sequences. An attacker
    # cannot smuggle `expression(...)` past us even with mixed case.
    if _CSS_FORBIDDEN_RE.search(value):
        raise OutputEncoderError(
            "OE_INV_04: CSS_VALUE rejects expression()/url()/@import sequences."
        )
    out_parts: list[str] = []
    for ch in value:
        cp = ord(ch)
        if _CSS_SAFE_RE.match(ch):
            out_parts.append(ch)
        else:
            # CSS spec §4.1.3: hex escape followed by a single space terminator.
            out_parts.append(f"\\{cp:06x} ")
    return "".join(out_parts)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------
_DISPATCH: Final[Mapping[Sink, Callable[[str], str]]] = {
    Sink.HTML_TEXT: _encode_html_text,
    Sink.HTML_ATTRIBUTE: _encode_html_attribute,
    Sink.JS_STRING: _encode_js_string,
    Sink.URL_PATH: _encode_url_path,
    Sink.URL_QUERY: _encode_url_query,
    Sink.CSS_VALUE: _encode_css_value,
}


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
class DefaultOutputEncoder:
    """Stateless, context-aware encoder.

    Satisfies every OE_INV_* at runtime. Instances are safe to share across
    threads; the class holds no mutable state.
    """

    def encode(self, value: str, sink: Sink) -> str:
        # OE_INV_02: reject any attempt to pass a non-Sink sink argument.
        if not isinstance(sink, Sink):
            raise OutputEncoderError(
                "OE_INV_02: sink MUST be a Sink enum member; caller cannot infer."
            )
        if not isinstance(value, str):
            raise OutputEncoderError(
                "OE_INV_01: value MUST be a str (value withheld from message)."
            )
        encoder = _DISPATCH.get(sink)
        if encoder is None:  # pragma: no cover — Sink membership already checked above.
            raise OutputEncoderError(f"OE_INV_02: unknown sink {sink!r}.")
        return encoder(value)


# ---------------------------------------------------------------------------
# One-encode guard — OE_INV_03
# ---------------------------------------------------------------------------
class EncodedFragment:
    """Opaque wrapper around a value that has been encoded exactly once.

    The guard lives at the boundary between application code and the sink:
    callers MUST NOT feed an EncodedFragment back through encode(). This is
    how we prevent double-encoding (`&lt;` → `&amp;lt;`) and how we prove
    OE_INV_03 at runtime in tests.
    """

    __slots__ = ("_payload", "_sink")

    _payload: str
    _sink: Sink

    def __init__(self, payload: str, sink: Sink) -> None:
        if not isinstance(payload, str):
            raise OutputEncoderError("OE_INV_03: EncodedFragment MUST wrap a str.")
        if not isinstance(sink, Sink):
            raise OutputEncoderError("OE_INV_03: EncodedFragment MUST declare a Sink.")
        self._payload = payload
        self._sink = sink

    @property
    def payload(self) -> str:
        return self._payload

    @property
    def sink(self) -> Sink:
        return self._sink

    def __repr__(self) -> str:
        # OE_INV_03: do NOT echo the payload — it would leak an attacker
        # string into logs and, via repr(), into exception traces.
        return f"EncodedFragment(sink={self._sink.value}, len={len(self._payload)})"


class SingleEncodeGuard:
    """Thin wrapper that rejects re-encoding of an EncodedFragment."""

    def __init__(self, encoder: OutputEncoder | None = None) -> None:
        self._encoder = encoder or DefaultOutputEncoder()

    def encode(self, value: str | EncodedFragment, sink: Sink) -> EncodedFragment:
        if isinstance(value, EncodedFragment):
            # OE_INV_03: pre-encoded storage is FORBIDDEN — refuse to re-encode.
            raise OutputEncoderError(
                "OE_INV_03: refusing to re-encode an EncodedFragment (double-encoding)."
            )
        encoded = self._encoder.encode(value, sink)
        return EncodedFragment(encoded, sink)


__all__ = [
    "DefaultOutputEncoder",
    "EncodedFragment",
    "OutputEncoder",
    "OutputEncoderError",
    "SingleEncodeGuard",
    "Sink",
]
