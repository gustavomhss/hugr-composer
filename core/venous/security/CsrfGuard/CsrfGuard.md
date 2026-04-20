# CsrfGuard

## What it does (plain language)

CsrfGuard issues a short random token bound to the current session and verifies
that same token is presented on every state-changing request. An attacker who
tricks a browser into submitting a forged POST cannot produce a valid token
without access to the user's session, so the mutation is refused before any
handler runs.

## Purpose

Bind state-changing HTTP requests to the authenticated session through
per-session tokens validated against a matching header or form field.

## When to use and when NOT to use

- USE: POST, PUT, PATCH, DELETE handlers that mutate server state on behalf
  of an authenticated session.
- DO NOT USE: safe methods (GET, HEAD, OPTIONS) — they MUST NOT mutate state.
- DO NOT USE: bearer-token APIs with no cookie / session surface; those rely
  on `TokenIntrospector` instead.

## API surface

See `CsrfGuard.contract.json` for the verbatim Protocol. The module ships
`HmacCsrfGuard`, an HMAC-SHA256 reference implementation. Tokens take the
form `hex(nonce) + "." + hex(HMAC-SHA256(secret, session_id || nonce))`,
which is stateless across requests and revocable via secret rotation.

## Invariants

| ID | Rule |
|---|---|
| CSRF_INV_01 | Tokens MUST be bound to the session id and MUST NEVER be accepted for a different session. |
| CSRF_INV_02 | verify() MUST compare tokens in constant time and MUST raise on mismatch with no information about the expected value. |
| CSRF_INV_03 | Safe methods (GET, HEAD, OPTIONS) MUST NEVER mutate state; the guard SHALL only be enforced for unsafe methods. |
| CSRF_INV_04 | Cross-origin requests lacking both a valid token and a same-site cookie CANNOT be processed; no-token MUST fail closed. |
| CSRF_INV_05 | Tokens MUST be rotated on session rotation and on explicit logout; stale tokens SHALL be rejected. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`.

## Thread and async safety

`HmacCsrfGuard` is immutable after construction. Every `issue()` draws a fresh
nonce from `secrets.token_bytes`; concurrent issue and verify are safe.

## Operational characteristics (for SRE)

- `verify()` rejects on `CsrfGuardError`; surface as HTTP 403, never 500.
- Rotate the signing secret on incident response by constructing a new
  `HmacCsrfGuard` and swapping it atomically; this invalidates every prior
  token in one step.
- Metrics to alert on: a spike in `csrf_guard.rejections{reason="mac_mismatch"}`
  is the classic signature of a CSRF campaign.

## Security considerations

- Token comparison uses `hmac.compare_digest` — constant time.
- Error messages NEVER echo the expected MAC or the submitted MAC; they cite
  only the invariant id.
- The guard fails closed on malformed or missing tokens.
- The guard is paired with `SessionStore`: a rotated session id implicitly
  invalidates every token issued for the prior id without requiring an
  explicit revocation list.

## Provenance

- Source agent: Agent #5 SECURITY
- Primary sources: OWASP ASVS 4.0.3 V4.2; OWASP Top 10 2021 A01.

## Alternatives considered and rejected

- SameSite=Strict cookies only — blocks legitimate cross-site navigation and
  is bypassed by subdomain takeover.
- Origin header check only — insufficient when Origin is missing.
- Per-form hidden token with no session binding — accepts any valid token
  from any user.

## Extension contract

Delivery shapes (double-submit cookie, synchronizer token, custom-header-only
for SPAs) register as csrf-strategy adapters implementing the Protocol. The
registry refuses to bind a strategy that does not validate Origin/Referer for
cookie-only flows.

## Usage

```python
def mutate(guard: CsrfGuard, session_id: str, submitted_token: str, do_work):
    guard.verify(session_id=session_id, submitted_token=submitted_token)
    return do_work()
```

## Compose with:

- **Browser write safety** → `SessionStore` + `CorsPolicy`
  Session cookie + CSRF token together authorize state change; neither alone is sufficient — cross-origin forgery requires both to leak.

- **Pipeline-mounted** → `RouterPipeline` + `RequestGuard`
  The browser pipeline mounts CSRF uniformly; individual handlers never remember to call it — one seam, one audit.

- **Defense in depth** → `ContentSecurityPolicy` + `AuditEvent`
  CSP prevents token exfil; CSRF prevents forgery; every rejection audits the principal — three layers, one decision.
