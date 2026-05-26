# AGENT 5 — SECURITY

> Research cohort: HuGR Arsenal venous-system research phase
> Namespaces owned: `security`, `auth`, `policy`
> Primitives delivered: 15 (floor: 12)
> Unique sources: 9 (floor: 6)

## Mission recap

Extract the non-negotiable security surface every Arsenal target must
expose: authentication protocols, cryptographic facades, secrets handling,
input/output hygiene, session management, MFA, passkeys. Sources root
primarily in OWASP ASVS 4.0.3, OWASP Top 10 2021, the IETF OAuth stack
(RFC 6749 / 7636 / 7662 / 6238), OpenID Connect Core 1.0, W3C WebAuthn
Level 3, and NIST SP 800-63B.

Compliance-specific primitives (audit trail tamper-evidence, data
retention, DSAR workflows) are explicitly deferred to Agent 6.

## Scope summary

| Covered here | Owned elsewhere |
|---|---|
| OAuth 2.0 / OIDC / PKCE flows | Audit tamper-evidence → Agent 6 |
| WebAuthn registration & assertion | DSAR & retention workflows → Agent 6 |
| TOTP / OTP verifier | IdP product integrations (Auth0, Okta) → out of scope entirely |
| Password hashing, KDF | |
| Session store (rotation, fixation resistance, revocation) | |
| CSRF, CORS, CSP | |
| Input validation & sink-named output encoding | |
| Secrets vault (fetch, rotate, audit) | |
| AEAD crypto envelope + signature verifier | |
| Rate limiting as an authentication control | |

## Primitives

### Identity & session layer (`auth`)

| Primitive | Purpose |
|---|---|
| `AuthorizationCodeFlow` | OAuth 2.0 auth-code grant with PKCE, state/nonce, single-use code exchange. |
| `TokenIntrospector` | Signature, issuer, audience, expiry checks; RFC 7662 for opaque tokens. |
| `WebAuthnAuthenticator` | Passkey registration & assertion with RP-ID binding, challenge uniqueness, sign-count monotonicity. |
| `TotpVerifier` | RFC 6238 TOTP with replay-step persistence and constant-time compare. |
| `SessionStore` | Server-side sessions with fixation-resistant rotation, dual idle/absolute timeout, subject-wide revocation. |

### Crypto & secrets (`security`)

| Primitive | Purpose |
|---|---|
| `PasswordHasher` | Memory-hard KDF verifier with self-describing encoding and `needs_rehash` rotation. |
| `CryptoEnvelope` | AEAD (AES-GCM / ChaCha20-Poly1305) with key-id tagging for rotation without re-encrypt. |
| `SignatureVerifier` | Algorithm-pinned sign/verify with algorithm-confusion refusal and constant-time tag compare. |
| `SecretsVault` | Named-secret fetch/rotate/invalidate with bounded cache, audit events, fail-closed on cold misses. |

### Hygiene & HTTP edge (`security` / `policy`)

| Primitive | Purpose |
|---|---|
| `CsrfGuard` | Per-session CSRF token bound to session id; enforced only for unsafe methods. |
| `ContentSecurityPolicy` | Composable CSP with nonce-plus-strict-dynamic contract and closed-list base/frame-ancestors. |
| `CorsPolicy` | Closed-origin allowlist, credentialed-mode wildcard refusal, bounded preflight cache. |
| `OutputEncoder` | Sink-named encoder (HTML text, attribute, JS string, URL path/query, CSS) applied at last-moment. |
| `InputValidator` | Schema-first ingress with length/range/depth bounds and unknown-field rejection. |
| `RateLimiter` | Principal+route-keyed sliding-window quota, atomic decrement, stricter profile on auth endpoints. |

## Cross-cutting observations

1. **Constant-time comparison is universal.** Every credential-facing
   primitive (hasher, TOTP verifier, CSRF guard, signature verifier)
   MUST compare with constant-time primitives. Leaving timing discipline
   to caller code is the dominant implementation failure mode across
   ASVS V2, V6, and RFC 6238.
2. **Rotation is first-class.** `PasswordHasher.needs_rehash`,
   `SessionStore.rotate`, `SecretsVault.rotate`, and key-id-tagged
   envelopes all exist because the catalog cannot treat "rotate later"
   as a deferred feature. RFC 6749 and ASVS V6 both make key rotation
   a pre-condition, not an enhancement.
3. **Defense-in-depth at the HTTP edge is three policies, not one.**
   CSP, CORS, and cookie attributes each own disjoint failure modes.
   The classic "wildcard origin with credentials plus unsafe-inline
   script-src" regression only happens when one primitive subsumes
   another.
4. **OAuth/OIDC is only safe in combination.** Pulling PKCE out of
   RFC 6749 reintroduces authorization-code interception; dropping
   RFC 7662 for opaque tokens leaves introspection undefined; omitting
   OIDC 3.1.3.7 ID-token validation leaves nonce and aud unchecked.
5. **Input validation and output encoding are orthogonal.** Validators
   constrain payload shape; encoders constrain sink-specific escape.
   Teams conflating them end up storing encoded data or rendering raw
   data — both broken.
6. **Rate limiting is an authentication control.** NIST SP 800-63B
   §5.2.2 and ASVS V2.2 scope throttling as anti-automation on
   authenticator endpoints. Parking it in `resiliency` loses the
   principal-keyed requirement.
7. **WebAuthn failure modes are narrow and catastrophic.** Wrong
   origin, missing RP-ID hash check, challenge reuse, or unmonotonic
   sign counter each silently break the security model. A shared
   `WebAuthnAuthenticator` encodes the ceremony once.
8. **Session fixation and CSRF share plumbing.** The fact that session
   rotation invalidates CSRF tokens is a load-bearing assumption across
   ASVS V3 and V4.2 — it must be explicit in the primitive split.

## Gaps relative to SKILL-001 today

- No rotation-aware `PasswordHasher` primitive; credential-touching
  tools call bcrypt inline and drift apart.
- No WebAuthn / passkey registration primitive; current auth additions
  assume shared-secret factors.
- `CryptoEnvelope` with key-id tagging is not surfaced; field-level
  encryption generators roll their own AES without rotation support.
- `SecretsVault` with rotation and audit hooks is absent; generators
  rely on env vars injected at deploy time.
- No composable CSP primitive; tools emitting HTML ship without a
  nonce-aware strict-dynamic policy.
- `RateLimiter` lives in `resiliency` today and lacks the principal-
  keyed, auth-endpoint-stricter profile NIST SP 800-63B §5.2.2 requires.
- `TokenIntrospector` abstraction is absent — JWT verification is
  reimplemented per tool with inconsistent audience enforcement.
- `SessionStore` lacks `revoke_all_for_subject` semantics; password-
  change flows do not guarantee termination of live sessions.

## Source coverage

| Source | Primitives citing |
|---|---|
| OWASP ASVS 4.0.3 | 12 |
| OWASP Top 10 2021 | 8 |
| NIST SP 800-63B | 4 |
| RFC 6749 | 2 |
| OpenID Connect Core 1.0 | 2 |
| RFC 7636 | 1 |
| RFC 7662 | 1 |
| W3C WebAuthn Level 3 Recommendation | 1 |
| RFC 6238 | 1 |

No single source exceeds the 70% dominance floor; ASVS is the most-cited
corpus at 12/32 citations (≈37%), which matches its role as the unifying
verification catalog. IETF RFCs, OIDC Core, WebAuthn, and NIST SP 800-63B
each carry distinct primitives that ASVS references but does not specify.

## Self-check

```
skills/SKILL-001-fastapi-production/.venv/bin/python \
    docs/research/contracts/check_deliverable.py \
    --agent 5 --deliverable docs/research/outputs/AGENT_5_SECURITY.json
```

Result: `DELIVERABLE VALID` — 15 primitives, 9 unique sources, 8
insights, 8 gaps, exit code 0.
