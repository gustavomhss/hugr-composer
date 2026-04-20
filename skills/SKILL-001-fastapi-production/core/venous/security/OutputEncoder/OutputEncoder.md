# OutputEncoder

## What it does (plain language)

OutputEncoder turns untrusted user values into safe strings for a *named*
sink. Each sink — HTML text, HTML attribute, JavaScript string, URL path,
URL query, CSS value — has its own escape rules. Pick the sink you are
emitting into and the encoder picks the rules. Miscategorising the sink is
the dominant root cause of XSS; this primitive makes the sink explicit at
every call site.

## Purpose

Encode untrusted values for a named sink using sink-specific escaping rules,
per OWASP ASVS V5.3 and the OWASP XSS Prevention Cheat Sheet.

## When to use and when NOT to use

- USE: anywhere a server-rendered template inlines a value into HTML, a JS
  literal, a URL, or a CSS property.
- USE: defense-in-depth alongside `ContentSecurityPolicy` — encoding is the
  primary control, CSP is the backup.
- DO NOT USE: structured data serialization (use `json.dumps` — the JSON
  library already produces a JS-safe string when `ensure_ascii=True`).
- DO NOT USE: SQL parameters (use parameterized queries, not string encoders).

## API surface

The catalog `api_signature` is authoritative; see `OutputEncoder.contract.json`.
Two classes ship:

- `DefaultOutputEncoder` — the stateless reference implementation. Safe to
  share across threads.
- `SingleEncodeGuard` — wraps an encoder and returns `EncodedFragment`
  values. Passing an `EncodedFragment` back through the guard raises
  `OutputEncoderError` so double-encoding is a loud bug, not a silent one.

## Invariants

| ID | Rule |
|---|---|
| OE_INV_01 | Encoded output MUST NEVER break out of its sink. |
| OE_INV_02 | The caller MUST declare the sink; encoder SHALL NEVER infer it. |
| OE_INV_03 | Encoders MUST be applied at emission; pre-encoded storage is FORBIDDEN. |
| OE_INV_04 | CSS_VALUE MUST reject expression()-style sequences and MUST hex-escape control characters. |
| OE_INV_05 | URL_QUERY MUST percent-encode per RFC 3986; space MUST become `%20` and `+` MUST NEVER substitute for space. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

`DefaultOutputEncoder` holds no mutable state; the dispatch table is a
module-level `Mapping` built once at import. Every call is a pure function
of `(value, sink)` — safe to call from any number of threads or tasks.

## Operational characteristics (for SRE)

- Encoding is O(n) in the input length with small constants; a 10 KB
  payload encodes in sub-millisecond time.
- Error rate spikes on `Sink.CSS_VALUE` are a security-interesting signal:
  the CSS encoder is the only sink that hard-rejects input
  (`expression(...)`, `url(...)`, `@import`).
- Schema logs include a `rejections{sink,reason_code}` counter for alerting.

## Security considerations

- Error messages cite the violated invariant id (`OE_INV_04`) but NEVER the
  raw payload — attacker strings do not reach logs through exceptions.
- `HTML_ATTRIBUTE` additionally escapes `/`, `` ` ``, and `=` so unquoted
  attribute breakouts (OWASP Rule 2) are defeated even when the template
  author forgot the surrounding quotes.
- `JS_STRING` escapes every character outside `[A-Za-z0-9,._]` as `\xHH` or
  `\uHHHH`; this intentionally over-escapes to handle quoting styles we do
  not know about.
- `URL_QUERY` never substitutes `+` for space. If you are building a form
  body, use a form-encoding routine, not this encoder.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V5.3 Output Encoding and Injection Prevention.
  - OWASP Top 10 2021 A03 Injection.
  - OWASP XSS Prevention Cheat Sheet (Rules 1–5).
  - RFC 3986 §2.3 URI Generic Syntax / Unreserved Characters.

## Alternatives considered and rejected

- Template autoescape only — misses JS_STRING and URL_QUERY sinks that are
  frequently nested inside HTML templates.
- Single generic escape function — encodes for HTML_TEXT regardless of
  sink; unsafe in attributes, useless in URLs, wrong in CSS.
- Sanitize-on-input — loses fidelity and re-introduces bugs whenever the
  emission context changes.

## Extension contract

Adding a new sink requires (1) extending the `Sink` enum, (2) registering
a pure `Callable[[str], str]` in the dispatch table, and (3) proving
containment against the sink's grammar with `test_inv_*_confirms`,
`_prevents`, and `_under_failure`. A plugin that cannot produce a
deterministic context-safe output for its sink CANNOT be bound.

## Usage

```python
from OutputEncoder import DefaultOutputEncoder, Sink

def render_user_mention(encoder: DefaultOutputEncoder, user_name: str) -> str:
    safe = encoder.encode(user_name, sink=Sink.HTML_TEXT)
    return f"<span class='mention'>@{safe}</span>"
```

## Compose with:

- **Sink-aware escaping** → `ContentSecurityPolicy` + `InputValidator`
  HTML, JS, URL, and CSS sinks each have their encoder; CSP enforces that untyped strings never reach the DOM.

- **PII-masked output** → `PiiClassification` + `AccessLog`
  Classification-driven mask runs before encoding; the access log records what was seen by whom — 'PII leaked because the encoder forgot' is prevented structurally.

- **Round-trip contract** → `InputValidator` + `ValueTransform`
  Inbound parse and outbound encode share canonical forms; the service's on-the-wire vocabulary is tight by construction.
