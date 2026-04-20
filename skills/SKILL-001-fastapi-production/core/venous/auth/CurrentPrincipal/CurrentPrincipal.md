# CurrentPrincipal

## What it does (plain language)

CurrentPrincipal is the single read-only view of "who is making this request".
Middleware decodes a credential once, binds an immutable principal (subject id,
tenant, roles, claims, plus an explicit `is_anonymous` flag), and every
downstream handler reads from it. Authorization logic stops duplicating across
tools, audit trails agree on who did what, and no call-site can mutate a role
or a subject to escalate.

## Purpose

Read-only view of the authenticated identity for the active request, including
subject id, tenant, roles, and claim set.

## When to use and when NOT to use

- USE: inside a request handler to check roles; inside a service to stamp the
  actor on an audit record; inside a dependency to branch on tenant.
- DO NOT USE: to store mutable per-request state (that is `RequestContext`).
- DO NOT USE: to hold raw credentials — the principal is downstream of token
  verification and does not retain the JWT / cookie.

## API surface

The catalog `api_signature` is the sole authority (see
`CurrentPrincipal.contract.json`). In this repo the primitive is a frozen,
slotted dataclass whose construction validates every invariant:

```python
@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    subject_id: str
    tenant_id: str | None
    roles: frozenset[str]
    claims: Mapping[str, str]
    is_anonymous: bool = False

    def has_role(self, role: str) -> bool: ...
    def has_any_role(self, roles: Iterable[str]) -> bool: ...
    def has_all_roles(self, roles: Iterable[str]) -> bool: ...
    def claim(self, key: str, default: str | None = None) -> str | None: ...
    def require_role(self, role: str) -> None: ...
    def for_log(self) -> dict[str, object]: ...
```

Factory helpers `anonymous()` and `authenticated(...)` should be preferred over
direct construction. The Protocol `PrincipalProvider` captures the extension
contract (middleware decodes a credential and returns a principal); the
reference `StaticPrincipalProvider` is for tests and single-tenant happy paths.

## Invariants

| ID | Rule |
|---|---|
| PRINCIPAL_INV_01 | MUST be immutable once bound; a later middleware CANNOT mutate any field. |
| PRINCIPAL_INV_02 | NEVER represents a successful auth state with `is_anonymous=True`; the two states are mutually exclusive. |
| PRINCIPAL_INV_03 | `roles` MUST be a `frozenset[str]`; plain set/list/tuple are rejected so a consumer cannot add a role at call time. |
| PRINCIPAL_INV_04 | `subject_id` MUST be stable, non-empty, non-whitespace, and free of control / null bytes; silent rotation is FORBIDDEN. |
| PRINCIPAL_INV_05 | Serialization for logs MUST omit raw claim values; every value is redacted by default. |

## Invariant → test mapping

Each invariant has three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- CurrentPrincipal is immutable (frozen dataclass, slots=True, frozenset roles,
  MappingProxy claims). Every method is a pure read. Sharing an instance across
  threads or asyncio tasks is safe without locking.
- `StaticPrincipalProvider` also takes a defensive copy of its mapping and
  exposes it read-only, so concurrent `resolve()` calls cannot corrupt state.

## Operational characteristics (for SRE)

- Zero I/O at import; zero I/O at resolve (the provider is pure table-lookup
  by default).
- Dashboards track `auth.principal.resolved` (per `is_anonymous`),
  `auth.principal.role_checks` (per `outcome`), and `auth.principal.claim_count`
  (histogram, per tenant). Alert when `anonymous` rate exceeds baseline by 3σ
  or when `role_checks{outcome="deny"}` spikes.
- No log line emitted by this primitive contains raw claim values; redaction
  is enforced at the source (PRINCIPAL_INV_05).

## Security considerations

- **No PII in logs.** `for_log()` redacts every claim value to `[REDACTED]` by
  policy. Explicit reads go through `.claim(key)` — callers who need a value
  have to ask for it, which makes logging a secret a code-review event rather
  than an accident.
- **Log injection is rejected.** `subject_id` and `tenant_id` reject null
  bytes, CR, LF, and C0 control chars so a malicious upstream cannot forge log
  lines through a crafted identifier.
- **Call-site escalation is blocked.** `roles` is a `frozenset`; there is no
  `.add()` method. Downstream code that tries to mutate the role set raises
  at the call site.
- **Anonymity is explicit.** The only way to say "no identity" is
  `anonymous()`; the primitive refuses an inconsistent state (e.g. anonymous
  with roles, or non-anonymous with empty subject_id).
- **Claims are defensively copied** into a `MappingProxyType` so a later
  mutation of the source dict cannot retroactively change the principal.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - ASP.NET Core 8.0 — `HttpContext.User` (ClaimsPrincipal).
  - Ruby on Rails 7 — `ActiveSupport::CurrentAttributes` (`Current.user`).
  - Nest.js 10 — `CanActivate` + `ExecutionContext.switchToHttp().getRequest().user`.

## Alternatives considered and rejected

- Pass a raw JWT string everywhere — rejected because it forces repeated
  parsing and loses type discipline.
- Put a plain `user` dict into `RequestContext.assigns` — rejected because it
  gives up frozen / typed guarantees and invites role mutation.
- Module-level globals like pre-Rails-7 `Current` — rejected because they are
  unsafe under threaded and async models.

## Extension contract

Middleware decodes an incoming credential (JWT, session cookie, API key) and
calls a registered `PrincipalProvider.resolve(credential)` that returns a
`CurrentPrincipal`. Downstream code reads the bound principal via dependency
injection (`request.state.principal`) and MUST NOT construct a
`CurrentPrincipal` outside the provider. New credential shapes are supported
by implementing a new `PrincipalProvider`; the Protocol is additive, so
existing consumers keep working.

## Schema of `CurrentPrincipal.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from CurrentPrincipal import authenticated, anonymous

def require_role(role: str, p) -> None:
    # PRINCIPAL_INV_02: anonymous never has roles; deny up front.
    if p.is_anonymous or not p.has_role(role):
        raise PermissionError(role)

alice = authenticated("alice", tenant_id="acme", roles=["admin"], claims={"email": "a@b.c"})
require_role("admin", alice)

# The unauthenticated default is explicit:
guest = anonymous()
assert guest.is_anonymous
```

## Compose with:

- **Authn → authz handoff** → `SessionStore` + `RequestGuard`
  SessionStore (or TokenIntrospector) produces the principal once; RequestGuard reads it as an immutable snapshot — no handler re-derives identity.

- **Auditable actor** → `AuditEvent` + `AccessLog`
  Every audit and access record carries the principal id and auth method verbatim, so forensic trails never have to reconstruct 'who was logged in at the time'.

- **Per-tenant context** → `RequestContext` + `RequestGuard`
  The principal includes tenant id; downstream authorization is scoped to that tenant — cross-tenant reads are a policy decision, not an oversight.
