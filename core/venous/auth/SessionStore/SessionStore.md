# SessionStore

## What it does (plain language)

SessionStore is the server-side record of "this caller is currently signed in."
It mints a cryptographically random id for each login, looks that id up when a
request comes back with a cookie, replaces the id on privilege elevation to
stop fixation attacks, and ends the session on logout or password change. It
enforces two independent clocks: an idle (sliding) clock that extends while
the user is active and an absolute clock that the session can never outrun.

## Purpose

Issue, rotate, and revoke server-side session records keyed by high-entropy
identifiers, with fixation resistance and explicit lifetime boundaries.

## When to use and when NOT to use

- USE: any product that authenticates humans and needs stateful, revocable
  sessions (web apps, customer portals, admin consoles).
- USE: whenever password change or suspicious-activity revocation MUST end
  every live session for a subject across devices.
- DO NOT USE: machine-to-machine APIs — use short-lived tokens with a separate
  revocation primitive.
- DO NOT USE: pure-signed-cookie deployments with no server state; those
  adapters are explicitly rejected at `register_adapter()` under
  SESSION-INV-05.

## API surface

The catalog `api_signature` in `SessionStore.contract.json` is the authority.
Callers mint a session with `create(subject)`, resolve a cookie with
`load(session_id)`, elevate privilege with `rotate(session_id)`, end a single
session with `revoke(session_id)`, and nuke every live session for a subject
(on password change) with `revoke_all_for_subject(subject)`.

## Invariants

| ID | Rule |
|---|---|
| SESSION_INV_01 | Session ids MUST carry >=128 bits of CSPRNG entropy and MUST NEVER encode user-controlled input. |
| SESSION_INV_02 | On privilege elevation the session id MUST be rotated; the prior id CANNOT be reused. |
| SESSION_INV_03 | Sessions MUST expire at min(idle, absolute); server-side revocation MUST win over client-held cookies. |
| SESSION_INV_04 | Session cookies MUST be Secure + HttpOnly + SameSite in {Lax, Strict}; Domain SHALL NEVER be broader than the application host. |
| SESSION_INV_05 | revoke_all_for_subject MUST terminate every live session for that subject atomically and MUST be invoked on password change. |
| SESSION_INV_06 | load() MUST NEVER extend a session past absolute_expires_at even on sustained activity. |

## Invariant -> test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding. The TLA+ model in
`SessionStore.tla` machine-verifies the matching safety properties
(`LiveRevokedDisjoint`, `IdleBoundedByAbsolute`, `TypeOK`).

## Lifecycle state machine

```
[none]
   | create(subject)
   v
[active]  --- load (sliding renew, capped by absolute) --> [active]
   | rotate(sid)
   v
[rotated]  (old id tombstoned; new id active)
   | revoke(sid)  OR  revoke_all_for_subject(subject)  OR  absolute ceiling hit
   v
[terminal]  (load returns None forever)
```

Rotation inherits the absolute ceiling so repeatedly elevating cannot extend
the hard cap (SESSION-INV-06). Revocation is an explicit tombstone so a later
replay of the old cookie cannot be accepted (SESSION-INV-02, SESSION-INV-03).

## Thread and async safety

- `InMemorySessionStore` serialises mutations via an internal `RLock`.
- `rotate()` wins-one-loser-many: concurrent rotate calls on the same id
  return exactly one fresh session; the rest raise `SessionInvariantError`.
- `revoke_all_for_subject()` is atomic under contention: concurrent callers
  sum to exactly the number of live sessions at the barrier.
- Session ids come from `secrets.token_urlsafe`, which is a CSPRNG; the store
  detects and refuses collisions rather than overwriting a live record.

## Operational characteristics (for SRE)

- Self-observability (wired by the web layer, schema in
  `observability_schema.json`):
  - logs: `session.created`, `session.rotated`, `session.revoked`,
    `session.revoked.all`, `session.expired`.
  - metrics: `session.active` (gauge), `session.lifecycle` (counter),
    `session.age` (histogram, `outcome` label), `session.revoke.batch`
    (histogram, `trigger` label).
  - spans: `session.create`, `session.rotate`, `session.revoke`,
    `session.revoke.all`.
- Alert thresholds: a sustained rise in `session.lifecycle{event="revoked"}`
  with no login spike signals either a stolen-cookie incident or a misconfigured
  rotate loop. p99 `session.age{outcome="revoked"}` close to the absolute
  window signals stuck sessions.

## Security considerations

- `mint_session_id()` draws 256 bits (>= 128 required) from `secrets.token_urlsafe`.
  A broken RNG collision is detected and refused, not silently overwritten.
- Rotation tombstones the prior id so a replay of the old cookie after
  elevation cannot resurrect the session (SESSION-INV-02).
- `CookieConfig` refuses `secure=False`, `http_only=False`, `SameSite=None`,
  and any Domain that starts with `.`. `validate_cookie_host()` rejects any
  Domain that differs from the application host (no broader-than-host cookies).
- `register_adapter()` refuses to bind adapters that lack server-side or
  subject-wide revocation, so a pure-signed-cookie backend cannot slip through
  the extension contract when policy requires password-change revocation.
- `sids_equal()` is a constant-time comparator for any code path that needs
  to compare two session ids.

## Provenance

- Source agent: Agent #5 SECURITY
  (`docs/research/outputs/AGENT_5_SECURITY.json`).
- Primary sources:
  - OWASP ASVS 4.0.3, V3 Session Management Requirements (V3.2 binding,
    V3.3 logout).
  - OWASP Top 10 2021, A07 Identification and Authentication Failures.

## Alternatives considered and rejected

- Pure JWT sessions with no server state — cannot revoke without a parallel
  denylist; SESSION-INV-03 and SESSION-INV-05 are unenforceable.
- Framework default session middleware — often lacks the dual-clock (idle +
  absolute) model and silently extends past the absolute ceiling.
- Sticky-session in-memory — fails `revoke_all_for_subject` under horizontal
  scale because each pod carries its own copy.

## Extension contract

Downstream storage backends register as SessionStore adapters (redis,
postgres). Each adapter MUST implement the Protocol surface AND declare
capabilities via `register_adapter(adapter, capabilities=...)`. Adapters that
do not support server-side revocation or subject-wide revocation are refused
at registration time (SESSION-INV-05).

## Schema of `SessionStore.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from SessionStore import InMemorySessionStore, CookieConfig

store = InMemorySessionStore(idle_timeout_s=1800, absolute_timeout_s=12 * 3600)
cookie = CookieConfig(name="sid", secure=True, http_only=True, same_site="Lax")

# Login:
session = store.create(subject="user-42")
# set_cookie(cookie.name, session.id, secure=cookie.secure, httponly=cookie.http_only, samesite=cookie.same_site)

# Request:
loaded = store.load(received_sid)
if loaded is None:
    # expired or revoked — force re-auth
    ...

# Privilege escalation (MFA, role change):
rotated = store.rotate(received_sid)
# re-issue the cookie with rotated.id

# Password change / security event:
store.revoke_all_for_subject("user-42")
```

## Compose with:

- **Browser session** → `CsrfGuard` + `CurrentPrincipal`
  Session id is httpOnly + secure; CsrfGuard binds state-changing requests to the same session — a stolen cookie alone is not sufficient for POST.

- **Rotation on privilege change** → `AuthorizationCodeFlow` + `AuditEvent`
  Every login, MFA step-up, and logout rotates the session id and writes an audit event — fixation and replay are detectable on the timeline.

- **Revocation fan-out** → `AuditEvent` + `BreachNotificationQueue`
  Security incident closes all sessions of impacted subjects and opens a breach incident with the actor list — containment and compliance in one stroke.
