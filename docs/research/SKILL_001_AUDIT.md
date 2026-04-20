# SKILL-001 Audit — Venous System Presence

> Automated audit comparing the 113 venous-system primitives in `VENOUS_SYSTEM_CATALOG.md` against the current SKILL-001 FastAPI Production skill. Classifies each primitive as PRESENT / PARTIAL / MISSING by keyword search (PascalCase + snake_case) across `.py` and `.md` files.

## Summary

| Status | Count | % | Meaning |
|---|---|---|---|
| PRESENT | 17 | 15% | ≥3 file matches — likely covered |
| PARTIAL | 10 | 9% | 1-2 file matches — concept touched, coverage likely thin |
| MISSING | 86 | 76% | zero matches — venous-system primitive absent from SKILL-001 |

**Total audited: 113 primitives.**

## Heuristic limits

- Keyword-only search — semantic equivalents are not detected (e.g. `Aggregate` concept may live in SKILL-001 as `Model` boundary without using the term).
- PRESENT does not mean compliant with the venous-system contract — only that the SKILL-001 surface uses the name. Reconciliation with the full `PrimitiveSpec` contract is a separate pass.
- MISSING means the primitive name (Pascal + snake) does not appear literally in SKILL-001 — it does NOT mean the concept is absent; it means the current surface does not expose it under that name.

## PRESENT (17)

### `api` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **RequestContext** | 4 | 3 | #1 | `battle_tested` |

### `data` (4)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **Aggregate** | 6 | 26 | #3 | `battle_tested` |
| **MaterializedView** | 0 | 3 | #3 | `battle_tested` |
| **Repository** | 0 | 6 | #3 | `battle_tested` |
| **Specification** | 5 | 11 | #3 | `battle_tested` |

### `events` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **DomainEvent** | 4 | 1 | #3 | `battle_tested` |

### `flags` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **FeatureToggle** | 4 | 16 | #1 | `battle_tested` |

### `llm` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **ModelRegistry** | 8 | 17 | #8 | `battle_tested` |

### `obs` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **CorrelationId** | 0 | 19 | #1 | `battle_tested` |
| **Tracer** | 9 | 10 | #7 | `battle_tested` |

### `resiliency` (6)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **Bulkhead** | 12 | 19 | #4 | `battle_tested` |
| **CircuitBreaker** | 5 | 55 | #4 | `battle_tested` |
| **FallbackChain** | 1 | 2 | #4 | `battle_tested` |
| **LoadShedder** | 7 | 7 | #4 | `battle_tested` |
| **RateLimiter** | 7 | 5 | #4, #5 | `battle_tested` |
| **RetryPolicy** | 1 | 3 | #4 | `battle_tested` |

### `security` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **PasswordHasher** | 5 | 5 | #5 | `battle_tested` |

## PARTIAL (10)

### `compliance` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **AuditEvent** | 1 | 0 | #7 | `battle_tested` |
| **RetentionPolicy** | 1 | 0 | #6 | `battle_tested` |

### `events` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **EventStream** | 0 | 2 | #3 | `battle_tested` |
| **SagaOrchestrator** | 0 | 1 | #3 | `battle_tested` |

### `llm` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **ModelRouter** | 0 | 1 | #8 | `emerging` |
| **ResponseCache** | 0 | 2 | #8 | `emerging` |

### `obs` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **EventBus** | 0 | 2 | #1 | `battle_tested` |

### `resiliency` (1)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **ChaosInjector** | 0 | 2 | #4 | `emerging` |

### `security` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **ContentSecurityPolicy** | 0 | 1 | #5 | `battle_tested` |
| **SignatureVerifier** | 1 | 0 | #5 | `battle_tested` |

## MISSING (86)

### `api` (5)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **CommandQuerySeparator** | 0 | 0 | #3 | `battle_tested` |
| **ContextMap** | 0 | 0 | #3 | `battle_tested` |
| **MiddlewarePipeline** | 0 | 0 | #1 | `battle_tested` |
| **RouterPipeline** | 0 | 0 | #1 | `battle_tested` |
| **ValueTransform** | 0 | 0 | #1 | `battle_tested` |

### `auth` (7)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **AuthorizationCodeFlow** | 0 | 0 | #5 | `battle_tested` |
| **CurrentPrincipal** | 0 | 0 | #1 | `battle_tested` |
| **RequestGuard** | 0 | 0 | #1 | `battle_tested` |
| **SessionStore** | 0 | 0 | #5 | `battle_tested` |
| **TokenIntrospector** | 0 | 0 | #5 | `battle_tested` |
| **TotpVerifier** | 0 | 0 | #5 | `battle_tested` |
| **WebAuthnAuthenticator** | 0 | 0 | #5 | `emerging` |

### `cache` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **DistributedLock** | 0 | 0 | #2 | `emerging` |
| **KeyValueBucket** | 0 | 0 | #2 | `emerging` |

### `compliance` (5)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **BreachNotificationQueue** | 0 | 0 | #6 | `emerging` |
| **ConsentLedger** | 0 | 0 | #6 | `battle_tested` |
| **DataSubjectRequest** | 0 | 0 | #6 | `emerging` |
| **ProcessingRecord** | 0 | 0 | #6 | `emerging` |
| **TamperEvidentAuditLog** | 0 | 0 | #6 | `battle_tested` |

### `cost` (2)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **BudgetGuard** | 0 | 0 | #8 | `emerging` |
| **TokenMeter** | 0 | 0 | #8 | `battle_tested` |

### `data` (14)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **AntiCorruptionLayer** | 0 | 0 | #3 | `battle_tested` |
| **BoundedContext** | 0 | 0 | #3 | `battle_tested` |
| **ChangeDataCapture** | 0 | 0 | #3 | `battle_tested` |
| **ConfigBinding** | 0 | 0 | #1 | `battle_tested` |
| **DataMapper** | 0 | 0 | #3 | `battle_tested` |
| **DiContainer** | 0 | 0 | #1 | `battle_tested` |
| **IdentityMap** | 0 | 0 | #3 | `battle_tested` |
| **LegalHold** | 0 | 0 | #6 | `battle_tested` |
| **LifetimeScope** | 0 | 0 | #1 | `battle_tested` |
| **PiiClassification** | 0 | 0 | #6 | `emerging` |
| **StateStore** | 0 | 0 | #2 | `battle_tested` |
| **TransactionalBatch** | 0 | 0 | #2 | `battle_tested` |
| **UnitOfWork** | 0 | 0 | #3 | `battle_tested` |
| **ValueObject** | 0 | 0 | #3 | `battle_tested` |

### `events` (9)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **DeadLetterRoute** | 0 | 0 | #2 | `battle_tested` |
| **EventEnvelope** | 0 | 0 | #2 | `battle_tested` |
| **EventSourcedStore** | 0 | 0 | #3 | `battle_tested` |
| **IdempotentConsumer** | 0 | 0 | #3 | `battle_tested` |
| **InboxDeduplicator** | 0 | 0 | #3 | `battle_tested` |
| **PartitionLog** | 0 | 0 | #2 | `battle_tested` |
| **StreamSubject** | 0 | 0 | #2 | `battle_tested` |
| **TopicBus** | 0 | 0 | #2 | `battle_tested` |
| **TransactionalOutbox** | 0 | 0 | #3 | `battle_tested` |

### `extras` (4)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **OutboundBinding** | 0 | 0 | #2 | `battle_tested` |
| **RequestShape** | 0 | 0 | #4 | `emerging` |
| **RpcInterceptor** | 0 | 0 | #2 | `battle_tested` |
| **VirtualActor** | 0 | 0 | #2 | `battle_tested` |

### `jobs` (4)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **ActivityCall** | 0 | 0 | #2 | `battle_tested` |
| **DurableTimer** | 0 | 0 | #2 | `battle_tested` |
| **WorkflowRun** | 0 | 0 | #2 | `battle_tested` |
| **WorkflowSignal** | 0 | 0 | #2 | `battle_tested` |

### `llm` (8)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **EvalHarness** | 0 | 0 | #8 | `emerging` |
| **HumanCheckpoint** | 0 | 0 | #8 | `emerging` |
| **InputGuardrail** | 0 | 0 | #8 | `emerging` |
| **OutputGuardrail** | 0 | 0 | #8 | `emerging` |
| **PromptInjectionFilter** | 0 | 0 | #8 | `emerging` |
| **PromptTemplate** | 0 | 0 | #8 | `battle_tested` |
| **ToolSchema** | 0 | 0 | #8 | `emerging` |
| **VectorStore** | 0 | 0 | #8 | `emerging` |

### `obs` (14)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **AccessLog** | 0 | 0 | #6 | `battle_tested` |
| **CardinalityGuard** | 0 | 0 | #7 | `emerging` |
| **CorrelationContext** | 0 | 0 | #7 | `battle_tested` |
| **ErrorSink** | 0 | 0 | #7 | `battle_tested` |
| **HealthProbe** | 0 | 0 | #1, #4 | `battle_tested` |
| **HistogramBuckets** | 0 | 0 | #7 | `battle_tested` |
| **LifecycleHook** | 0 | 0 | #1 | `battle_tested` |
| **LlmTrace** | 0 | 0 | #8 | `emerging` |
| **MetricMeter** | 0 | 0 | #7 | `battle_tested` |
| **ResourceDescriptor** | 0 | 0 | #7 | `battle_tested` |
| **SamplingPolicy** | 0 | 0 | #7 | `battle_tested` |
| **SemanticAttributes** | 0 | 0 | #7 | `emerging` |
| **StructuredLogger** | 0 | 0 | #7 | `battle_tested` |
| **TelemetryExporter** | 0 | 0 | #7 | `battle_tested` |

### `policy` (4)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **CorsPolicy** | 0 | 0 | #5 | `battle_tested` |
| **DataResidencyPolicy** | 0 | 0 | #6 | `emerging` |
| **EncryptionPolicy** | 0 | 0 | #6 | `battle_tested` |
| **KeyRotationSchedule** | 0 | 0 | #6 | `battle_tested` |

### `resiliency` (3)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **BackpressureSignal** | 0 | 0 | #4 | `emerging` |
| **OutlierEjection** | 0 | 0 | #4 | `battle_tested` |
| **TimeoutBudget** | 0 | 0 | #4 | `battle_tested` |

### `security` (5)

| Primitive | Pascal hits | Snake hits | Agents | Maturity |
|---|---|---|---|---|
| **CryptoEnvelope** | 0 | 0 | #5 | `battle_tested` |
| **CsrfGuard** | 0 | 0 | #5 | `battle_tested` |
| **InputValidator** | 0 | 0 | #5 | `battle_tested` |
| **OutputEncoder** | 0 | 0 | #5 | `battle_tested` |
| **SecretsVault** | 0 | 0 | #5 | `battle_tested` |

