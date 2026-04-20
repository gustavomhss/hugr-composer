# ContentSecurityPolicy

## What it does (plain language)

ContentSecurityPolicy is the primitive every HTTP response flows through to
pick up a strict, reviewable `Content-Security-Policy` header. It turns the
usual "one giant string concatenated in a middleware" into typed
`Directive` objects that compose functionally. A per-response nonce can be
attached with one call; the render step catches classic XSS bypass
patterns — `'unsafe-inline'` sneaking onto `script-src`, wildcards on
`base-uri`, or a missing `default-src` — before the header ever reaches a
browser. Report-only and enforce modes are separate headers; a directive
cannot both block and merely report at the same time.

## Purpose

Compose, serialize, and enforce a Content Security Policy header that
constrains script, style, frame, and connection origins with strict-dynamic
and nonce-based script allowance.

## Alternatives considered and rejected

- **Static nginx header** — not nonce-aware; breaks strict-dynamic.
- **Framework meta-tag CSP** — ignored for navigation responses and
  reporting.
- **Per-endpoint hand-written header** — accumulates divergence and dead
  directives.

## When to use and when NOT to use

- USE: every HTTP response serving HTML or JSON rendered into a page.
- USE: any middleware that stamps a common security baseline plus per-route
  carve-outs.
- DO NOT USE: to carry session material — the header is public by design.
- DO NOT USE: as a validator for incoming requests — CSP is a *response*
  header. For request validation, pair with `InputValidator`.

## API surface

The catalog `api_signature` is authoritative; see
`ContentSecurityPolicy.contract.json`. The module ships:

- `ContentSecurityPolicy` — the `Protocol` with
  `with_directive`, `with_nonce`, `render_header`.
- `Directive` — frozen dataclass `(name, sources)`.
- `CspPolicy` — reference immutable implementation.
  - `strict_default()` — OWASP ASVS V14.4-compliant baseline.
  - `render_dual()` — emit the enforce + report-only headers.
- `generate_nonce`, `nonce_request` — CSPRNG-backed nonce with uniqueness
  tracking (CSP_INV_03).
- `PolicyDecorator`, `apply_decorator` — per-route override that refuses
  widenings of `default-src` and silent `'unsafe-inline'` injection.
- `policy_from_directives` — convenience builder.

## Key terms

- **Directive**: a single CSP rule — `script-src 'self'`.
- **Source list**: the set of origins / keywords allowed on a directive.
- **Nonce**: one-time random token tagged as `'nonce-<value>'` on
  script-src to authorize inline scripts without `'unsafe-inline'`.
- **Enforce vs report-only**: two separate headers. Enforce blocks
  violations; report-only merely logs them. A single directive MUST NOT
  appear on both (CSP_INV_06).
- **Closed-list directive**: `base-uri` and `frame-ancestors`. These MUST
  list origins explicitly; wildcards are forbidden in production
  (CSP_INV_05).

## Invariants

| ID | Rule |
|---|---|
| CSP_INV_01 | default-src MUST be set; a policy without default-src CANNOT be rendered. |
| CSP_INV_02 | script-src MUST NEVER include 'unsafe-inline' together with a nonce; the two are mutually exclusive per CSP3. |
| CSP_INV_03 | Nonces MUST be ≥128 bits from a CSPRNG and MUST be unique per response; reuse SHALL invalidate the guarantee. |
| CSP_INV_04 | object-src MUST be set to 'none' unless the caller explicitly opts in with a reason string. |
| CSP_INV_05 | base-uri and frame-ancestors MUST be set to a closed list; wildcard values are FORBIDDEN in production profiles. |
| CSP_INV_06 | report-only and enforce modes MUST be separate header names and MUST NEVER both block and merely report the same directive. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

`CspPolicy` is a frozen dataclass — immutable and safe to share across
threads without locks. The nonce registry uses a `threading.Lock` for
record / forget / reset paths. The default registry is process-global;
replace it with a request-scoped one in async frameworks to avoid
cross-request sharing.

## Operational characteristics (for SRE)

- `render_header` is O(directives + sources) and allocates a single string.
  p50 well under 10 µs on a modern host.
- Nonce generation is a single `secrets.token_urlsafe` plus a lock ack —
  a few microseconds.
- Failure modes:
  - Missing `default-src` → `CspRenderError` (CSP_INV_01).
  - `'unsafe-inline'` + nonce on script-src → `CspRenderError` (CSP_INV_02).
  - Below-entropy or reused nonce → `CspNonceError` (CSP_INV_03).
  - `object-src` override without rationale → `CspRenderError` (CSP_INV_04).
  - Wildcard on closed-list directive → `CspRenderError` (CSP_INV_05).
  - Directive overlap across enforce/report-only → `CspRenderError`
    (CSP_INV_06).
- Alert on `csp_policy_rejections_total > 0` — a rejection means a request
  reached the renderer with a broken policy; investigate immediately.
- Alert on `csp_nonces_reused_total > 0` — a reuse event indicates a bug
  in the per-request nonce wiring.

### Runbook

1. **Rejection spike by `invariant_id=CSP_INV_02`**: a middleware is
   splicing `'unsafe-inline'` without setting `allow_unsafe_inline_script`.
   Identify the route via the `route` label, audit the middleware, remove
   `'unsafe-inline'` or set the flag with a JIRA-linked rationale.
2. **Nonce reuse alert**: the per-request context forgot to call
   `nonce_request()` and is reusing a long-lived value. Redeploy with a
   fresh context per request.
3. **Report-only → enforce promotion**: move a directive from
   `report_only_directives` onto the main directive set. Confirm
   `csp_violations_reported_total` is 0 on that directive for at least 24 h
   before flipping.

## Security considerations

- `'unsafe-inline'` and `'unsafe-eval'` are refused by default on every
  nonceable directive. Overriding requires the explicit
  `allow_unsafe_inline_script=True` flag AND a non-empty rationale string
  that is preserved on the policy for review.
- Nonces are generated from `secrets.token_urlsafe` (CSPRNG) with ≥128
  bits of entropy. Reuse across responses is refused by the process-local
  registry; production callers should scope the registry to a request.
- Source tokens containing `;`, `,`, CR, or LF are refused at
  `with_directive` time — these are the header-injection payloads.
- `base-uri` and `frame-ancestors` MUST be closed-list. Wildcards of any
  kind (`*`, `*.evil`, `https:`, `data:`) are refused in production.
- `object-src` defaults to `'none'`. Overriding requires an explicit flag
  and rationale; this preserves the OWASP ASVS V14.4 baseline.
- Report-only and enforce are separate headers. A policy that lists a
  directive in both refuses to render (CSP_INV_06) so you cannot
  accidentally block and report the same class of violation.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3 V14.4 HTTP Security Headers Requirements.
  - OWASP Top 10 2021 A05:2021 Security Misconfiguration — response
    headers.

## Extension contract

Per-route policy overrides register as `PolicyDecorator` instances that
compose on top of a base policy via `apply_decorator`. A decorator is
refused if it:

- widens `default-src` (attempts to add sources the base does not already
  include), OR
- reintroduces `'unsafe-inline'` on `script-src` without setting
  `adds_unsafe_inline=True` AND providing a non-empty
  `adds_unsafe_inline_rationale`.

To add a new decorator, construct `PolicyDecorator(name, applies=(...))`
and pass it through `apply_decorator(base, decorator)`. The returned
policy is a new immutable `CspPolicy`.

## Usage

```python
from ContentSecurityPolicy import (
    CspPolicy, Directive, apply_decorator, nonce_request,
    PolicyDecorator,
)

base = CspPolicy.strict_default()

# Per-response:
with nonce_request() as nonce:
    policy = base.with_nonce(nonce)
    header_name, header_value = policy.render_header()
    response.headers[header_name] = header_value

# Per-route carve-out:
avatar_deco = PolicyDecorator(
    name="allow-avatar-cdn",
    applies=(Directive("img-src", ("'self'", "https://cdn.example.com")),),
)
avatar_policy = apply_decorator(base, avatar_deco)
```

## Compose with:

- **Defense-in-depth rendering** → `OutputEncoder` + `CorsPolicy`
  Encoder neutralizes inline injections; CSP blocks anything that slips through at the browser; CORS limits who can even reach the endpoint.

- **Report + enforce** → `AuditEvent` + `StructuredLogger`
  Report-only rollout logs violations; enforce mode blocks; the transition is a policy-version bump, not a code change.

- **Trusted types** → `OutputEncoder` + `InputValidator`
  CSP requires typed sinks; encoder and validator are the only ways to produce them — raw string → DOM is a compile-time error.
