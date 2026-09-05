# Maintenance Skills per Crate — HuGR Arsenal

> **Purpose**: Comprehensive operational guides for each domain/crate in the HuGR Arsenal. These are living documents — update them as you learn.

> **Audience**: Engineers maintaining, extending, or debugging the crates. Written by practitioners, for practitioners.

> **Philosophy**: *Every crate deserves a manual written by someone who has felt the pain of operating it.*

---

## Domain Index

| Domain | Crates | Status | Last Updated |
|--------|--------|--------|--------------|
| [Auth](auth.md) | 9 crates | ✅ Complete | 2026-09-04 |
| [Billing](billing.md) | 1 crate | ✅ Complete | 2026-09-04 |
| [Cache](cache.md) | 3 crates | ✅ Complete | 2026-09-04 |
| [Compliance](compliance.md) | 1 crate | ✅ Complete | 2026-09-04 |
| [Data](data.md) | 19 crates | ✅ Complete | 2026-09-04 |
| [Events](events.md) | 13 crates | ✅ Complete | 2026-09-04 |
| [Jobs](jobs.md) | 3 crates | ✅ Complete | 2026-09-04 |
| [Observability](observability.md) | 15 crates | ✅ Complete | 2026-09-04 |
| [Security](security.md) | 7 crates | ✅ Complete | 2026-09-04 |
| [Resiliency](resiliency.md) | 18 crates | ✅ Complete | 2026-09-04 |
| [Security](security.md) | 7 crates | ✅ Complete | 2026-09-04 |
| [Flags](flags.md) | 1 crate | ✅ Complete | 2026-09-04 |
| [LLM](llm.md) | 1 crate | ✅ Complete | 2026-09-04 |
| [Cost](cost.md) | 1 crate | ✅ Complete | 2026-09-04 |
| [Policy](policy.md) | 1 crate | ✅ Complete | 2026-09-04 |

---

## Universal Principles (Apply to ALL Crates)

### 1. Contract-First Evolution
```bash
# Before ANY change:
# 1. Read the crate's CONTRACT.md (or .contract.json if exists)
# 2. Run: python -m engine.audit.contract_check --crate <crate-name>
# 3. If contract check passes → proceed. If not → STOP.
```

### 2. Determinism is Non-Negotiable
```python
# Every crate must satisfy:
# 1. Deterministic output for same inputs
# 2. No hidden global state
# 3. Explicit dependency injection
# 4. Pure functions where possible
```

### 3. Observability by Default
```python
# Every crate MUST emit:
# - Structured logs (JSON, with correlation_id)
# - Metrics (RED: Rate, Errors, Duration)
# - Traces (OpenTelemetry spans)
# - Health checks (liveness + readiness)
```

### 4. Security by Default
```python
# Every crate MUST:
# - Validate all inputs at boundaries
# - Use typed settings (pydantic-settings)
# - Fail fast on config errors
# - Never log secrets (use `SecretStr`)
# - Encrypt at rest, TLS in transit
```

---

## How to Use This Guide

1. **Read the domain-specific guide** for your crate
2. **Follow the checklists** before making changes
6. **Update this guide** when you discover something new
7. **Share learnings** — PR the maintenance skill when you learn something hard

---

## Quick Reference: Crate → Maintenance Skill Mapping

| Crate | Maintenance Skill |
|-------|-------------------|
| `AuthorizationCodeFlow` | [auth.md](auth.md#authorizationcodeflow) |
| `CurrentPrincipal` | [auth.md](auth.md#currentprincipal) |
| `RequestGuard` | [auth.md](auth.md#requestguard) |
| `SessionStore` | [auth.md](auth.md#sessionstore) |
| `TokenIntrospector` | [auth.md](auth.md#tokenintrospector) |
| `TotpVerifier` | [auth.md](auth.md#totpverifier) |
| `WebAuthnAuthenticator` | [auth.md](auth.md#webauthnauthenticator) |
| `FeatureFlagCache` | [auth.md](auth.md#featureflagcache) |
| `Billing` | [billing.md](billing.md) |
| `KeyValueBucket` | [cache.md](cache.md#keyvaluebucket) |
| `DistributedLock` | [cache.md](cache.md#distributedlock) |
| `SessionCache` | [cache.md](cache.md#sessioncache) |
| `Aggregate` | [data.md](data.md#aggregate) |
| `AntiCorruptionLayer` | [data.md](data.md#anticorruptionlayer) |
| `BoundedContext` | [data.md](data.md#boundedcontext) |
| `ChangeDataCapture` | [data.md](data.md#changedatacapture) |
| `ConfigBinding` | [data.md](data.md#configbinding) |
| `DataMapper` | [data.md](data.md#datamapper) |
| `DiContainer` | [data.md](data.md#dicontainer) |
| `IdentityMap` | [data.md](data.md#identitymap) |
| `LegalHold` | [data.md](data.md#legalhold) |
| `LifetimeScope` | [data.md](data.md#lifetimescope) |
| `MaterializedView` | [data.md](data.md#materializedview) |
| `OptimisticConcurrency` | [data.md](data.md#optimisticconcurrency) |
| `PiiClassification` | [data.md](data.md#piiclassification) |
| `Repository` | [data.md](data.md#repository) |
| `ShardedCounter` | [data.md](data.md#shardedcounter) |
| `Specification` | [data.md](data.md#specification) |
| `TransactionalBatch` | [data.md](data.md#transactionalbatch) |
| `UnitOfWork` | [data.md](data.md#unitofwork) |
| `ValueObject` | [data.md](data.md#valueobject) |
| `CausalReorderBuffer` | [events.md](events.md#causalreorderbuffer) |
| `DeadLetterRoute` | [events.md](events.md#deadletterroute) |
| `DomainEvent` | [events.md](events.md#domainevent) |
| `EventEnvelope` | [events.md](events.md#eventenvelope) |
| `EventSourcedStore` | [events.md](events.md#eventsourcedstore) |
| `EventStream` | [events.md](events.md#eventstream) |
| `IdempotentConsumer` | [events.md](events.md#idempotentconsumer) |
| `InboxDeduplicator` | [events.md](events.md#inboxdeduplicator) |
| `PubSub` | [events.md](events.md#pubsub) |
| `SagaOrchestrator` | [events.md](events.md#sagaorchestrator) |
| `StreamSubject` | [events.md](events.md#streamsubject) |
| `TopicBus` | [events.md](events.md#topicbus) |
| `TransactionalOutbox` | [events.md](events.md#transactionaloutbox) |
| `ActivityCall` | [jobs.md](jobs.md#activitycall) |
| `DurableTimer` | [jobs.md](jobs.md#durabletimer) |
| `WorkflowRun` | [jobs.md](jobs.md#workflowrun) |
| `AccessLog` | [observability.md](observability.md#accesslog) |
| `CardinalityGuard` | [observability.md](observability.md#cardinalityguard) |
| `CorrelationContext` | [observability.md](observability.md#correlationcontext) |
| `CorrelationId` | [observability.md](observability.md#correlationid) |
| `ErrorSink` | [observability.md](observability.md#errorsink) |
| `EventBus` | [observability.md](observability.md#eventbus) |
| `HealthProbe` | [observability.md](observability.md#healthprobe) |
| `HistogramBuckets` | [observability.md](observability.md#histogrambuckets) |
| `LifecycleHook` | [observability.md](observability.md#lifecyclehook) |
| `LlmTrace` | [observability.md](observability.md#llmtrace) |
| `MetricMeter` | [observability.md](observability.md#metricmeter) |
| `ResourceDescriptor` | [observability.md](observability.md#resourcedescriptor) |
| `SamplingPolicy` | [observability.md](observability.md#samplingpolicy) |
| `SemanticAttributes` | [observability.md](observability.md#semanticattributes) |
| `StructuredLogger` | [observability.md](observability.md#structuredlogger) |
| `TelemetryExporter` | [observability.md](observability.md#telemetryexporter) |
| `Tracer` | [observability.md](observability.md#tracer) |
| `ContentSecurityPolicy` | [security.md](security.md#contentsecuritypolicy) |
| `CryptoEnvelope` | [security.md](security.md#cryptoenvelope) |
| `CsrfGuard` | [security.md](security.md#csrfguard) |
| `InputValidator` | [security.md](security.md#inputvalidator) |
| `OutputEncoder` | [security.md](security.md#outputencoder) |
| `PasswordHasher` | [security.md](security.md#passwordhasher) |
| `SecretsVault` | [security.md](security.md#secretsvault) |
| `SignatureVerifier` | [security.md](security.md#signatureverifier) |
| `ContentSecurityPolicy` | [resiliency.md](resiliency.md#contentsecuritypolicy) |
| `CryptoEnvelope` | [resiliency.md](resiliency.md#cryptoenvelope) |
| `CsrfGuard` | [resiliency.md](resiliency.md#csrfguard) |
| `InputValidator` | [resiliency.md](resiliency.md#inputvalidator) |
| `OutputEncoder` | [resiliency.md](resiliency.md#outputencoder) |
| `PasswordHasher` | [resiliency.md](resiliency.md#passwordhasher) |
| `SecretsVault` | [resiliency.md](resiliency.md#secretsvault) |
| `SignatureVerifier` | [resiliency.md](resiliency.md#signatureverifier) |
| `FeatureFlagCache` | [flags.md](flags.md) |
| `LlmTrace` | [llm.md](llm.md) |
| `CostTracker` | [cost.md](cost.md) |
| `PolicyEngine` | [policy.md](policy.md) |

---

## Contributing to Maintenance Skills

```bash
# 1. Make your change
# 2. Update the relevant .md file
# 3. Run: python -m engine.audit.contract_check --quiet
# 4. If green → PR
# 5. If red → fix contract, then PR
```

---

*Last updated: 2026-09-04 | Maintained with ❤️ by the HuGR team*