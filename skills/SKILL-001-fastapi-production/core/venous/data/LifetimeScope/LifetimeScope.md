# LifetimeScope

## Executive summary (for PM / non-engineers)

LifetimeScope is a three-value vocabulary — SINGLETON, SCOPED, TRANSIENT —
that tells the rest of the system how long any given object should live.
With one enum, we stop the entire class of bugs where a "shared forever"
object accidentally holds a "lasts one request" object and crashes only
under load. Every framework the team might pick (ASP.NET, Spring, Nest.js,
Quarkus) has the same three buckets; LifetimeScope gives us one word
inside our codebase that maps cleanly to all of them.

## What it does (plain language)

LifetimeScope answers a single question: "when something gets constructed,
how long should it live?" There are exactly three answers:

- **singleton** — one copy for the whole process.
- **scoped** — one copy per request / session / tenant, thrown away when
  that scope ends.
- **transient** — a fresh copy every time you ask.

Alongside the enum this module also ships `ScopeManager`, a reference
implementation that actually tracks instances per scope and disposes them
in reverse (LIFO) order when the scope ends. Parent scopes flow into
children so a deeply nested request can still see the same configuration
singleton.

## Glossary

- **Lifetime** — how long a constructed object is meant to live.
- **Scope** — a bounded region (typically one request) during which
  `scoped` instances are shared. Ends with explicit `dispose()` or exit
  from a `with scope:` block.
- **LIFO disposal** — the last instance created in a scope is the first
  one released when the scope ends, mirroring normal resource unwinding.
- **Leak** — a longer-lived owner accidentally capturing a shorter-lived
  dependency (classic: a singleton grabbing a scoped DB session). The
  manager rejects this at construction time.
- **Closed vocabulary** — only the three enum members are valid; any raw
  string (e.g. `"request"`, `"Singleton"`) is rejected.

## Minimal example

```python
from LifetimeScope import LifetimeScope, ScopeManager

class Config:          # shared forever
    pass

class Session:         # one per request
    def close(self) -> None:
        ...

class RequestId:       # fresh every call
    pass

m = ScopeManager()
m.register("config",  Config,     scope=LifetimeScope.SINGLETON)
m.register("session", Session,    scope=LifetimeScope.SCOPED)
m.register("reqid",   RequestId,  scope=LifetimeScope.TRANSIENT)

with m.scope() as request:
    cfg  = request.resolve("config")   # shared with every other request
    sess = request.resolve("session")  # lives for this request only
    rid1 = request.resolve("reqid")    # each call a new object
    rid2 = request.resolve("reqid")
    assert rid1 is not rid2
# On exit, sess.close() runs (LIFO); singletons stay.
```

## Purpose

Typed enumeration that fixes how long a resolved instance lives: the
whole process, one request, or one injection point. The bundled
`ScopeManager` realises those semantics with parent→child scope
inheritance and LIFO disposal on scope exit.

## When to use and when NOT to use

- USE: anywhere your app distinguishes "one per process" from "one per
  request" — web handlers, workers, test fixtures.
- USE: when you need deterministic disposal order (LIFO) for sessions,
  DB transactions, outbound HTTP clients.
- DO NOT USE: as a generic lifetime string bag — the enum is the ONLY
  legal surface.
- DO NOT USE: when a brand-new value is needed (e.g. `"request"` for
  Spring parity) — add an enum member, do not smuggle a string.

## API surface

The catalog `api_signature` in `LifetimeScope.contract.json` is
authoritative for the enum shape. Module-level extensions:

- `LifetimeScope.SINGLETON | SCOPED | TRANSIENT` — the closed vocabulary.
- `coerce(value)` — turn a known wire string or enum member into the enum;
  anything else raises `LifetimeScopeInvariantError` (LS-INV-05).
- `is_closed_value(value)` — `True` iff the value is exactly one of the
  three declared members / strings.
- `ScopeManager` — reference manager:
  - `register(key, factory, *, scope)` — register under a string key.
  - `register_instance(key, instance)` — wire an externally-owned
    singleton (never disposed by the manager).
  - `resolve(key)` / `resolve_typed(key, type)` — get an instance
    obeying the declared lifetime.
  - `open_scope()` / `scope()` — create a child scope; `scope()` is a
    context manager that guarantees LIFO `dispose()` on exit.
  - `dispose()` — idempotent release of all scope-owned instances.
  - Introspection: `scope_snapshot()`, `singleton_snapshot()`,
    `is_registered()`, `lifetime_of()`, `depth`, `disposed`.

## Invariants

| ID | Rule |
|---|---|
| LS_INV_01 | SINGLETON instances MUST be shared process-wide and created at most once per container. |
| LS_INV_02 | SCOPED instances MUST be created at most once per scope and disposed when the scope ends (LIFO order). |
| LS_INV_03 | TRANSIENT instances MUST be created per resolution call and NEVER reused across call sites. |
| LS_INV_04 | A SINGLETON MUST NEVER depend on a SCOPED or TRANSIENT disposable that requires a live request scope. |
| LS_INV_05 | The value set MUST be closed: any new lifetime requires an explicit enum addition, NEVER a string literal. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the exact binding.

## Lifetime semantics (state-transition table)

| Scope      | Cache location           | Resolve returns                         | Disposed on scope exit? |
|------------|--------------------------|-----------------------------------------|-------------------------|
| singleton  | root manager             | same instance forever                   | no (process lifetime)   |
| scoped     | current scope            | same instance within the scope          | yes, in LIFO order      |
| transient  | never                    | fresh instance every resolve            | n/a (caller owns)       |

Resolving a scoped registration from the root is FORBIDDEN
(LS-INV-02). Resolving from a disposed scope is FORBIDDEN.

## Parent→child scope inheritance

`open_scope()` (and the `scope()` context manager) returns a child
manager that shares the registration map and singleton cache with the
root but owns its OWN scoped cache + creation-order list. Depth
increases monotonically (root = 0, child = 1, grandchild = 2, …) and is
readable via `manager.depth`. A child resolving a singleton observes the
SAME identity as the root (LS-INV-01).

## Thread and async safety

- Registration is guarded by an `RLock` shared by root and every child.
- Singleton construction is idempotent under concurrent resolve — the
  first resolver wins, subsequent callers observe the cached instance.
- Scoped caches are per-scope, protected by their own `RLock`. A single
  scope MUST NOT be resolved from multiple async tasks without external
  synchronisation; instance construction runs inside the lock.
- `dispose()` drains the scope even when an individual `close()` raises;
  the failure is swallowed so the remaining instances still release.

## Operational characteristics (for SRE)

- Root manager keeps singleton instances for the process lifetime. At
  shutdown, the process exit releases them (no explicit call needed).
- Scoped disposal runs `close()` on each instance in reverse of creation
  order; failures are swallowed to guarantee drain.
- Metrics (self-observability): `lifetime.resolves` (counter,
  `scope` + `cached` labels), `lifetime.scope.depth` (histogram),
  `lifetime.scope.instance_count` (histogram),
  `lifetime.dispose.duration` (histogram).
- A rising p95 on `lifetime.scope.instance_count` points at a scope
  leaking caches (handlers registering ad-hoc scoped entries).

## Security considerations

- Factories are arbitrary callables — restrict who may call `register()`
  to application bootstrap / composition-root code in production.
- `register_instance` grants the caller ownership of disposal; auditors
  MUST confirm that externally-owned resources are closed on shutdown.
- The closed enum (LS-INV-05) prevents scope typos from silently degrading
  to an unintended lifetime — a common attack surface in frameworks that
  accept free-form strings.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - ASP.NET Core 8.0 Fundamentals — Service lifetimes
    (`AddSingleton`, `AddScoped`, `AddTransient`).
  - Spring Framework Reference — Bean Scopes (`singleton`, `prototype`,
    `request`).
  - Nest.js 10 — Injection scopes
    (`Scope.DEFAULT`, `Scope.REQUEST`, `Scope.TRANSIENT`).
  - Quarkus 3.x CDI Guide (`@ApplicationScoped`, `@RequestScoped`,
    `@Dependent`, `@Singleton`).

## Alternatives considered and rejected

- Free-form string scope names — no compile-time check, drift across
  tools. A typo silently downgrades a lifetime under load.
- Boolean `shared / not shared` — collapses SCOPED and SINGLETON into
  one value, making request-bound state indistinguishable from
  process-wide state.
- Framework-specific annotations only — breaks cross-framework
  portability and couples business code to the current DI container.

## Extension contract

Alternative frameworks map their native lifetimes (Spring `request`,
Nest.js `REQUEST`, ASP.NET `Scoped`, Quarkus `@RequestScoped`) onto this
enum via an adapter that translates `register()` calls; new lifetimes
require extending the enum, not bypassing it. Adapters MUST preserve
LS-INV-01..05.

## Schema of `LifetimeScope.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from
the research catalog. Fields: `name`, `namespace`, `purpose`,
`api_signature`, `invariants[]`, `extension_contract`,
`consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage

```python
def register_scoped(m: ScopeManager, key: str, impl: type) -> None:
    m.register(key, impl, scope=LifetimeScope.SCOPED)

def handle(m: ScopeManager) -> None:
    with m.scope() as request:
        session = request.resolve("session")
        # ... do work with session ...
    # session.close() runs here
```

## Compose with:

- **Per-request UoW** → `DiContainer` + `UnitOfWork`
  Request scope owns the UoW; entering the pipeline creates it, exiting disposes it — handlers never leak transactions across requests.

- **Singleton config** → `ConfigBinding` + `DiContainer`
  Typed config is singleton; request-scoped consumers re-read it without re-parsing — hot-reload of config is O(1) per request.

- **Operation-scoped tracing** → `RequestContext` + `Tracer`
  Operation scope matches span scope; spawned spans inherit request context without handlers threading anything by hand.
