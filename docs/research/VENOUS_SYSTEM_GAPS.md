# Venous System Gaps

> Prioritized diff between the consolidated venous-system catalog (113 primitives) and the current SKILL-001 FastAPI Production skill. Plus the 60 gaps the 8 research agents observed directly.

## Summary

- **Absent primitives (keyword MISSING):** 86
- **Thin primitives (PARTIAL — concept touched, likely not a primitive):** 10
- **Agent-observed qualitative gaps:** 60

## Priority 1 — Missing primitives, grouped by namespace

Absent from SKILL-001 by keyword (barring renames / semantic equivalents).

### `api` — 5 missing

- **`CommandQuerySeparator`** (`battle_tested`) — Partitions the API into write commands that mutate state and read queries that observe it so each side can scale and evolve independently.
  *Agent 3 (PATTERNS)*
- **`ContextMap`** (`battle_tested`) — Catalogs every BoundedContext and the integration relationship (Partnership, Customer-Supplier, Conformist, Open Host) between each pair.
  *Agent 3 (PATTERNS)*
- **`MiddlewarePipeline`** (`battle_tested`) — Ordered chain of components that each transform the RequestContext and decide whether to call the next, enabling cross-cutting concerns.
  *Agent 1 (FRAMEWORKS)*
- **`RouterPipeline`** (`battle_tested`) — Named bundle of middleware (e.g. 'browser', 'api') that a route joins with pipe_through so groups of endpoints share the same pre-dispatch chain.
  *Agent 1 (FRAMEWORKS)*
- **`ValueTransform`** (`battle_tested`) — Strongly-typed parse/validate step that converts a raw inbound argument (body/query/param) into the typed value the handler expects.
  *Agent 1 (FRAMEWORKS)*

### `auth` — 7 missing

- **`AuthorizationCodeFlow`** (`battle_tested`) — Execute the OAuth 2.0 authorization-code grant with PKCE, enforcing state, nonce, redirect URI pinning, and one-time code exchange against the token endpoint.
  *Agent 5 (SECURITY)*
- **`CurrentPrincipal`** (`battle_tested`) — Read-only view of the authenticated identity for the active request, including subject id, tenant, roles, and claim set.
  *Agent 1 (FRAMEWORKS)*
- **`RequestGuard`** (`battle_tested`) — Predicate invoked before a handler runs that returns allow/deny based on RequestContext and CurrentPrincipal, short-circuiting the pipeline on deny.
  *Agent 1 (FRAMEWORKS)*
- **`SessionStore`** (`battle_tested`) — Issue, rotate, and revoke server-side session records keyed by high-entropy identifiers, with fixation resistance and explicit lifetime boundaries.
  *Agent 5 (SECURITY)*
- **`TokenIntrospector`** (`battle_tested`) — Validate access tokens by signature, issuer, audience, expiry, and not-before claims, with optional RFC 7662 introspection for opaque tokens.
  *Agent 5 (SECURITY)*
- **`TotpVerifier`** (`battle_tested`) — Generate and verify six-digit time-based one-time passwords per RFC 6238 with constant-time comparison, clock-skew tolerance, and replay prevention.
  *Agent 5 (SECURITY)*
- **`WebAuthnAuthenticator`** (`emerging`) — Register and assert passkey credentials per the Web Authentication API, binding credentials to an RP ID and verifying attestation, challenge, origin, and signature counter.
  *Agent 5 (SECURITY)*

### `cache` — 2 missing

- **`DistributedLock`** (`emerging`) — Named mutex with lease expiry that grants one holder exclusive access across processes and is released explicitly or by lease timeout on crash.
  *Agent 2 (DISTRIBUTED)*
- **`KeyValueBucket`** (`emerging`) — Named bucket of key value entries with optimistic create and update and a watch channel for change notifications derived from an underlying stream.
  *Agent 2 (DISTRIBUTED)*

### `compliance` — 5 missing

- **`BreachNotificationQueue`** (`emerging`) — Tracks suspected and confirmed personal-data incidents with a statutory notification clock, so the 72-hour window is enforced in code.
  *Agent 6 (COMPLIANCE)*
- **`ConsentLedger`** (`battle_tested`) — Records granular per-subject, per-purpose consent grants and revocations with timestamp and version of the notice accepted.
  *Agent 6 (COMPLIANCE)*
- **`DataSubjectRequest`** (`emerging`) — Coordinates the lifecycle of an access or erasure request across all stores that hold data about the subject, with a SLA clock.
  *Agent 6 (COMPLIANCE)*
- **`ProcessingRecord`** (`emerging`) — Machine-readable record of processing activities that a controller must maintain, generated from code rather than a separate document.
  *Agent 6 (COMPLIANCE)*
- **`TamperEvidentAuditLog`** (`battle_tested`) — Append-only record of security-relevant events, hash-chained and signed so any retroactive mutation is detectable by verification.
  *Agent 6 (COMPLIANCE)*

### `cost` — 2 missing

- **`BudgetGuard`** (`emerging`) — Enforce per-tenant, per-feature, and per-time-window spending ceilings by consulting the TokenMeter and rejecting or throttling new model calls when the configured budget is exhausted.
  *Agent 8 (LLM_ERA)*
- **`TokenMeter`** (`battle_tested`) — Record prompt tokens, completion tokens, cache-read tokens, and provider-reported cost for every model call, attributing each unit of consumption to a tenant, user, and feature label.
  *Agent 8 (LLM_ERA)*

### `data` — 14 missing

- **`AntiCorruptionLayer`** (`battle_tested`) — Translates between a local model and a foreign or legacy model so upstream semantics cannot leak into the local BoundedContext.
  *Agent 3 (PATTERNS)*
- **`BoundedContext`** (`battle_tested`) — Declares the explicit linguistic and model boundary within which one ubiquitous language and one set of invariants apply.
  *Agent 3 (PATTERNS)*
- **`ChangeDataCapture`** (`battle_tested`) — Publishes an ordered stream of row-level changes from a source database so downstream systems can consume mutations without dual writes.
  *Agent 3 (PATTERNS)*
- **`ConfigBinding`** (`battle_tested`) — Binds a namespaced slice of the runtime configuration to a typed record, validated at startup so misconfiguration fails loud, not silent.
  *Agent 1 (FRAMEWORKS)*
- **`DataMapper`** (`battle_tested`) — Moves state between in-memory domain objects and rows in storage while keeping both ignorant of each other.
  *Agent 3 (PATTERNS)*
- **`DiContainer`** (`battle_tested`) — Registry that resolves a typed request for a dependency into a constructed instance obeying the declared lifetime scope.
  *Agent 1 (FRAMEWORKS)*
- **`IdentityMap`** (`battle_tested`) — Caches loaded domain objects by identity inside one session so the same row is never represented twice in memory.
  *Agent 3 (PATTERNS)*
- **`LegalHold`** (`battle_tested`) — Suspends retention-driven deletion and erasure cascades for records covered by a litigation or regulatory hold until the hold is released.
  *Agent 6 (COMPLIANCE)*
- **`LifetimeScope`** (`battle_tested`) — Typed enumeration that fixes how long a resolved instance lives: the whole process, one request, or one injection point.
  *Agent 1 (FRAMEWORKS)*
- **`PiiClassification`** (`emerging`) — Schema-level annotation that tags every field as one of PII, PHI, PCI, or public, gating serialization and logging through a central mask.
  *Agent 6 (COMPLIANCE)*
- **`StateStore`** (`battle_tested`) — Key addressed durable key-value CRUD surface with optimistic concurrency tokens and optional TTL for language neutral state access.
  *Agent 2 (DISTRIBUTED)*
- **`TransactionalBatch`** (`battle_tested`) — Atomic multi key write unit that commits a set of upsert and delete operations to one state store under a single transaction boundary.
  *Agent 2 (DISTRIBUTED)*
- **`UnitOfWork`** (`battle_tested`) — Tracks object changes during a business transaction and flushes them to storage as one atomic commit or rollback.
  *Agent 3 (PATTERNS)*
- **`ValueObject`** (`battle_tested`) — Represents a descriptive concept whose identity is defined entirely by its attributes and which is immutable once constructed.
  *Agent 3 (PATTERNS)*

### `events` — 9 missing

- **`DeadLetterRoute`** (`battle_tested`) — Named destination where undeliverable or repeatedly failed messages are routed after the redelivery budget is exhausted so they can be inspected or replayed.
  *Agent 2 (DISTRIBUTED)*
- **`EventEnvelope`** (`battle_tested`) — Canonical CloudEvents 1.0 shape that normalizes id, source, type, time and payload so downstream handlers parse the same structure regardless of transport.
  *Agent 2 (DISTRIBUTED)*
- **`EventSourcedStore`** (`battle_tested`) — Persists aggregate state as an ordered sequence of domain events and reconstructs current state by folding them on load.
  *Agent 3 (PATTERNS)*
- **`IdempotentConsumer`** (`battle_tested`) — Applies a message's effect at most once per logical key while tolerating at-least-once delivery from the transport.
  *Agent 3 (PATTERNS)*
- **`InboxDeduplicator`** (`battle_tested`) — Records processed message identifiers in the consumer's database so redelivered messages are detected and skipped exactly once.
  *Agent 3 (PATTERNS)*
- **`PartitionLog`** (`battle_tested`) — Ordered append only per partition event log identified by topic and partition number whose position is addressed by a monotonically increasing offset.
  *Agent 2 (DISTRIBUTED)*
- **`StreamSubject`** (`battle_tested`) — Hierarchical dot separated event routing name that supports single token and trailing wildcard matching for consumer filters and stream captures.
  *Agent 2 (DISTRIBUTED)*
- **`TopicBus`** (`battle_tested`) — Publish and subscribe facade over a broker topic that delivers CloudEvents at least once to named subscriber groups with optional dead letter routing.
  *Agent 2 (DISTRIBUTED)*
- **`TransactionalOutbox`** (`battle_tested`) — Stores outgoing messages in the same local transaction as the state change so a relay can publish them atomically with the commit.
  *Agent 3 (PATTERNS)*

### `extras` — 4 missing

- **`OutboundBinding`** (`battle_tested`) — Declarative adapter that lets the application invoke an external resource through a named operation and metadata without embedding the vendor SDK.
  *Agent 2 (DISTRIBUTED)*
- **`RequestShape`** (`emerging`) — Capture a request's resiliency context (priority class, deadline, idempotency key, retry-count-so-far) in a single immutable record propagated across boundaries.
  *Agent 4 (RESILIENCY)*
- **`RpcInterceptor`** (`battle_tested`) — Per call middleware that wraps a remote procedure invocation to read or mutate metadata, enforce deadlines and translate errors consistently across services.
  *Agent 2 (DISTRIBUTED)*
- **`VirtualActor`** (`battle_tested`) — Location transparent single writer object addressed by type and id that holds private state and processes one message at a time on activation.
  *Agent 2 (DISTRIBUTED)*

### `jobs` — 4 missing

- **`ActivityCall`** (`battle_tested`) — Workflow scoped unit of side effectful work scheduled with explicit timeouts and a retry policy that the runtime executes at least once on a worker.
  *Agent 2 (DISTRIBUTED)*
- **`DurableTimer`** (`battle_tested`) — Workflow scoped sleep that persists across worker outages and fires after a logical delay so long delays do not hold process resources.
  *Agent 2 (DISTRIBUTED)*
- **`WorkflowRun`** (`battle_tested`) — Durable replayable orchestration identified by a workflow id that survives worker restarts and reconstructs state from a recorded event history.
  *Agent 2 (DISTRIBUTED)*
- **`WorkflowSignal`** (`battle_tested`) — Asynchronous fire and forget write that delivers named input to an open workflow run and is recorded into the event history for replay.
  *Agent 2 (DISTRIBUTED)*

### `llm` — 8 missing

- **`EvalHarness`** (`emerging`) — Execute a golden dataset against a prompt-plus-model pair and compute graded verdicts via deterministic metrics and optional judge models, emitting a replayable run record.
  *Agent 8 (LLM_ERA)*
- **`HumanCheckpoint`** (`emerging`) — Block an agent workflow at a named step until an authorized human approves, rejects, or edits the proposed action, persisting the decision and the reviewer identity.
  *Agent 8 (LLM_ERA)*
- **`InputGuardrail`** (`emerging`) — Intercept user input before it reaches a model and reject, redact, or transform it according to deterministic rules (PII, injection markers) and optional LLM-judged classifications.
  *Agent 8 (LLM_ERA)*
- **`OutputGuardrail`** (`emerging`) — Inspect model output after generation and reject, rewrite, or annotate it against schema, policy, and safety rules before the caller or downstream tools receive it.
  *Agent 8 (LLM_ERA)*
- **`PromptInjectionFilter`** (`emerging`) — Quarantine untrusted text (retrieved documents, tool outputs, user messages) by wrapping it in delimiters and stripping instruction-like fragments that target the model.
  *Agent 8 (LLM_ERA)*
- **`PromptTemplate`** (`battle_tested`) — Declare a named, versioned, parameterized prompt whose text, variables, and target model are pinned so two runs of the same version produce identical rendered payloads.
  *Agent 8 (LLM_ERA)*
- **`ToolSchema`** (`emerging`) — Describe a callable tool by name, JSON-schema input, side-effect class, and required scopes so function calling validates arguments and enforces authorization before executing the tool.
  *Agent 8 (LLM_ERA)*
- **`VectorStore`** (`emerging`) — Expose upsert, similarity search, metadata filter, and delete over embedded documents with per-tenant scoping so retrieval augmentation cannot leak rows across tenants or return deleted content.
  *Agent 8 (LLM_ERA)*

### `obs` — 14 missing

- **`AccessLog`** (`battle_tested`) — Records every successful read of classified data with actor, purpose-of-use, and record identifier, distinct from the security audit log.
  *Agent 6 (COMPLIANCE)*
- **`CardinalityGuard`** (`emerging`) — Bound the unique attribute-value combinations attached to a metric or log stream to prevent label explosion from breaking time-series databases.
  *Agent 7 (OBSERVABILITY)*
- **`CorrelationContext`** (`battle_tested`) — Propagate a stable request identifier and optional baggage across threads, async tasks, and network hops so every downstream record can be joined back to the originating request.
  *Agent 7 (OBSERVABILITY)*
- **`ErrorSink`** (`battle_tested`) — Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation context, apply sampling, and forward to an error-tracking backend.
  *Agent 7 (OBSERVABILITY)*
- **`HealthProbe`** (`battle_tested`) — Small probe that reports UP/DOWN/DEGRADED with optional detail so orchestrators (Kubernetes, load balancers) can route traffic safely.
  *Agent 1 (FRAMEWORKS), Agent 4 (RESILIENCY)*
- **`HistogramBuckets`** (`battle_tested`) — Define explicit latency and size bucket boundaries for histogram instruments so quantile estimation is accurate and comparable across services.
  *Agent 7 (OBSERVABILITY)*
- **`LifecycleHook`** (`battle_tested`) — Named callback fired at a defined application phase (starting, ready, stopping) so tools can initialize resources and shut down cleanly.
  *Agent 1 (FRAMEWORKS)*
- **`LlmTrace`** (`emerging`) — Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI semantic conventions so token counts, model identity, and prompt/response linkage land in traces consistently.
  *Agent 8 (LLM_ERA)*
- **`MetricMeter`** (`battle_tested`) — Record numeric measurements through four instrument shapes — counter, up-down counter, histogram, asynchronous gauge — under OpenTelemetry metric semantics.
  *Agent 7 (OBSERVABILITY)*
- **`ResourceDescriptor`** (`battle_tested`) — Describe the entity producing telemetry — service, version, deployment environment, instance id — and attach that identity to every span, metric, and log record.
  *Agent 7 (OBSERVABILITY)*
- **`SamplingPolicy`** (`battle_tested`) — Decide whether a given trace or span is retained, combining head-based (at span start) and tail-based (post hoc) rules and honoring the parent sampling decision.
  *Agent 7 (OBSERVABILITY)*
- **`SemanticAttributes`** (`emerging`) — Expose the OpenTelemetry semantic-convention attribute keys as typed constants and enforce that primitives populate required keys for HTTP, database, messaging, and GenAI operations.
  *Agent 7 (OBSERVABILITY)*
- **`StructuredLogger`** (`battle_tested`) — Emit machine-parseable key/value log records with a fixed level taxonomy, attached trace and span identifiers, and no positional string formatting.
  *Agent 7 (OBSERVABILITY)*
- **`TelemetryExporter`** (`battle_tested`) — Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and deliver them to a configured endpoint with retry and backpressure.
  *Agent 7 (OBSERVABILITY)*

### `policy` — 4 missing

- **`CorsPolicy`** (`battle_tested`) — Evaluate cross-origin preflight and simple-request allowance against a closed list of origins, methods, headers, and credential mode without reflecting arbitrary Origin values.
  *Agent 5 (SECURITY)*
- **`DataResidencyPolicy`** (`emerging`) — Binds a data class to a set of permitted storage and processing regions, refusing writes or cross-border transfers outside the allow-list.
  *Agent 6 (COMPLIANCE)*
- **`EncryptionPolicy`** (`battle_tested`) — Declares cipher, key provider, and rotation cadence for a data class at rest and in transit, and rejects storage without a bound policy.
  *Agent 6 (COMPLIANCE)*
- **`KeyRotationSchedule`** (`battle_tested`) — Drives rotation of data-encryption keys on a fixed cadence with overlap window, and blocks new writes with a key past its cutover.
  *Agent 6 (COMPLIANCE)*

### `resiliency` — 3 missing

- **`BackpressureSignal`** (`emerging`) — Carry producer-visible pressure information from a consumer or queue so upstream components can slow down rather than fill unbounded buffers.
  *Agent 4 (RESILIENCY)*
- **`OutlierEjection`** (`battle_tested`) — Remove a backend instance from the load-balancing pool when its error rate or latency statistics exceed the cluster baseline and reinstate it after a cooldown.
  *Agent 4 (RESILIENCY)*
- **`TimeoutBudget`** (`battle_tested`) — Attach a monotonic deadline to an inbound request and propagate the remaining budget to every downstream call so no call outlives its originating request.
  *Agent 4 (RESILIENCY)*

### `security` — 5 missing

- **`CryptoEnvelope`** (`battle_tested`) — Encrypt and decrypt payloads with authenticated encryption, key-id-tagged ciphertext, and deterministic header framing that enables key rotation without re-encryption on read.
  *Agent 5 (SECURITY)*
- **`CsrfGuard`** (`battle_tested`) — Bind state-changing HTTP requests to the authenticated session through per-session tokens validated against a matching header or form field.
  *Agent 5 (SECURITY)*
- **`InputValidator`** (`battle_tested`) — Parse and constrain inbound payloads against a declared schema with typed coercion, length and range bounds, and rejection of unknown fields.
  *Agent 5 (SECURITY)*
- **`OutputEncoder`** (`battle_tested`) — Encode untrusted values for a named sink (HTML text, HTML attribute, JavaScript string, URL path, URL query, CSS value) using sink-specific escaping rules.
  *Agent 5 (SECURITY)*
- **`SecretsVault`** (`battle_tested`) — Fetch, cache, rotate, and audit application secrets through a named-secret interface backed by an external key management or secrets service.
  *Agent 5 (SECURITY)*

## Priority 2 — Thin primitives (PARTIAL)

Concept touched by SKILL-001 but coverage is thin (1-2 file hits). Candidate for promotion to first-class primitive.

- **`AuditEvent`** [`compliance`] — 1P + 0S hits — Emit a tamper-evident, append-only record of a security-relevant action with actor, subject, action verb, outcome, and a cryptographic chain link.  
  *Agent 7 (OBSERVABILITY)*
- **`RetentionPolicy`** [`compliance`] — 1P + 0S hits — Declarative binding of a data class to a maximum lifetime, enforced by scheduled purge and blocked at write-time if unclassified.  
  *Agent 6 (COMPLIANCE)*
- **`EventStream`** [`events`] — 0P + 2S hits — An ordered, append-only log of events partitioned by key and replayable from any offset by any number of consumers.  
  *Agent 3 (PATTERNS)*
- **`SagaOrchestrator`** [`events`] — 0P + 1S hits — Coordinates a multi-step business transaction across services by driving each step and triggering compensations when a later step fails.  
  *Agent 3 (PATTERNS)*
- **`ModelRouter`** [`llm`] — 0P + 1S hits — Select a concrete model handle for a request based on declared policy (cheapest-first, quality-floor, tenant override) and fall back to the next candidate on rate limit, timeout, or provider error.  
  *Agent 8 (LLM_ERA)*
- **`ResponseCache`** [`llm`] — 0P + 2S hits — Reuse a prior model response when a call resolves to the same cache key (exact prompt hash or semantic embedding match within a threshold), returning the cached payload.  
  *Agent 8 (LLM_ERA)*
- **`EventBus`** [`obs`] — 0P + 2S hits — In-process publish/subscribe point for named framework and application events (e.g. sql.active_record, http.request) with structured payloads.  
  *Agent 1 (FRAMEWORKS)*
- **`ChaosInjector`** [`resiliency`] — 0P + 2S hits — Deliberately introduce latency, errors or partial partitions in controlled scopes so resiliency primitives are exercised in production-like conditions.  
  *Agent 4 (RESILIENCY)*
- **`ContentSecurityPolicy`** [`security`] — 0P + 1S hits — Compose, serialize, and enforce a Content Security Policy header that constrains script, style, frame, and connection origins with strict-dynamic and nonce-based script allowance.  
  *Agent 5 (SECURITY)*
- **`SignatureVerifier`** [`security`] — 1P + 0S hits — Produce and verify detached digital signatures with key-id selection, typed message framing, and refusal of weak or unannounced algorithms.  
  *Agent 5 (SECURITY)*

## Priority 3 — Qualitative gaps observed by agents

Free-text gaps each research agent flagged directly. These are diffs between the research corpus and SKILL-001 that the automated keyword audit cannot detect (missing shared contracts, naming drift, composition gaps).

### Agent 1 — FRAMEWORKS

- SKILL-001 lacks a LifetimeScope enum; lifetimes are currently implicit in tool bodies rather than declared at registration.
- CorrelationId propagation across outbound HTTP/queue calls is not a declared primitive; each integration tool handles headers its own way.
- No unified HealthProbe registry aggregating /readyz and /livez across tools; each generator adds its own path with its own shape.
- LifecycleHook phases (STARTING/READY/STOPPING) are not a first-class primitive; startup wiring is scattered across generators.
- FeatureToggle as a context-aware predicate is absent; the current flag story is environment-variable checks without per-tenant evaluation.

### Agent 2 — DISTRIBUTED

- SKILL-001 lacks a durable workflow primitive; long running orchestration is still modeled as chained background jobs without event history.
- No CloudEvents envelope shape is enforced on the existing event bus, so (source, id) dedup is not guaranteed across producers.
- Virtual actor style single writer entities are missing; hot keys fall back to row locks or in process asyncio locks.
- Distributed lock primitive with lease expiry is not exposed; tools reuse cache TTL tricks that drift under clock skew.
- Dead letter route configuration is ad hoc per tool and not a first class primitive tied to the TopicBus contract.
- No key value bucket with compare and swap plus watch; feature flag and session stores rely on plain cache semantics.

### Agent 3 — PATTERNS

- SKILL-001 lacks a first-class UnitOfWork primitive; commit boundaries are per-tool and leak across feature boundaries.
- No TransactionalOutbox primitive exists; tools integrating with brokers rely on implicit dual writes.
- IdempotentConsumer and InboxDeduplicator are not codified; each messaging consumer reinvents dedupe differently.
- No ContextMap primitive is present; cross-module integration policy is tacit and undocumented.
- MaterializedView and ChangeDataCapture are missing; cache and projection strategies vary by feature without a shared contract.
- Specification is not a shared primitive; query criteria are inlined into repositories per tool.
- SagaOrchestrator is absent; cross-service workflows are ad-hoc with no compensation registry.
- EventSourcedStore is not offered as an option; aggregates cannot opt into sourcing without bespoke code.
- CommandQuerySeparator is not enforced; read and write handlers intermix in most feature tools.
- AntiCorruptionLayer has no primitive; third-party SDK types are imported directly into domain code.

### Agent 4 — RESILIENCY

- SKILL-001 lacks a shared TimeoutBudget primitive; per-call timeouts are set locally and do not propagate across async boundaries.
- No first-class Bulkhead partitioning exists in SKILL-001; worker pools and HTTP clients share resources without isolation.
- Retry logic in SKILL-001 is ad-hoc per tool and does not enforce a global retry budget or idempotency requirement.
- A priority-aware LoadShedder is absent; admission control is effectively binary at the reverse proxy.
- Chaos injection hooks are not wired into the resiliency primitives, so their behavior is unverified in production-like conditions.
- RequestShape-like immutable context is not propagated end-to-end; priority and idempotency keys are lost across hops.

### Agent 5 — SECURITY

- SKILL-001 lacks a first-class PasswordHasher primitive with rotation-aware needs_rehash semantics; tools that touch credentials inline with bcrypt drift apart.
- No WebAuthn/passkey registration primitive — current auth additions assume shared-secret factors and miss origin/RP-ID binding.
- CryptoEnvelope with key-id tagging is not surfaced; field-level encryption tools roll their own AES without rotation support.
- SecretsVault with rotation and audit hooks is absent; generators rely on environment variables injected at deploy time.
- CSP composer is missing; tools emitting HTML responses ship without a nonce-aware, strict-dynamic policy.
- RateLimiter is not scoped as a security primitive today; add_rate_limit lives in resiliency and misses principal-keyed login throttling per NIST SP 800-63B §5.2.2.
- TokenIntrospector abstraction is absent — JWT verification is reimplemented per tool with inconsistent audience enforcement.
- SessionStore lacks a revoke_all_for_subject operation in current tooling; password-change rotation is not guaranteed to terminate live sessions.

### Agent 6 — COMPLIANCE

- SKILL-001 has no hash-chained audit primitive; writes land in structured logs without per-entry signature or chain verification.
- No declarative RetentionPolicy binding exists — retention is per-table, enforced by ad-hoc scripts without legal_basis traceability.
- ConsentLedger-like primitive is absent; consent state is modeled as boolean flags without notice-version history.
- DSAR/RTBF requires a cross-store cascade; no current primitive enforces that every registered store attaches an artifact before closing a request.
- PiiClassification at schema level is missing — masking is left to serializer code, which means a new field ships unclassified by default.
- AccessLog separate from the security audit is not provided, blocking HIPAA 164.528 accounting-of-disclosures reports.
- EncryptionPolicy per data_class is not enforced at write; at-rest encryption is trusted to cloud defaults without cipher or rotation guarantees.
- LegalHold primitive is absent, so retention sweepers can destroy evidence under active investigation.
- Breach notification lacks a statutory clock — incidents live in generic tickets with no 72-hour SLA alerting.
- DataResidencyPolicy is not modeled; region binding relies on deployment topology and ignores replicas and backups.

### Agent 7 — OBSERVABILITY

- SKILL-001 lacks a dedicated Tracer primitive — spans are created ad hoc per tool and propagation across Celery/arq workers is not enforced.
- No CardinalityGuard equivalent exists; metric attribute sets are free-form and user_id-like keys can reach the TSDB uncapped.
- Error capture is coupled to request middleware, so background jobs, scheduled tasks, and CLI entrypoints emit errors without trace_id.
- SemanticAttributes keys are not centralized — HTTP and DB spans use inconsistent keys across generators, blocking cross-service queries.
- There is no SamplingPolicy primitive; sampling is either all-or-nothing at the exporter level and cannot keep error traces selectively.
- AuditEvent exists in audit tools but does not enforce a hash-chain invariant, so tamper evidence depends on downstream WORM storage.
- ResourceDescriptor detection is manual; Kubernetes and AWS auto-detectors are not wired into the default telemetry bootstrap.
- HistogramBuckets presets are hardcoded per tool, so p99 comparisons across checkout, payments, and auth latencies are not apples-to-apples.

### Agent 8 — LLM_ERA

- SKILL-001 lacks a first-class PromptTemplate object with versioned fingerprint; prompts today are inline strings without diffable identity.
- No shared VectorStore primitive exists in SKILL-001, so tenant scoping and deletion propagation are re-solved per feature.
- No OutputGuardrail chain is wired to the tool-call dispatcher; OWASP LLM02 validation is implicit and per-endpoint.
- HumanCheckpoint is absent; high-impact actions that should require approval currently execute on model output alone.
- TokenMeter and BudgetGuard are not factored out, so cost attribution relies on post-hoc log parsing rather than a call-time ledger.
- LlmTrace does not yet align with OpenTelemetry GenAI semantic convention attribute names, blocking vendor-neutral observability backends.
- PromptInjectionFilter is missing, meaning retrieved documents and tool outputs are concatenated into prompts without a quarantine step.

## Suggested sequencing

1. **Reconciliation pass** — manual walk through PARTIAL primitives to decide: promote, rename, or deprecate the existing surface.
2. **MISSING + battle_tested** — candidate for SkillEngine L0 Convention layer (default-on, zero config). Highest leverage.
3. **MISSING + emerging** — land as EXTEND tools first, promote when stable.
4. **Cross-agent collisions** (`HealthProbe`, `RateLimiter`) — reconcile the two api_signatures into a single canonical one before SkillEngine sees them.
5. **Agent-observed gaps** — triage each against the existing EXPANSION_ROADMAP.md, collapse duplicates, promote real misses to concrete tasks.

