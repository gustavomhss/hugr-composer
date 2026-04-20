# TokenIntrospector

## What it does (plain language)

TokenIntrospector is the shared primitive that every resource server uses to
decide whether an incoming access token is valid for this API. It verifies
JWTs with a pinned algorithm policy per issuer, calls the authorization
server's RFC 7662 endpoint for opaque tokens, enforces audience and
expiration consistently, and caches results only for as long as the token
itself is valid — never longer.

## Purpose

Validate access tokens by signature, issuer, audience, expiry, and not-before
claims, with optional RFC 7662 introspection for opaque tokens.

## When to use and when NOT to use

- USE: every authenticated HTTP endpoint, background worker, or internal RPC
  that accepts a bearer token and needs the same claim checks applied in the
  same order.
- DO NOT USE: for issuing tokens — that belongs to the authorization server.
- DO NOT USE: for long-lived session state — pair with `SessionStore` when
  server-side revocation across sessions is required.

## API surface

The catalog `api_signature` in `TokenIntrospector.contract.json` is the
authority. Consumers call `introspect(token, required_audience)` and receive
a frozen `TokenClaims` dataclass (`subject`, `scopes`, `audience`, `issuer`,
`expires_at`). On any validation failure the method raises the typed
`InvalidTokenError` (subclass of `TokenIntrospectorInvariantError`). The
reference implementation `CachingTokenIntrospector` is wired with an
`IssuerConfig` per trusted issuer, a `JwksFetcher` adapter, and an optional
`IntrospectionEndpoint` adapter for RFC 7662 opaque tokens.

## Invariants

| ID | Rule |
|---|---|
| TI_INV_01 | JWT verification MUST reject the 'none' algorithm and MUST pin the accepted algorithm set per issuer. |
| TI_INV_02 | introspect() MUST reject tokens whose aud claim does not include required_audience and SHALL raise a typed error. |
| TI_INV_03 | Expired tokens (now >= exp) and not-yet-valid tokens (now < nbf) MUST be rejected with no claim surface returned. |
| TI_INV_04 | Signing keys MUST be fetched from the issuer's JWKS with bounded caching; stale keys beyond max-age CANNOT be trusted. |
| TI_INV_05 | Opaque tokens MUST be introspected against the authorization server per RFC 7662 and NEVER parsed locally. |
| TI_INV_06 | Introspection results MUST NEVER be cached past the token's exp or past the documented TTL, whichever is lower. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## State model (for principal engineers / reviewers)

The primitive is stateful: two internal caches track (a) JWKS per issuer
with a hard max-age, and (b) introspection results per opaque token bounded
by `min(exp, ttl)`. A revoked opaque token atomically purges its cache entry
— no stale claims can surface on the next call. The TLA+ specification
(`TokenIntrospector.tla`) machine-checks three safety properties that map to
TI_INV_06 and TI_INV_03:

- `CacheNeverPastExpOrTtl` — a cached entry's `cached_until` is never beyond
  the token's `exp`.
- `RevokedTokensHaveNoCache` — the cache and revocation set are mutually
  disjoint after every transition.
- `ExpiredCacheIsPurgedAtTick` — the clock advance step evicts any entry
  whose `cached_until` has elapsed.

## Thread and async safety

- The introspection and JWKS caches are guarded by an internal lock; cache
  lookup releases the lock before any adapter call so adapter code CANNOT
  deadlock on the introspector's own lock.
- `revoke(token)` invalidates the introspection-cache entry atomically with
  adding the token to the revocation set — no window exists where a
  revoked token's cached claims can leak to a caller.
- `introspect()` is safe to call from any thread; see
  `concurrent_TokenIntrospector.py` for the linearizability harness.

## Operational characteristics (for SRE)

- One JWKS fetch per issuer per `jwks_max_age_s` window under steady load.
- Opaque introspection is one remote call per token per
  `min(exp - now, ttl)` window.
- `jwks.fetch.duration` p99 is the leading indicator for authorization-
  server latency; `token.introspect.total{result="rejected"}` rising is the
  symptom of misconfigured audience or rotated keys.
- Self-observability: see `observability_schema.json` for the schema and
  `dashboard.json` for the recommended Grafana panels.

## Security considerations

- The 'none' algorithm is FORBIDDEN at BOTH the `IssuerConfig` construction
  site AND at every JWT verification — defence in depth against a misconfig
  that would otherwise silently accept unsigned tokens.
- Algorithm pinning per issuer prevents a downgrade attack where an
  adversary with access to an HMAC secret signs an `alg: HS256` token that
  impersonates an issuer whose real public key is RSA.
- Opaque tokens are NEVER parsed locally — they are always introspected
  remotely per RFC 7662. Any three-segment string that is not a valid JWT
  raises `InvalidTokenError`.
- The primitive stores SHA-256 hashes of tokens (not the raw bearer) when it
  has to persist an identifier for revocation, so memory dumps never leak
  tokens.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - RFC 6749 — OAuth 2.0 Authorization Framework, Section 7 (Accessing
    Protected Resources).
  - RFC 7662 — OAuth 2.0 Token Introspection, Sections 2.1 / 2.2.
  - OpenID Connect Core 1.0, Section 3.1.3.7 (ID Token Validation).

## Alternatives considered and rejected

- Trust the upstream gateway to verify — leaves services exposed if the
  gateway is bypassed or misconfigured.
- Parse JWTs inline with a library call per handler — produces inconsistent
  `alg` and `aud` policy across endpoints.
- Always introspect remotely (even for JWTs) — unacceptable latency for
  typical JWT deployments at scale.

## Extension contract

Token formats register as introspector adapters (JWT, opaque, DPoP-bound)
implementing the catalog Protocol. A JWKS fetcher plugin declares the
supported issuers and key-resolution strategy; the registry refuses adapters
that accept the 'none' alg or skip `aud` checking. RFC 7662 endpoints
implement `IntrospectionEndpoint` and MUST return the raw dictionary
response — parsing is centralised here to keep the policy singular.

## Usage

```python
from TokenIntrospector import (
    CachingTokenIntrospector, IssuerConfig, SigningKey,
    StaticJwksFetcher, StaticIntrospectionEndpoint,
)

fetcher = StaticJwksFetcher({
    "https://id.example.com": [SigningKey(kid="k1", algorithm="HS256", secret=b"...")]
})
ti = CachingTokenIntrospector(
    issuers={"https://id.example.com": IssuerConfig(
        issuer="https://id.example.com",
        allowed_algorithms=frozenset({"HS256"}),
    )},
    jwks_fetcher=fetcher,
    introspection_endpoint=StaticIntrospectionEndpoint(),
)
claims = ti.introspect(request.headers["Authorization"].removeprefix("Bearer "), "billing-api")
if "invoices:read" not in claims.scopes:
    raise PermissionError("missing scope")
```

## Compose with:

- **Verify-then-admit** → `SignatureVerifier` + `CurrentPrincipal`
  Signature verification precedes claim extraction; only after the full claim set is validated is a CurrentPrincipal published — no partial trust.

- **Rotating JWKS** → `SecretsVault` + `KeyRotationSchedule`
  Signing keys come from the vault on a rotation cadence; overlap windows let old tokens verify until expiry without a big-bang cutover.

- **Opaque-token fallback** → `RequestGuard` + `CircuitBreaker`
  RFC 7662 introspection sits behind a breaker so an IdP outage degrades to cached introspection rather than blanket denial.
