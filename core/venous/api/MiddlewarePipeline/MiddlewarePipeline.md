# MiddlewarePipeline

## What it does (plain language)

A `MiddlewarePipeline` is an *ordered* list of small components — "middlewares"
— that each receive the current request, do their piece of work (log, auth,
rate-limit, trace, shape errors), and then either hand control to the next
middleware or stop the chain right there. It is the shape behind every
framework's `app.use(...)` call: Express, ASP.NET Core, Nest.js interceptors,
Elixir Plug, Python Starlette middleware. One chain, one contract, one place
to reason about cross-cutting concerns.

### One-minute mental model (junior-friendly)

```
request → [auth] → [logging] → [rate-limit] → [handler] → response
                                   ↑
                         each stage may stop the chain
```

- A **middleware** is an `async` function that takes `(ctx, call_next)` and
  either `await call_next()` (to continue) or returns without awaiting (to
  *short-circuit* — everything downstream is skipped).
- **RequestContext** is the shared envelope: method, path, headers, a mutable
  `attributes` bag for stashing state (`ctx.put("user_id", 42)`) and the
  response slot (`ctx.write_response(200, body)`).
- **Registration is frozen** the first time you call `run()`. Adding new
  middleware at request time is a bug, so the primitive raises instead of
  silently accepting it (INV-04).
- **Every request produces a response.** Even if a middleware forgets to
  write one, the pipeline stamps a `500` so clients never hang (INV-05).

### Hello, world

```python
import asyncio
from MiddlewarePipeline import (
    InMemoryMiddlewarePipeline, RequestContext, Next,
)

pipe = InMemoryMiddlewarePipeline()

async def logging(ctx: RequestContext, call_next: Next) -> None:
    print(f"{ctx.method} {ctx.path} …")
    await call_next()
    print(f"  → {ctx.status}")

async def auth(ctx: RequestContext, call_next: Next) -> None:
    if ctx.headers.get("Authorization") != "Bearer OK":
        ctx.write_response(401, {"error": "unauth"})
        return                          # short-circuit: handler NEVER runs
    await call_next()

async def handler(ctx: RequestContext, call_next: Next) -> None:
    ctx.write_response(200, {"hello": "world"})

pipe.use(logging).use(auth).use(handler)

ctx = RequestContext(headers={"Authorization": "Bearer OK"})
asyncio.run(pipe.run(ctx))
# GET / …
#   → 200
```

### Glossary (terms used below)

- **Short-circuit** — a middleware returns without awaiting `call_next`,
  preventing all downstream middleware from running.
- **Error filter** — a registered handler for exceptions raised anywhere in
  the chain; always consulted (INV-03).
- **Frozen pipeline** — after the first `run()`, no further `use(...)`,
  `insert_before`, `remove`, or `swap` is accepted (INV-04).
- **Re-entrancy** — multiple concurrent requests may call `run()` on the
  same pipeline; each carries its own `RequestContext`, so state is isolated.

## Purpose

Ordered chain of components that each transform the RequestContext and
decide whether to call the next, enabling cross-cutting concerns.

## When to use and when NOT to use

- USE: any HTTP / RPC / queue-worker dispatcher where authorisation, logging,
  tracing, rate limiting, or error shaping apply uniformly across endpoints.
- USE: when you want ordering to be a first-class, inspectable contract
  (INV-01) rather than a side-effect of import order.
- DO NOT USE: for per-handler decoration that varies wildly (prefer explicit
  decorators). A chain is for *cross-cutting* concerns, not per-route logic.
- DO NOT USE: as an async task orchestrator; the chain contract assumes
  one request in, one response out. Fan-out belongs elsewhere.

## API surface

The catalog `api_signature` is the sole authority; see
`MiddlewarePipeline.contract.json` for the verbatim Protocol declaration.
The reference `InMemoryMiddlewarePipeline` exposes `use`, `use_error_filter`,
`insert_before`, `insert_after`, `remove`, `swap`, `freeze`, `names`,
`frozen`, and `run`.

| Method | Purpose | INV |
|---|---|---|
| `use(mw, *, name=None)` | Append a middleware to the chain. | INV-01, INV-04 |
| `use_error_filter(flt)` | Register an error filter, always consulted. | INV-03, INV-04 |
| `insert_before(anchor, mw, *, name)` | Explicit insert — never implicit. | INV-01 |
| `insert_after(anchor, mw, *, name)` | Explicit insert — never implicit. | INV-01 |
| `remove(name)` | Explicit removal by name. | INV-01 |
| `swap(a, b)` | Explicit reordering by name. | INV-01 |
| `freeze()` | Idempotent; called implicitly on first `run()`. | INV-04 |
| `run(ctx)` | Drive the chain; always produces a response. | INV-02/03/05 |

A middleware is any `async` callable of the shape
`async def mw(ctx: RequestContext, call_next: Next) -> None`. An error filter
is `async def flt(ctx: RequestContext, exc: BaseException) -> None`; filters
run in registration order and MAY choose to resolve by calling
`ctx.write_response(...)`.

## Invariants

| ID | Rule |
|---|---|
| MWP_INV_01 | Execution order MUST be the registration order; swap or insert operations SHALL be explicit, never implicit. |
| MWP_INV_02 | A middleware that does NOT await call_next MUST short-circuit the remainder of the pipeline. |
| MWP_INV_03 | Each middleware CANNOT bypass downstream error handling: exceptions NEVER skip registered error filters. |
| MWP_INV_04 | Registration MUST be frozen before run() is first called; adding middleware at request time SHALL raise. |
| MWP_INV_05 | MUST produce a response even if every middleware halts; an unhandled halt SHALL yield a 500 by contract. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- Registration mutations (`use`, `insert_*`, `remove`, `swap`, `freeze`) are
  guarded by a process-wide lock on the pipeline instance; ordering is
  deterministic across threads.
- `run()` snapshots the middleware list under the lock and walks the tuple
  without further locking — the primitive itself is stateless on the hot
  path, so concurrent requests cannot interfere. Per-request state lives on
  the `RequestContext` argument (which the caller owns).
- First `run()` atomically sets `_frozen = True`; later registration calls
  observe the flag inside the lock and raise `MWP-INV-04`.

## Operational characteristics (for SRE)

- Chain length is configuration; track it with `pipe.names` and assert a
  startup invariant in your boot sequence (e.g. `len(pipe.names) == 7`).
- Dashboards (see `dashboard.json`) track request rate, p50/p95/p99 latency,
  short-circuits per middleware, error filter resolution rate, and 5xx rate
  (the INV-05 tripwire — a sudden bump means unhandled halts).
- SLO baseline: p99 `run()` < 50 ms for a 7-stage chain on a warm process;
  5xx rate from INV-05 should be *zero* in steady state. Any non-zero reading
  indicates a middleware bug (halted without writing a response).
- Failure policy: exceptions propagate after *every* error filter runs
  (INV-03). If no filter writes a response, INV-05 stamps a 500 body so the
  outer adapter always has something to serialize.

## Security considerations

- Authorisation middleware relies on INV-02: if `auth` short-circuits with a
  401/403, the handler cannot run. Audit that every auth-critical chain has
  auth BEFORE the handler (use `pipe.names` in a startup check).
- Error filters are the security boundary for error shaping: without INV-03
  a middleware could swallow an exception and let a request leak past auth.
  The runtime guarantees every filter is invoked, so the shape of the 5xx
  response is deterministic.
- INV-04 prevents request-time handler injection: an attacker who can reach
  a live pipeline cannot register a rogue middleware to intercept traffic.
- INV-01's explicit naming prevents a late import from silently inserting
  a middleware in the wrong position; name collisions raise immediately.
- The RequestContext's `attributes` dict is process-local; do not serialise
  it to the wire without filtering — middleware MAY stash secrets there
  (e.g. resolved principals).

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - ASP.NET Core 8.0 middleware — `RequestDelegate`, `app.Use` pattern
    (learn.microsoft.com/aspnet/core/fundamentals/middleware).
  - Elixir Plug 1.x behaviour — `init/1`, `call/2`
    (hexdocs.pm/plug/readme.html).
  - Nest.js 10 Interceptors — `NestInterceptor.intercept(context, next)`
    (docs.nestjs.com/interceptors).

## Alternatives considered and rejected

- **AOP via bytecode weaving** — invisible and hard to debug. A chain you
  can `print(pipe.names)` is vastly more observable than a classfile rewrite.
- **Decorators per handler** — combinatorial explosion. Ten cross-cutting
  concerns × fifty handlers means five hundred decorations to keep in sync;
  one chain subsumes the entire quadratic.
- **Monkey-patching a dispatcher** — breaks framework upgrades. Every minor
  version of the underlying framework becomes an integration bug.

## Extension contract

Consumers add behavior by implementing `Middleware` (an async callable with
the `(ctx, call_next)` signature) and calling `pipeline.use()`. Alternative
framework styles (NestJS interceptor, Plug module, ASP.NET IMiddleware, Rack
app) MUST be bound via an adapter that forwards `(ctx, call_next)` and
preserves registration ordering. Extensions MUST preserve the five
invariants above. Semver: the `Middleware`/`MiddlewarePipeline` Protocol
surface is v1; adding new `use*` helpers to the reference implementation is
additive and does not break consumers.

## Schema of `MiddlewarePipeline.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`. See
`docs/research/CONTRACT_STANDARDS.md` section 2 (PrimitiveSpec) for the
governing standards.

## Usage

```python
async def timing(ctx: RequestContext, call_next: Next) -> None:
    t0 = 0.0
    await call_next()
    ctx.put("elapsed_ms", t0)

def build(p: MiddlewarePipeline) -> MiddlewarePipeline:
    return p.use(timing)
```

## Compose with:

- **Edge security chain** → `RequestGuard` + `CsrfGuard` + `RequestContext`
  Authn → authz → CSRF runs in a fixed order; downstream handlers receive a RequestContext already stamped with principal and verified origin.

- **Observability wrapping** → `CorrelationContext` + `StructuredLogger` + `Tracer`
  The outermost middleware stamps a correlation id and opens the root span so every log line and child span in the pipeline is automatically joined.

- **Resiliency envelope** → `TimeoutBudget` + `LoadShedder` + `CircuitBreaker`
  Pipeline entry computes the deadline and enqueues the request under a priority class; inner middleware inherits the remaining budget — no handler gets more time than the ingress contract promised.
