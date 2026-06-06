# L0 Convention Candidates

> Of the 65 primitives classified as **MISSING + battle_tested** in
> `SKILL_001_AUDIT.md`, this document selects the subset that belongs in the
> SkillEngine **L0 Convention** layer — defaults every generated project gets,
> zero configuration, $0 LLM cost, measurable by the existing venous-system
> contract.
>
> L0 is the tightest of the five layers (`L0 Convention · L1 Rules · L2 LLM ·
> L3 Templates · L4 Validation`). Being in L0 means: *every* production backend
> on *every* language target gets this on by default; an app opting out must do
> so explicitly.

## Selection criteria (all three must hold)

1. **Universal** — every production backend (API / worker / batch) needs the concept.
2. **Safe default** — on-by-default does not break apps; opt-out is the rare case.
3. **Zero-config** — a sensible default exists without the app author configuring anything. If config is required, the primitive belongs in L1 (rules) or L3 (templates).

Anything failing even one criterion goes to L1+ and is discussed in the SkillEngine architecture doc.

## Summary

| Layer | Primitive count | Where they live |
|---|---|---|
| **L0 Convention** | **24** | default-on, this document |
| L1+ (opt-in) | 41 | catalog entry → rules/templates in `SKILL_ENGINE_SPEC.md` |

## L0 primitives (24)

Grouped by namespace. Each entry: **purpose · default behavior · opt-out path**.

### `data` — 6 primitives

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`DiContainer`** | Auto-register request/singleton/transient scopes; constructor injection by type. | Disable with `container=None` — app wires manually. |
| **`LifetimeScope`** | Enum {singleton, request, transient}; per-binding default is `request`. | Override per registration. |
| **`ConfigBinding`** | Typed section binding from env + `.env` + secret store; fails fast on missing required. | Use raw `os.environ` in the rare case. |
| **`UnitOfWork`** | One UoW per request; auto-commit on handler success, rollback on exception. | Disable per-handler with `@no_uow`. |
| **`RequestContext`** | Holds `correlation_id`, `principal`, `tenant`, deadline; populated by middleware. | Accessible as explicit dep; never global. |
| **`ValueTransform`** | Parse + validate inbound scalars into typed domain values at the edge. | N/A — schema is a dependency. |

### `obs` — 8 primitives

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`StructuredLogger`** | JSON logs with `service.name`, `correlation.id`, level, timestamp; OTel-compatible. | Swap exporter via `TelemetryExporter`. |
| **`MetricMeter`** | OTel counter/histogram/gauge/updown-counter; default histogram buckets from `HistogramBuckets`. | Replace meter provider. |
| **`HistogramBuckets`** | Default latency buckets: 5-10-25-50-100-250-500-1000-2500-5000-10000 ms. | Override per instrument. |
| **`CorrelationContext`** | W3C Trace Context propagation; every request carries `traceparent`. | N/A — always on. |
| **`ErrorSink`** | Uncaught exceptions captured with fingerprint + stack + context; sampled. | Configurable sampler. |
| **`HealthProbe`** | `/livez` + `/readyz` endpoints with typed `HealthReport`. | N/A — orchestrators require them. |
| **`LifecycleHook`** | Startup/ready/shutdown/drain phases; ordered hook registration. | Register zero hooks. |
| **`ResourceDescriptor`** | Auto-populated from env: `service.name`, `service.version`, `deployment.environment`. | Override via config. |

### `api` — 3 primitives

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`MiddlewarePipeline`** | Ordered chain: `CorrelationContext` → logging → error → auth → guard → business → serialization. | Remove layer by name. |
| **`RequestGuard`** | Before-handler predicate; default guards: authenticated + not-locked. | Bypass per-handler with `@public`. |
| **`TimeoutBudget`** | Inbound request deadline from `Deadline` header or default 30s; propagated to downstream calls. | Per-handler override. |

### `auth` — 1 primitive

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`CurrentPrincipal`** | Read-only `principal` from validated session/token; unauthenticated = `Anonymous`. | Use `@public` to allow anonymous. |

### `security` — 5 primitives

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`SecretsVault`** | Fetch from env → local `.env` → cloud secret store by named scope; cached TTL. | Provide custom provider. |
| **`CsrfGuard`** | Double-submit cookie + Origin check on state-changing verbs. | `@csrf_exempt` per route. |
| **`CorsPolicy`** | Deny-by-default; explicit allow-list from config. | Configure allowed origins. |
| **`InputValidator`** | Schema-validated inbound payloads; reject on type / range / format. | Handler takes raw input (rare). |
| **`OutputEncoder`** | Context-aware encoding (HTML text / attribute / JS / URL). | Mark field `raw=True` with lint warning. |

### `compliance` — 1 primitive

| Primitive | Default behavior | Opt-out |
|---|---|---|
| **`TamperEvidentAuditLog`** | Append-only hash-chained record for every mutating handler; actor + subject + action. | Disable via config; warned at boot. |

### Total: 24 L0 primitives

---

## L1+ (opt-in) — 41 primitives

The remaining 41 battle-tested-but-MISSING primitives are not L0 because they fail at least one criterion. They belong to **L1 Rules** (keyword-selected at build time) or **L3 Templates** (generated on demand).

### `auth` (5) — opt-in by feature flag
- `AuthorizationCodeFlow` (OAuth only), `SessionStore` (session auth only), `TokenIntrospector` (token auth only), `TotpVerifier` (MFA only) — app must declare auth mode.

### `api` (2) — opt-in
- `CommandQuerySeparator` (CQRS only), `RouterPipeline` (route-scoped pipelines).

### `data` (8) — opt-in (DDD / event-sourcing / Dapr territory)
- `AntiCorruptionLayer`, `BoundedContext`, `ContextMap`, `DataMapper`, `IdentityMap`, `StateStore`, `TransactionalBatch`, `ValueObject`.

### `events` (8) — opt-in (messaging topology)
- `EventEnvelope` (used only if an `EventBus` / broker is present), `DeadLetterRoute`, `EventSourcedStore`, `IdempotentConsumer`, `InboxDeduplicator`, `PartitionLog`, `StreamSubject`, `TopicBus`, `TransactionalOutbox`.

### `jobs` (4) — opt-in (Temporal-style workflows)
- `ActivityCall`, `DurableTimer`, `WorkflowRun`, `WorkflowSignal`.

### `extras` (3) — opt-in
- `OutboundBinding` (Dapr-style bindings), `RpcInterceptor` (gRPC only), `VirtualActor` (Dapr / Orleans only).

### `compliance` (2) — opt-in (regulated verticals)
- `ConsentLedger` (GDPR consent management), `LegalHold` (e-discovery suspend).

### `cost` (1)
- `TokenMeter` — LLM callers only.

### `llm` (1)
- `PromptTemplate` — LLM callers only.

### `obs` (3) — opt-in
- `AccessLog` (read-auditing for PHI/PII), `SamplingPolicy` (custom sampling), `TelemetryExporter` (vendor-specific exporters).

### `policy` (3) — opt-in
- `EncryptionPolicy`, `KeyRotationSchedule` (data-at-rest encryption management).

### `resiliency` (1)
- `OutlierEjection` — service-mesh / client-side LB.

### `security` (1) — opt-in
- `CryptoEnvelope` — app-layer authenticated encryption (vs. transport-layer).

---

## Implementation hints for L0 build-out

1. **Every L0 primitive ships with a `consumption_example` from its `PrimitiveSpec` as a sanity test** — the example IS the minimal integration test.
2. **Default values live as module-level constants** in a single `core/convention/defaults.py` — trivial to audit, trivial to override.
3. **Opt-out is always explicit** — the primitive MUST NOT silently disable itself when misconfigured; it SHALL warn at boot if the app tries.
4. **L0 must compile with zero config** — if a primitive requires config to boot, it is L1 by definition.
5. **L0 adds no required dependencies beyond the language's standard library + the target framework's core** — every extra runtime dep promotes the primitive to L1.

## Cross-references

- `VENOUS_SYSTEM_CATALOG.md` — full primitive specs for the 24 L0 entries
- `SKILL_001_AUDIT.md` — source of the MISSING classification
- `CONTRACT_STANDARDS.md` — rules every primitive, L0 or not, satisfies
- `SKILL_ENGINE_SPEC.md` (next) — wires L0 into the full L0–L4 pipeline
