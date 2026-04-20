# RouterPipeline

## What it does (plain language)

RouterPipeline is the "named middleware bundle" vocabulary that web frameworks
like Phoenix and Rails-Rack popularised. You declare a pipeline once with a
name (`"browser"`, `"api"`, `"internal"`) and a list of middleware, then groups
of routes join that pipeline by reference — so "add auth to /api" is a
one-line change, not a per-route edit.

### One-minute mental model (junior-friendly)

- A **pipeline** is a named tuple of middleware. `"api"` might mean
  `[parse_json, require_auth]`; `"browser"` might mean
  `[accept_html, fetch_session]`.
- A **route** (e.g. `/v1/users/:id`) **attaches** to exactly one pipeline. When
  that route is dispatched, the pipeline's middleware runs in declared order,
  then the handler runs. Never the other way around.
- All per-request state lives in `RequestContext.assigns` — a fresh dict per
  request. Pipelines themselves stay immutable after `Router.seal()`, so two
  concurrent requests CANNOT pollute each other.

### Glossary (terms used below)

- **Middleware** — a callable `(ctx, next) -> object`; either call `next(ctx)`
  to continue or return a value to short-circuit.
- **Chain** — the ordered list of middleware inside one pipeline.
- **Seal** — the one-way gate (`Router.seal()`) that freezes the router; after
  seal, no new pipelines and no new route attachments are allowed.
- **Assigns** — Phoenix-inspired name for the per-request key/value bag that
  middleware uses to pass data down the chain.

### Hello, world

```python
from RouterPipeline import Router, RequestContext

def parse_json(ctx, next_):
    ctx.assigns["parsed"] = True
    return next_(ctx)

def require_auth(ctx, next_):
    if ctx.assigns.get("token") != "valid":
        ctx.halt("unauthenticated")
        return {"status": 401}
    return next_(ctx)

router = Router()
router.register("api", [parse_json, require_auth])   # declare once
router.get("api").attach("/v1/users/:id")            # routes join by name
router.get("api").attach("/v1/orders")
router.seal()                                        # one-way gate

ctx = RequestContext(route="/v1/users/:id", assigns={"token": "valid"})
router.dispatch("/v1/users/:id", lambda c: c.assigns, ctx)
```

## Purpose

Named bundle of middleware (e.g. 'browser', 'api') that a route joins with
`pipe_through` so groups of endpoints share the same pre-dispatch chain.

## When to use and when NOT to use

- USE: any API or web server where several route groups share a cross-cutting
  concern (auth, parsing, throttling, content-negotiation). The pipeline IS
  the vocabulary for "this group of routes behaves the same way".
- USE: when "add auth to /api" must be a one-line change reviewable in a PR,
  rather than a grep-and-edit across every route file.
- DO NOT USE: a single endpoint with one-off middleware — a per-route decorator
  is cheaper than declaring a pipeline of size 1.
- DO NOT USE: as a general plugin / DI container. A pipeline is a *request
  processing* concept; it does not replace wiring for services that live
  outside the request path.

## API surface

The catalog `api_signature` is the sole authority; see
`RouterPipeline.contract.json` for the verbatim Protocol declaration. The
reference `Router` exposes `register(name, middleware)`, `get(name)`,
`seal()`, `dispatch(route, handler, ctx)` plus the `pipelines` and
`attachments` read-only properties. Pipelines expose `attach(route)` (the
Protocol's sole method) and a `routes` snapshot.

| member | meaning |
|---|---|
| `Router.register(name, middleware)` | Declare a pipeline; raises RP-INV-05 on duplicate name, RP-INV-04 if sealed. |
| `Router.get(name)` | O(1) lookup of a pipeline; raises if unknown (RP-INV-05 supporting). |
| `pipeline.attach(route)` | Join a route to this bundle; raises RP-INV-04 post-seal. |
| `Router.seal()` | Freeze the router; enables `dispatch`; disables registration and attach. |
| `Router.dispatch(route, handler, ctx)` | Run the attached chain in declared order, then the handler (RP-INV-01, RP-INV-02). |
| `RequestContext.assigns` | Per-request mutation surface (RP-INV-03). |
| `RequestContext.halt(reason)` | Short-circuit the chain while keeping the request "delivered". |

## Invariants

| ID | Rule |
|---|---|
| RP_INV_01 | A pipeline MUST run its middleware in declared order, every time; reorder at runtime SHALL NEVER happen. |
| RP_INV_02 | A route joined to a pipeline MUST execute its chain before the handler; the chain CANNOT be bypassed per request. |
| RP_INV_03 | Pipelines MUST NOT share mutable state across requests; any state SHALL live in RequestContext.assigns. |
| RP_INV_04 | Joining a route to a pipeline MUST be declarative; programmatic attach CANNOT happen after the router is sealed. |
| RP_INV_05 | A pipeline name MUST be unique within the router; duplicate declarations SHALL raise at boot. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- `register`, `record_attachment`, and `seal` acquire an internal lock; a
  16-thread race to register the same pipeline name yields exactly one winner
  (the rest hit RP-INV-05).
- The middleware tuple captured at registration is immutable; dispatch only
  reads from it. There is no re-ordering API — RP-INV-01 is structural.
- Per-request state lives on `RequestContext.assigns`, a field-level
  `default_factory=dict`. Each new `RequestContext()` gets its own dict, so
  concurrent dispatches never share mutable state (RP-INV-03).
- `run_chain` is a plain recursive function; it holds no locks and is safe to
  call from any thread.

## Operational characteristics (for SRE)

- Registration is O(number_of_middleware) once per pipeline; dispatch is
  O(chain_length) per request and includes no synchronisation beyond the
  single route-index lookup.
- Primary SLOs to alert on: `router.request.duration` p99 and the halted-rate
  per pipeline. A rising halted-rate under `"api"` usually means an auth
  middleware is rejecting a surge.
- Primary dashboards: requests-dispatched, duration p50/p95/p99, halted ratio.
  See `dashboard.json` for the starter Grafana layout.
- Failure policy: exceptions inside middleware propagate up through
  `run_chain` — the caller (usually the HTTP server) handles them. Because
  `assigns` is per-request, a crash in one request cannot corrupt another.

## Security considerations

- **Sealing is the enforcement boundary.** Any attempt to add a pipeline or
  attach a route after `seal()` raises RP-INV-04. This closes the late-binding
  hijack vector where a rogue module could silently install an
  attacker-controlled middleware chain.
- **Duplicate names are refused at boot (RP-INV-05).** A late-loaded module
  cannot silently replace `"api"` with its own middleware; the build breaks
  loudly before serving traffic.
- **Route hijack is refused (RP-INV-02 supporting).** Attempting to attach the
  same route to two pipelines raises — the router always has one
  authoritative chain per route.
- **Per-request isolation (RP-INV-03).** `RequestContext.assigns` uses
  `default_factory=dict`, so there is no shared mutable default. Two
  concurrent requests cannot leak auth/session state between each other.
- **Middleware authoring is the remaining trust boundary.** The pipeline
  guarantees order, but the middleware bodies themselves decide what to
  enforce. Review pipelines the same way you review allow-lists.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - Phoenix 1.7 Router — `pipeline/2`, `pipe_through/1`
    (`hexdocs.pm/phoenix/Phoenix.Router.html`, "Pipelines" and "Scopes"
    sections).
  - Plug 1.x — `Plug.Builder` pipelines
    (`hexdocs.pm/plug/Plug.Builder.html`, "plug" directive composition).

## Alternatives considered and rejected

- **Per-route decorator stacks** — every route repeats the same middleware
  list; a change to the shared chain requires editing N files, and it is easy
  to forget a route when rolling out a new cross-cutting concern.
- **Single global middleware chain** — cannot vary by route group; routes that
  must NOT run auth (e.g. `/healthz`) either leak through the auth middleware
  or force conditional logic inside the middleware itself.
- **URL-prefix-based conditionals in middleware** — fragile; a new route added
  under an unexpected prefix silently bypasses the group's rules.

## Extension contract

Downstream tools declare a pipeline via `Router.register(name, middleware)` or
an equivalent `pipeline/2`-style macro and then scope routes with `attach()`
(or a `pipe_through` directive). Frameworks plug in by providing their own
adapter that respects RP-INV-01 (order) and RP-INV-05 (name uniqueness). The
Protocol surface is additive: new pipelines and new attachments extend the
router without breaking existing consumers. Semver: v1.

## Schema of `RouterPipeline.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the
governing standards.

## Usage

```python
def build_api(router: Router) -> None:
    # Declarative wiring — no side effects on other pipelines.
    router.register("api", [parse_json, require_auth, rate_limit])
    router.register("browser", [accept_html, fetch_session, csrf])
    router.get("api").attach("/v1/users/:id")
    router.get("browser").attach("/")
    router.seal()

def serve(router: Router, route: str, handler):
    # RP-INV-01 + RP-INV-02: chain runs in order, then handler runs.
    return router.dispatch(route, handler, RequestContext(route=route))
```

## Compose with:

- **Browser vs API split** → `MiddlewarePipeline` + `CsrfGuard` + `CorsPolicy`
  The 'browser' pipeline enforces CSRF and session cookies; the 'api' pipeline enforces bearer tokens and CORS — one route cannot accidentally inherit the wrong edge.

- **Read/write separation** → `CommandQuerySeparator` + `MiddlewarePipeline`
  Query pipelines skip UoW and write-locks; command pipelines mount them — the router is the single place this contract lives.

- **Tenanted edge** → `RequestGuard` + `CurrentPrincipal`
  Per-tenant pipelines stamp tenant id into the context before authorization runs, so downstream handlers never need to re-extract it from headers.

- **Per-request batch fan-in** → `DataLoader` + `RequestContext`
  The router installs a fresh `DataLoader` on each request and tears it down at the end; resolvers inside the pipeline coalesce their per-key lookups into one bulk fetch. Invariant gained: N+1 fan-out cannot escape a single request's lifespan.
