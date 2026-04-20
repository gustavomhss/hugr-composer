# DiContainer

## What it does (plain language)

DiContainer is the dependency-injection primitive. You register interface
types against implementations with a declared lifetime (singleton, scoped,
transient), and the container hands back correctly-lived instances at
resolve time. Scopes are opened with `create_scope()` and own the instances
they construct — when the scope ends, their `close()` methods run. The
container detects dependency cycles, rejects scoped-into-singleton leaks,
and refuses silent re-registration.

## Glossary (read this first)

- **Interface (iface)** — a Python class (usually a Protocol or abstract
  base) that declares *what* a dependency does. The key the container uses
  to look up a concrete implementation.
- **Implementation (impl)** — the concrete class or factory function that
  actually produces an instance of the interface.
- **Resolve** — ask the container for an instance of an interface; the
  container returns either a cached instance or a freshly constructed one,
  depending on the scope.
- **Scope** — the lifetime label attached at registration time. Three values:
  - `"singleton"` — one instance per process; the same object every resolve.
  - `"scoped"` — one instance per `create_scope()` block (typically a web
    request); fresh in a sibling scope.
  - `"transient"` — a brand-new instance on every resolve.
- **Dispose** — release resources (call `close()`) on instances owned by a
  scope. Happens automatically when the `with container.create_scope()`
  block exits.
- **Cycle** — two dependencies that need each other to build (A constructs
  B which needs A); the container detects this and raises rather than
  looping forever.
- **Leak (scope leak)** — a longer-lived owner accidentally capturing a
  shorter-lived dependency (singleton grabbing a scoped). The container
  rejects this at resolve-time to stop use-after-dispose bugs.

## Minimal example (from zero)

```python
from DiContainer import InMemoryDiContainer

class Clock:          # interface
    def now(self) -> int: ...

class SystemClock(Clock):  # implementation
    def now(self) -> int:
        import time
        return int(time.time())

container = InMemoryDiContainer()
container.register(Clock, SystemClock, scope="singleton")

with container.create_scope() as scope:
    clock = scope.resolve(Clock)
    print(clock.now())
# On exit, any scoped instances are auto-disposed.
```

## Purpose

Registry that resolves a typed request for a dependency into a constructed
instance obeying the declared lifetime scope.

## When to use and when NOT to use

- USE: when your app has more than one composition root (tests + prod,
  worker + API), or any time wiring depends on runtime configuration.
- USE: whenever a repository, clock, client, or session's lifetime is
  different from its caller (request-scoped repo, per-app singleton config).
- DO NOT USE: inside tight hot loops where the allocation cost of scopes
  matters and the graph is fully static — import the concrete class.
- DO NOT USE: as a global service locator — pass the container through the
  composition root, not implicitly via module imports.

## API surface

The catalog `api_signature` in `DiContainer.contract.json` is authoritative.

- `register(iface, impl, *, scope)` — register a provider. `impl` may be the
  concrete class or any zero-arg callable returning an instance.
- `resolve(iface)` — return a correctly-scoped instance.
- `create_scope()` — open a child scope; use as a context manager so disposal
  is guaranteed.

Extension beyond the catalog Protocol:

- `register(..., name=...)` — keyed registration when more than one impl of
  the same iface must coexist (DI-INV-05).
- `register(..., allow_override=True)` — explicit re-registration escape
  hatch (DI-INV-04).
- `register_instance(iface, instance)` — wire an externally-owned instance
  that the container MUST NOT dispose (DI-INV-03).

## Invariants

| ID | Rule |
|---|---|
| DI_INV_01 | MUST resolve without re-entering a partially-constructed node; cycles SHALL raise. |
| DI_INV_02 | NEVER returns an instance whose declared scope outlives the resolving scope; scoped CANNOT leak into singleton. |
| DI_INV_03 | ALWAYS disposes instances it owns when the owning scope ends; callers MUST NOT dispose externally-created instances. |
| DI_INV_04 | MUST NOT silently replace a prior registration; re-registration SHALL be explicit via `allow_override=True`. |
| DI_INV_05 | `register()` keys on the interface type; keyed registrations MUST use a non-empty `name` discriminator. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the binding.

## Lifetime semantics (state-transition table)

| Scope      | Cache location     | Resolve returns          |
|------------|--------------------|--------------------------|
| singleton  | root container     | same instance forever     |
| scoped     | current scope      | same instance within the scope, fresh in sibling scopes |
| transient  | never              | fresh instance every resolve |

Resolving a `scoped` registration from the root is FORBIDDEN (DI-INV-02).
Resolving from a disposed scope is FORBIDDEN (DI-INV-03).

## Thread and async safety

- Registration is guarded by an RLock shared by root and all child scopes.
- Singleton construction is idempotent under concurrent resolve — the first
  resolver wins, subsequent callers observe the cached instance.
- Scoped caches are per-scope, protected by their own RLock. A single scope
  MUST NOT be resolved from multiple async tasks unless the caller
  externally synchronises; instance construction runs inside the lock.
- The resolve stack used for cycle detection is `threading.local`, so
  independent threads NEVER see each other's partial resolutions.

## Operational characteristics (for SRE)

- Root container keeps singleton instances for the process lifetime; callers
  should dispose it at shutdown (explicit `dispose()` on root currently
  drops only scope-owned instances — singletons live for the process).
- Scoped disposal runs close() on each instance; failures are swallowed to
  guarantee the rest of the scope drains.
- Metrics (self-observability): `di.resolves` (counter, `scope` + `cached`
  labels), `di.scope.instance_count` (histogram), `di.resolve.duration`
  (histogram).
- A sudden rise in `di.resolves{cached="false"}` on singletons indicates
  cache eviction or a re-registration event.

## Security considerations

- The container stores factory references, not serialised impls. Registering
  a factory that captures secrets holds those secrets for the process
  lifetime — scope disposal only nulls references, not memory pages.
- `register_instance` grants the caller ownership of disposal; auditors MUST
  confirm that externally-owned resources are closed on shutdown.
- `allow_override=True` is the ONLY path to re-register; reviewers should
  flag any production code that passes it outside a bootstrap or test
  harness.

## Provenance

- Source agent: Agent #1 FRAMEWORKS
  (`docs/research/outputs/AGENT_1_FRAMEWORKS.json`).
- Primary sources:
  - ASP.NET Core 8.0 Fundamentals — Dependency Injection
    (IServiceCollection / IServiceProvider, `Service registration methods`).
  - Spring Framework Reference — Core Container (BeanFactory /
    ApplicationContext scopes).
  - Quarkus 3.x Guide — Contexts and Dependency Injection (`jakarta.inject`).

## Alternatives considered and rejected

- Hand-wired constructors per entry point — loses uniform test substitution
  and forces every composition root to reinvent wiring.
- Service-locator singleton — hides dependencies and defeats unit tests.
- Module-import side effects — couples wiring to import order and produces
  surprise failures on refactor.

## Extension contract

Downstream code registers services via `register()` or a provider decorator.
To plug a non-default container, implement the Protocol and bind an adapter
that forwards `resolve()` / `register()` / `create_scope()` without changing
lifetime semantics. Adapters MUST preserve DI-INV-01..05.

## Schema of `DiContainer.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog. Fields: `name`, `namespace`, `purpose`, `api_signature`,
`invariants[]`, `extension_contract`, `consumption_example`, `sources[]`,
`why_essential`, `alternatives_considered[]`, `maturity`.

## Usage

```python
def build_container(c: InMemoryDiContainer) -> None:
    c.register(UserRepo, SqlUserRepo, scope="singleton")
    c.register(RequestClock, SystemClock, scope="scoped")

def handle(container: InMemoryDiContainer) -> None:
    with container.create_scope() as scope:
        repo = scope.resolve(UserRepo)
        repo.save(...)
```

## Compose with:

- **Scoped per-request wiring** → `LifetimeScope` + `UnitOfWork`
  Request-scoped UoW and repositories are resolved once per request and disposed at pipeline exit — handlers never 'new' a transaction.

- **Typed configuration graph** → `ConfigBinding` + `LifetimeScope`
  Config records are singleton bindings; their consumers are request-scoped — hot-reload rewires consumers without rebooting singletons.

- **Testable seams** → `Repository` + `OutboundBinding`
  Every integration is a registered interface; tests swap in fakes without touching production wiring — integration seams are mockable by construction.
