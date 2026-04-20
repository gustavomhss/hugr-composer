# AuthorizationCodeFlow

## What it does (plain language)

AuthorizationCodeFlow runs the OAuth 2.1 / OpenID Connect authorization-code
grant with PKCE S256. Call `begin(scopes)` to get a URL the user's browser
visits; stash the returned `AuthorizationRequest` in your session. When the
user comes back with `code` and `state`, call `exchange(code, state, stored)`
to trade the code for tokens. The flow pins state, nonce, PKCE verifier, and
redirect URI end-to-end; codes are single-use and replays raise
`invalid_grant`; tokens never appear in audit traces as plaintext.

## Purpose

Execute the OAuth 2.0 authorization-code grant with PKCE, enforcing state,
nonce, redirect URI pinning, and one-time code exchange against the token
endpoint.

## When to use and when NOT to use

- USE: federated login via an external identity provider (Google, Auth0,
  Keycloak, corporate OIDC) for a confidential or public client.
- USE: any "Sign in with X" UX that returns to a server-rendered callback.
- DO NOT USE: the implicit flow or resource-owner password credentials
  grant — both are forbidden by OAuth 2.1.
- DO NOT USE: machine-to-machine token acquisition — use the client
  credentials grant instead (not covered by this primitive).

## API surface

The catalog `api_signature` in `AuthorizationCodeFlow.contract.json` is the
authority. Callers:

1. Build the flow with `create_flow(client_id, redirect_uri, provider,
   token_endpoint, audit_sink=..., code_ttl_seconds=...)`. The token endpoint
   is injected as a callable `Mapping[str,str] -> Mapping[str,object]` so the
   primitive performs zero network I/O (and is unit-testable without httpx).
2. Call `flow.begin(scopes=[...])` to get an `AuthorizationRequest` — stash
   it in the user's session verbatim.
3. When the browser returns, call `flow.exchange(code, state, stored)` to
   redeem the code for tokens. On success you receive the raw token
   response; every audit-trace emission uses the redacted view instead.

## Invariants

| ID | Rule |
|---|---|
| ACF_INV_01 | `begin()` MUST draw state, nonce, and PKCE `code_verifier` from a CSPRNG with ≥128 bits of entropy; no value is ever reused within a flow instance. |
| ACF_INV_02 | `exchange()` MUST reject any callback whose `state` does not byte-equal the stored state and SHALL abort before touching the token endpoint. |
| ACF_INV_03 | The `code_verifier` MUST be bound to the authorization request; substitution at exchange time is FORBIDDEN (PKCE S256 only). |
| ACF_INV_04 | Redirect URI sent on exchange MUST exactly match the registered URI; wildcard / suffix matches are FORBIDDEN. |
| ACF_INV_05 | Authorization codes MUST be single-use; replay SHALL produce `invalid_grant`. Expiry (TTL) is enforced locally and the state is burned on success. |
| ACF_INV_06 | Tokens MUST NEVER appear in full inside logs; only a 16-char SHA-256 hex prefix MAY appear in audit traces. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Thread and async safety

- `ReferenceAuthorizationCodeFlow` serialises state-issue and code-redemption
  under an internal lock. Concurrent `begin()` / `exchange()` calls preserve
  the uniqueness of issued values and the at-most-one-winner property for
  single-use codes.
- The token endpoint callable is invoked OUTSIDE the lock so application
  code called from inside the endpoint cannot deadlock on the flow's lock.
- A flow instance is scoped to one OAuth client registration; multi-client
  deployments MUST instantiate one flow per client (one `client_id`, one
  `redirect_uri`, one provider).

## Operational characteristics (for SRE)

- Self-observability: `acf.begin.count` (counter, `client_id` label),
  `acf.exchange.count` (counter, `result` label), `acf.exchange.duration`
  (histogram, `ms`, `result` label).
- A sustained rise in `acf.exchange.count{result="invalid_state"}` is the
  primary indicator of a CSRF-style attack or a broken session store.
- A sustained rise in `acf.exchange.count{result="invalid_grant"}` points
  at a replay attempt, an expired-code race, or a provider misconfiguration.
- Every audit event ships only `*_hash` fields for tokens / codes; never
  the plaintext.

## Security considerations

- `state` / `nonce` use 32 bytes of `secrets.token_bytes` → 192 bits of
  entropy via base64url. The catalog floor is 128 bits.
- Redirect URIs are compared byte-exact via `hmac.compare_digest`; this
  blocks both timing oracles and the classic suffix-wildcard bypass.
- Tokens are redacted at the `redact_token_response` boundary; the audit
  sink NEVER receives a plaintext token. Callers who log the raw response
  themselves must apply the same redactor.
- Code expiry is tracked via an injectable `clock` so deployments can
  enforce TTL independent of wall-clock skew; the default TTL is 10 minutes
  (per RFC 6749 §4.1.2 recommendation).

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - RFC 6749 §4.1 — Authorization Code Grant.
  - RFC 7636 §4.1–4.6 — PKCE code_verifier / code_challenge / S256.
  - OpenID Connect Core 1.0 §3.1 — Authentication using the Authorization
    Code Flow.
  - OAuth 2.1 (draft) — §4.1.3 redirect_uri string-comparison rule.

## Alternatives considered and rejected

- Implicit flow — deprecated by OAuth 2.1; tokens leak through browser
  history.
- Resource-owner password credentials grant — forbidden by OAuth 2.1 for
  untrusted clients.
- Per-provider bespoke flow in each microservice — guarantees divergent
  state validation and re-invents CSRF bugs per integration.

## Extension contract

Downstream tools register new identity providers by constructing a
`ProviderMetadata` whose `code_challenge_methods_supported` includes
`"S256"`. The factory refuses to bind a provider that does not advertise
PKCE S256. Token-endpoint transport is injected as a callable so production
deployments swap in httpx / requests / an mTLS-wrapped client without
changing the primitive.

## Schema of `AuthorizationCodeFlow.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from AuthorizationCodeFlow import ProviderMetadata, create_flow

provider = ProviderMetadata(
    authorization_endpoint="https://accounts.example/authorize",
    token_endpoint="https://accounts.example/token",
    jwks_uri="https://accounts.example/jwks",
    code_challenge_methods_supported=("S256",),
)

def httpx_token_endpoint(req):  # wire to your HTTP client of choice
    import httpx
    return httpx.post(provider.token_endpoint, data=dict(req)).json()

flow = create_flow(
    client_id="my-app",
    redirect_uri="https://my-app.example/oauth/callback",
    provider=provider,
    token_endpoint=httpx_token_endpoint,
)

# --- request phase ---
auth_request = flow.begin(scopes=["openid", "profile", "email"])
session["oauth_request"] = auth_request  # stash verbatim
return redirect(auth_request.authorization_url)

# --- callback phase ---
stored = session.pop("oauth_request")
tokens = flow.exchange(code=request.args["code"], state=request.args["state"], stored=stored)
```

## Compose with:

- **Login handshake** → `SessionStore` + `CurrentPrincipal`
  Successful code exchange mints a server-side session and resolves the principal — the access token never leaks to the browser.

- **Confidential client** → `SecretsVault` + `TokenIntrospector`
  Client secret is fetched from the vault at exchange time, never baked into config; issued tokens are later introspected via the same trust chain.

- **Step-up to MFA** → `TotpVerifier` + `WebAuthnAuthenticator`
  The flow hands off to a second-factor primitive before session elevation — the code grant alone is never sufficient for sensitive scopes.
