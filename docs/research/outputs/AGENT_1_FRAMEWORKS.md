# Agent 1 — FRAMEWORKS

**Mission.** Extract dependency-injection, request-context, config-binding, lifecycle, and cross-cutting chain primitives from six mature backend frameworks (Spring Boot 3.x, Nest.js 10, ASP.NET Core 8.0, Ruby on Rails 7, Phoenix 1.7 / Plug, Quarkus 3.x) and anchor the venous-system spec in 20+ years of production-proven design.

**Namespaces owned.** `auth`, `data`, `api`, `obs`, `flags`.

**Delivery.** 14 primitives, 37 unique sources cited, 8 cross-cutting insights, 5 gaps observed against SKILL-001.

---

## Summary of primitives

| # | Name | Namespace | Maturity |
|---|------|-----------|----------|
| 1 | `DiContainer` | data | battle_tested |
| 2 | `LifetimeScope` | data | battle_tested |
| 3 | `RequestContext` | api | battle_tested |
| 4 | `CurrentPrincipal` | auth | battle_tested |
| 5 | `CorrelationId` | obs | battle_tested |
| 6 | `MiddlewarePipeline` | api | battle_tested |
| 7 | `RequestGuard` | auth | battle_tested |
| 8 | `ValueTransform` | api | battle_tested |
| 9 | `ConfigBinding` | data | battle_tested |
| 10 | `HealthProbe` | obs | battle_tested |
| 11 | `LifecycleHook` | obs | battle_tested |
| 12 | `FeatureToggle` | flags | battle_tested |
| 13 | `RouterPipeline` | api | battle_tested |
| 14 | `EventBus` | obs | battle_tested |

Distribution across owned namespaces: `data` 3, `api` 4, `auth` 2, `obs` 4, `flags` 1.

---

## Primitive narratives

### 1. `DiContainer` — data
The typed registry that resolves a request for a dependency into a constructed instance obeying its declared lifetime scope. Spring `ApplicationContext`, Nest.js Injector, ASP.NET `IServiceProvider`, Quarkus ArC, and the Phoenix supervision tree all implement the same contract: register → resolve → dispose. Key rules: cycle detection on resolve, no leaking a scoped instance into a singleton graph, ownership-based disposal, and explicit re-registration.

### 2. `LifetimeScope` — data
The three lifetimes that all six frameworks converge on, renamed uniformly: SINGLETON (process), SCOPED (request), TRANSIENT (per-call). Cross-framework mapping: ASP.NET `AddSingleton`/`AddScoped`/`AddTransient`, Spring `singleton`/`request`/`prototype`, Nest.js `Scope.DEFAULT`/`Scope.REQUEST`/`Scope.TRANSIENT`, Quarkus `@ApplicationScoped`/`@RequestScoped`/`@Dependent`. Captive-dependency (SINGLETON pulling SCOPED) is the canonical bug the primitive's invariants forbid.

### 3. `RequestContext` — api
The per-request bag: `HttpContext` (ASP.NET), `Plug.Conn` (Phoenix/Plug), `ActiveSupport::CurrentAttributes` (Rails 7), `ExecutionContext` (Nest.js). Carries identity, headers, correlation id, and free-form assigns without thread-locals. `halt()` short-circuits the pipeline; `put()` is the single mutation surface.

### 4. `CurrentPrincipal` — auth
Read-only identity view: subject id, tenant, frozen role set, claims, and an `is_anonymous` flag that is mutually exclusive with non-empty claims. Immutable for the life of a request; constructed by the auth middleware/guard and consumed by every downstream authorization step. Backed by ASP.NET `HttpContext.User` (`ClaimsPrincipal`), Rails 7 `Current.user`, and the object Nest.js guards read off `ExecutionContext`.

### 5. `CorrelationId` — obs
Opaque string propagated on every log line, metric exemplar, and outbound request. Honours upstream `X-Request-Id`/`traceparent`; generates a cryptographically-random 16+ byte id otherwise. ASP.NET `HttpContext.TraceIdentifier`, Plug `Plug.RequestId`, and Rails 7's `attribute :request_id, default: -> { SecureRandom.uuid }` pattern.

### 6. `MiddlewarePipeline` — api
Ordered chain of `(ctx, call_next)` callables: ASP.NET `RequestDelegate`, Plug `call/2`, Nest.js `NestInterceptor.intercept`. Registration order = execution order, frozen after first run, halts short-circuit, errors never skip error filters.

### 7. `RequestGuard` — auth
Predicate before handler execution: Nest.js `CanActivate.canActivate(context)`. Returns True/False; False blocks the request with 401/403. Composes with AND. Guards run after authentication middleware (principal already bound) and before interceptors/pipes.

### 8. `ValueTransform` — api
Strongly-typed parse/validate step lifted from Nest.js `PipeTransform.transform(value, metadata: ArgumentMetadata)` where `metadata.type ∈ {'body','query','param','custom'}` plus `metatype` and `data`. ASP.NET `ModelBinder` is the equivalent. Pure, order-sensitive composition, raises on invalid.

### 9. `ConfigBinding` — data
Binds a prefixed config slice to a frozen typed record. Spring `@ConfigurationProperties` with `ConstructorBinding` and `@DefaultValue`; ASP.NET `IOptions<T>` with `Configure<T>(section)`. Fails loudly on missing required keys, rejects unknown keys under the prefix, hands out immutable records.

### 10. `HealthProbe` — obs
Named probe reporting UP/DOWN/DEGRADED with non-secret detail. Spring `HealthIndicator.health()` returning `Health.up()`/`down()`/`status(...)`; ASP.NET `IHealthCheck.CheckHealthAsync`. Registry-based aggregation with `StatusAggregator`; readiness requires every required probe UP; optional probes cannot force readiness off.

### 11. `LifecycleHook` — obs
STARTING/READY/STOPPING/STOPPED phases as a closed enum. Spring `ApplicationStartingEvent`/`ApplicationReadyEvent`/`ApplicationFailedEvent`, Quarkus `io.quarkus.runtime.StartupEvent`/`ShutdownEvent` with `@Observes`, ASP.NET `IHostApplicationLifetime` (`ApplicationStarted`/`ApplicationStopping`/`ApplicationStopped`). LIFO shutdown, bounded timeouts, READY gates traffic.

### 12. `FeatureToggle` — flags
Named predicate evaluated against a `ToggleContext` (principal, tenant, environment). Togglz enum `Feature.isActive()`, Spring `@ConditionalOnProperty(name=..., havingValue=...)`, Spring `@Profile('production')`. Off-by-default when store unreachable, pure evaluation, mandatory audit event per call, two-step deprecation.

### 13. `RouterPipeline` — api
Named bundle of middleware attached to a group of routes. Phoenix `pipeline/2` + `pipe_through/1`; Plug `Plug.Builder` for composed pipelines. Declared order is executed order, pipelines are sealed at boot, route-to-pipeline attachment is declarative.

### 14. `EventBus` — obs
In-process pub/sub for named events with structured payloads. Rails `ActiveSupport::Notifications.subscribe/instrument` (payload carries `duration`, `allocations`, etc.), Spring `@EventListener` on `ApplicationReadyEvent` and friends. Dotted namespaces, pattern subscriptions, idempotent unsubscribe, payload immutability.

---

## Cross-cutting insights

1. All six frameworks converge on three lifetimes (process, request, per-call); names differ (Spring `request` vs ASP.NET `Scoped` vs Nest.js `REQUEST`) but semantics are identical and portable.
2. Every framework exposes a per-request state carrier (`HttpContext`, `Plug.Conn`, `CurrentAttributes`, `ExecutionContext`) — identity, correlation id, and tenant are attached here, never via thread-local globals.
3. Configuration binding is a startup concern (Spring `@ConfigurationProperties`, ASP.NET `IOptions<T>`): validation happens once, results are immutable, unknown keys fail fast rather than at first read.
4. Middleware/Plug/Interceptor chains are the same pattern under different names: ordered `(ctx, call_next)` callables with short-circuit via `halt()`/non-call, making ordering a first-class contract.
5. Lifecycle hooks have stabilized into STARTING/READY/STOPPING phases (Spring `ApplicationReadyEvent`, Quarkus `StartupEvent`/`ShutdownEvent`, ASP.NET `IHostApplicationLifetime`); orchestrators rely on the READY signal to gate traffic.
6. Health endpoints are composite: a registry of named probes aggregated by a `StatusAggregator`; readiness ≠ liveness and the two must be reported separately.
7. Guard-vs-Pipe-vs-Interceptor ordering (Nest.js) encodes a production truth: authorize before transforming, transform before handling, observe around all of them.
8. Feature flags and Spring `@ConditionalOnProperty`/`@Profile` share one mental model: a named predicate evaluated against context controls whether a wiring or code path is live.

---

## Gaps against SKILL-001

1. SKILL-001 lacks a `LifetimeScope` enum; lifetimes are currently implicit in tool bodies rather than declared at registration.
2. `CorrelationId` propagation across outbound HTTP/queue calls is not a declared primitive; each integration tool handles headers its own way.
3. No unified `HealthProbe` registry aggregating `/readyz` and `/livez` across tools; each generator adds its own path with its own shape.
4. `LifecycleHook` phases (STARTING/READY/STOPPING) are not a first-class primitive; startup wiring is scattered across generators.
5. `FeatureToggle` as a context-aware predicate is absent; the current flag story is environment-variable checks without per-tenant evaluation.

---

## Sources cited (37 unique)

Primary frameworks: Spring Boot 3.x Reference and Actuator; Spring Framework Reference (beans, profiles, conditionals); Nest.js 10 documentation (injection scopes, interceptors, guards, pipes); ASP.NET Core 8.0 Fundamentals (DI, lifetimes, HttpContext, options, middleware, authorization policies, health checks, `IHostApplicationLifetime`, model binding); Ruby on Rails 7 (`ActiveSupport::CurrentAttributes`, `ActiveSupport::Notifications`); Plug 1.x (specification, `Plug.Conn`, `Plug.Builder`, `Plug.RequestId`) and Phoenix 1.7 Router; Quarkus 3.x CDI and Lifecycle guides; Togglz 4.x.

No single source exceeds 3% of total citations; diversity requirement (≤70%) is satisfied by a wide margin.

---

## Self-check

```
$ skills/SKILL-001-fastapi-production/.venv/bin/python \
    docs/research/contracts/check_deliverable.py \
    --agent 1 --deliverable docs/research/outputs/AGENT_1_FRAMEWORKS.json
✓ DELIVERABLE VALID
  Agent 1 (FRAMEWORKS)
  Primitives: 14 (min 12)
  Unique sources: 37 (min 6)
  Insights: 8
  Gaps observed: 5
```

Exit code: 0.
