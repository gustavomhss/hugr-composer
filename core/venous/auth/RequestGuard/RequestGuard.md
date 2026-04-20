# RequestGuard

## What it does (plain language)

RequestGuard is the "may this request reach the handler?" primitive. You write
a tiny predicate (one async method: `allow(ctx, principal) -> bool`), drop it
onto a route, and the pipeline asks every guard for a vote before it ever
touches your handler. One deny blocks the request; all allows let it through.
If a guard raises, the request becomes a 500 — never a silent allow.

## Purpose

Enforce declarative, composable authorization: one decision point per route,
audited centrally, with a strict life-cycle so a mis-used guard cannot leak
an unchecked request to the handler.

## When to use and when NOT to use

- USE: role checks, tenant checks, feature-flag gating, scope verification,
  any yes/no policy that ONLY needs `(ctx, principal)` to decide.
- DO NOT USE: transforming a payload (use a middleware/interceptor), writing
  audit rows (use an interceptor after the handler), or any decision that
  needs the handler's return value. Guards are strictly pre-handler and
  strictly binary.
- DO NOT USE: cross-request state (rate-limits, counters) — guards run under
  a lifecycle-scoped CompositeGuard that is fresh per request. Use the
  resiliency primitives for that.

## API surface

The catalog `api_signature` in `RequestGuard.contract.json` is authoritative:

```python
from typing import Protocol

class RequestGuard(Protocol):
    async def allow(self, ctx: RequestContext, principal: CurrentPrincipal) -> bool: ...
```

Callers build a `CompositeGuard([g1, g2, ...])` (or use the convenience
`and_guards(g1, g2, ...)`), then `HandlerDispatch().dispatch(composite, ctx,
principal, handler)` does the evaluation. The dispatcher returns a
`HandlerResult` with a `GuardDecision` that tells the pipeline which HTTP
status to emit and whether the handler ran.

## Invariants

| ID | Rule |
|---|---|
| RG_INV_01 | A False return from the composition MUST prevent the handler from running and SHALL produce a 401 (anonymous) or 403 (authenticated) response. |
| RG_INV_02 | Guards MUST NOT mutate the request body nor the principal; the runtime snapshot check aborts with `RequestGuardInvariantError` on any drift. |
| RG_INV_03 | Multiple guards MUST be composed with logical AND; a single False blocks the request and MUST short-circuit remaining guards. |
| RG_INV_04 | Guards MUST execute after authentication has bound a principal, BEFORE the handler, and a terminal CompositeGuard CANNOT be reused — a fresh one is required per request. |
| RG_INV_05 | A guard that raises NEVER gets silently treated as allow; exceptions (and non-bool returns) SHALL map to the ERROR outcome (HTTP 500). |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json`. The T2 formal model (`RequestGuard.tla`) proves
RG-INV-01, RG-INV-03, RG-INV-04, RG-INV-05 as temporal safety properties.

## Thread and async safety

- `CompositeGuard` is lock-guarded on the OPEN → EVALUATING transition, so
  two threads cannot accidentally drive the same composite into
  evaluation simultaneously; one wins, the other sees
  `RequestGuardInvariantError`.
- Guards themselves MUST be re-entrant across distinct composites — the
  primitive assumes one CompositeGuard per request and shares nothing in
  its own state. Guards that want shared state own it.
- Evaluation is single-threaded per request by design; inside one
  evaluation the guard list is walked sequentially so short-circuit order
  is deterministic.

## Operational characteristics (for SRE)

- `guard.decisions` (counter, `outcome` label) — rate of allow / deny /
  error decisions. Alert on a sudden jump in `outcome=error`: that is a
  guard implementation bug, not a policy change.
- `guard.evaluation.duration` (histogram, ms) — p95 usually sits in
  single-digit microseconds; a slow guard (> 10 ms p95) is a sign
  authentication is leaking into the guard or a network call is hiding
  inside what should be a pure predicate.
- `guard.short_circuit.depth` (histogram) — how many guards were actually
  run. A deep composite with p95 depth = 1 tells you the first guard is
  rejecting most requests; reorder for throughput.

## Security considerations

- Principals reach guards already bound by authentication middleware. A
  guard that reads `principal.is_anonymous` has an authoritative view;
  guards that try to re-authenticate CANNOT rewrite the principal.
- Guard exceptions NEVER become silent allows (RG-INV-05). A crashing
  guard is a crash, not an open door.
- The runtime mutation check (RG-INV-02) is a defense-in-depth: the
  dataclass freeze on `CurrentPrincipal` blocks most mutations statically,
  and the snapshot compare catches a malicious guard that uses
  `object.__setattr__` or similar bypass.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - Nest.js 10 — Guards (`CanActivate`), `docs.nestjs.com/guards`.
  - ASP.NET Core 8.0 — Authorization policies,
    `learn.microsoft.com/aspnet/core/security/authorization/policies`.

## Alternatives considered and rejected

- Inline role checks in handlers — no central audit, easy to forget;
  rejected by the catalog.
- A single monolithic authorization middleware — cannot attach different
  policies per route; rejected.
- Decorator metadata only — requires a reader and still needs a guard to
  enforce; the guard is the primitive the decorator composes with.

## Extension contract

Downstream tools implement `RequestGuard` and register via a decorator
(`@use_guards(RoleGuard("admin"))`), a `register()` call on the pipeline,
or a Plug inserted before dispatch. Guards compose via AND; they CANNOT
replace one another. Per catalog: a new guard type only adds a new
predicate — the composition rule and short-circuit order stay untouched.

## Schema of `RequestGuard.contract.json`

The contract file is a verbatim copy of the PrimitiveSpec dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
from RequestGuard import AuthenticatedGuard, RoleGuard, TenantGuard, and_guards, HandlerDispatch

composite = and_guards(
    AuthenticatedGuard(),
    RoleGuard("admin", "billing"),
    TenantGuard("acme"),
)

dispatch = HandlerDispatch()

async def admin_only_handler(ctx, principal):
    return {"ok": True}

result = await dispatch.dispatch(composite, ctx, principal, admin_only_handler)
# result.decision.http_status in {200, 401, 403, 500}
# result.decision.handler_invoked is True iff http_status == 200
```

## Compose with:

- **Route-level ABAC** → `CurrentPrincipal` + `AuditEvent`
  Guard evaluates attributes of principal + resource and emits an audit event for every deny — 'who tried what and was refused' is never silent.

- **Feature-gated rollout** → `FeatureToggle` + `CurrentPrincipal`
  A guard can require a toggle to be on for the caller's cohort; disabled cohorts see 404, not 403 — reducing feature-flag fingerprinting.

- **Pipeline-scoped policy** → `MiddlewarePipeline` + `RouterPipeline`
  The guard is mounted once on the pipeline; routes inherit the policy — individual handlers cannot forget to call it.

- **Query-allow-list gate** → `PersistedQueryRegistry` + `InputValidator`
  `RequestGuard` refuses any request whose persisted-query id is missing from the registry and escalates the reject to the rate-limiter so brute-force attempts are throttled. Invariant gained: only registered queries survive the gate, and every miss costs the caller a rate-limit tick.
