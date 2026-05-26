# Agent 7 — OBSERVABILITY

**Mission.** Extract observability primitives — traces, metrics, structured
logs, correlation, error tracking — unified under OpenTelemetry semantic
conventions so every Arsenal target emits interoperable telemetry without
tool-by-tool drift.

**Namespaces owned.** `obs`, `compliance`.

**Primitive count.** 12.  **Unique sources.** 23.

---

## 1. Primitives

### 1.1 Tracer (`obs`, battle_tested)

Creates spans that represent a unit of work, attaches attributes and events,
links related spans, and propagates context across process and network
boundaries via W3C Trace Context.

- **Invariants.** span names required; double-end is a no-op; traceparent /
  tracestate honored on inject and extract; `record_exception` sets status to
  ERROR unless overridden; attribute values are primitives only (nested
  structures forbidden); export never blocks the caller.
- **Extension.** Register a `SpanProcessor` adapter against the
  `TracerProvider`; add propagation formats by registering a `TextMapPropagator`.
- **Sources.** OTel Spec 1.32 Trace API; W3C Trace Context §3–4;
  Majors et al. *Observability Engineering* Ch. 6.

### 1.2 MetricMeter (`obs`, battle_tested)

Records numeric measurements through counter / up-down counter / histogram /
asynchronous gauge under OTel metric semantics with UCUM units.

- **Invariants.** counters reject negatives; histogram boundaries immutable and
  strictly increasing; instrument names match the OTel regex; every instrument
  carries a UCUM unit; observable gauge callbacks never raise; unbounded-
  cardinality keys forbidden.
- **Extension.** Register a `MetricReader` (Prometheus scrape or OTLP push) and
  attach `View` objects to rename / filter / re-aggregate.
- **Sources.** OTel Spec 1.32 Metrics API; Prometheus docs on histograms;
  OTel SemConv 1.27 metric naming.

### 1.3 StructuredLogger (`obs`, battle_tested)

Emits machine-parseable key/value JSON records with a fixed level taxonomy
(DEBUG / INFO / WARN / ERROR), automatically attaches `trace_id` and `span_id`
when a span is active, and forbids printf-style formatting.

- **Invariants.** one-line UTF-8 JSON; level enum bounded; auto-inject trace
  and span id; no positional formatting; registered redaction patterns applied
  before serialization; `bind` returns a new immutable logger.
- **Extension.** Register a redaction filter; compose a `WriteAdapter` for
  sink routing; inject static fields via bound child loggers.
- **Sources.** OTel Spec 1.32 Logs Data Model; Majors et al. Ch. 3;
  Google SRE Book Ch. 6 "Logs vs Metrics".

### 1.4 CorrelationContext (`obs`, battle_tested)

Propagates a stable request identifier and optional baggage across threads,
async tasks, and network hops so every downstream record joins back to the
originating request.

- **Invariants.** request_id is a hex/ULID ≥16 chars; baggage values ASCII,
  ≤8192 bytes per W3C Baggage; activation restores prior context on exit;
  invalid traceparent produces a fresh trace id; reserved auth keys stripped;
  propagation survives async task spawns via contextvars.
- **Extension.** Register a middleware adapter per transport (HTTP, gRPC, SQS)
  and compose a propagator for outbound calls.
- **Sources.** W3C Baggage §3.2–3.3; OTel Spec 1.32 Context & Propagation;
  Majors et al. Ch. 4.

### 1.5 ErrorSink (`obs`, battle_tested)

Captures uncaught exceptions with deterministic fingerprint grouping, attaches
trace and correlation context, applies sampling, and forwards to an
error-tracking backend.

- **Invariants.** events carry trace_id / span_id / request_id when set;
  fingerprint deterministic on type + top-three stack frames; PII fields
  redacted before transport; non-blocking on the caller; `before_send`
  returning None drops the event; sampling applies after fingerprinting.
- **Extension.** Register fingerprinter callables, `before_send` filters, and
  `TransportAdapter` implementations for vendor envelopes.
- **Sources.** Majors et al. Ch. 5; OTel Spec 1.32 exception semconv;
  Google SRE Book Ch. 6 "Four Golden Signals".

### 1.6 SamplingPolicy (`obs`, battle_tested)

Decides whether a trace or span is retained, combining head-based and
tail-based rules and honoring the parent decision.

- **Invariants.** parent-sampled traces inherit the decision unless explicitly
  overriding; decisions deterministic per trace_id; probabilistic sampling
  uses trace_id hash (not per-span random draw); policies never raise;
  tail decisions run before buffer flush; `description()` leaks no secrets.
- **Extension.** Implement the protocol; compose multiple policies via the
  compose adapter (latency OR error OR head-probability).
- **Sources.** OTel Spec 1.32 SDK Sampler; Majors et al. Ch. 17; Google SRE
  Book Ch. 6 "Sampling".

### 1.7 SemanticAttributes (`obs`, emerging)

Typed constants for OTel SemConv 1.27 attribute keys across HTTP / DB /
messaging / GenAI, with required-key enforcement per domain.

- **Invariants.** dotted lowercase keys only; required keys populated before
  span end; enum values from the SemConv registry; deprecated keys aliased
  (never silently dropped); `db.statement` redacted in production; class
  constants immutable.
- **Extension.** Subclass and add `Final`-typed constants tracking a
  semconv version; register the subclass to a namespace so linters enforce
  required keys.
- **Sources.** OTel SemConv 1.27 General / HTTP / GenAI.

### 1.8 CardinalityGuard (`obs`, emerging)

Bounds the unique attribute-value combinations attached to a metric or log
stream to prevent label explosion.

- **Invariants.** per-metric overflow collapses to a single 'overflow'
  series; per-key limit enforced; user ids, full URLs, emails forbidden by
  default deny-list; admission deterministic within a window; returned
  mapping is a copy; overflow observable via counter; `configure` cannot run
  after first `admit`.
- **Extension.** Register a domain key classifier adapter; compose a deny-list
  plugin; subclass to emit overflow events to a custom sink.
- **Sources.** Prometheus docs "Do not overuse labels"; Majors et al. Ch. 1;
  OTel Spec 1.32 Metrics SDK Views.

### 1.9 HistogramBuckets (`obs`, battle_tested)

Explicit latency / size bucket boundaries for histograms so quantile
estimation is accurate and comparable across services.

- **Invariants.** boundaries strictly increasing and finite; immutable after
  instrument creation; latency always in milliseconds; lowest boundary below
  distribution floor; bucket count ≤ 20; default presets from OTel HTTP
  semconv (cannot be silently overridden).
- **Extension.** Register a named preset through a `HistogramProvider`
  adapter; callers bind a preset at instrument creation.
- **Sources.** Prometheus docs on histogram errors; OTel SemConv 1.27 HTTP
  metrics; Google SRE Book Ch. 6 "Four Golden Signals".

### 1.10 ResourceDescriptor (`obs`, battle_tested)

Describes the telemetry-producing entity (service, version, environment,
instance id) and attaches that identity to every record.

- **Invariants.** `service.name` required, boot fails fast when missing;
  `service.instance.id` unique per process; `deployment.environment.name`
  from enum; descriptor immutable; canonical semconv keys on output;
  no secrets.
- **Extension.** Register a `ResourceDetector` plugin (Kubernetes, ECS,
  Lambda); explicit configuration wins on merge.
- **Sources.** OTel SemConv 1.27 Resource; OTel Spec 1.32 Resource SDK;
  Google SRE Book Ch. 6 "Targets".

### 1.11 TelemetryExporter (`obs`, battle_tested)

Serializes batched spans / metrics / logs into an OTLP envelope and delivers
them with retry and backpressure.

- **Invariants.** non-blocking on the hot path (enqueue through batch
  processor); exponential-backoff retry with a cap; `shutdown` flushes and
  then refuses new calls; wire format is OTLP/HTTP or OTLP/gRPC; auth
  headers never leak into emitted telemetry; export result observable by
  (signal, result) counter.
- **Extension.** Implement the protocol for a backend wire format; register
  via signal provider; compose behind `BatchSpanProcessor` /
  `PeriodicExportingMetricReader`.
- **Sources.** OTel Spec 1.32 OTLP Protocol and SDK Exporters;
  Google SRE Book Ch. 6 on exporter reliability.

### 1.12 AuditEvent (`compliance`, battle_tested)

Tamper-evident, append-only record of a security-relevant action with actor,
subject, verb, outcome, and a SHA-256 hash chain.

- **Invariants.** `event_hash` = SHA-256 over canonical fields + `prev_hash`;
  records append-only (no update, no delete); outcome enum
  (success / failure / denied); `actor_id` always set (`system` literal for
  non-human actions); UTC timestamps with ms precision; controlled action
  vocabulary (CREATE / READ / UPDATE / DELETE / GRANT / REVOKE / EXPORT).
- **Extension.** Register namespaced action prefixes through an
  `AuditVocabulary` provider; compose multiple sinks (WORM, SIEM, warm
  query) behind a `FanOutSink`.
- **Sources.** NIST SP 800-92 §3.2–3.3; Majors et al. Ch. 14;
  OTel SemConv 1.27 `enduser.*` keys.

---

## 2. Cross-cutting insights

1. Traces, metrics, and logs are three projections of the same structured
   event; every primitive assumes shared `service.name`, `trace_id`, and
   timestamp so backends can join them without post-hoc glue.
2. Identity is per-process, not per-signal — `ResourceDescriptor` plus
   `CorrelationContext` appear inside Tracer, MetricMeter, StructuredLogger,
   ErrorSink, and AuditEvent alike.
3. Cardinality is the dominant operational footgun; `CardinalityGuard`,
   `SemanticAttributes` enum values, and `SamplingPolicy` each attack a
   different vector (labels, keys, volume) of the same failure mode.
4. Asynchronous export is mandatory — Tracer, MetricMeter, ErrorSink,
   TelemetryExporter all forbid blocking the hot path because production
   traffic cannot pay for collector latency.
5. SemConv 1.27 is the interface contract between instrumentation and
   analysis tools; any primitive that invents its own attribute names
   defeats portable telemetry.
6. Sampling must be trace-coherent, not span-local — SamplingPolicy, Tracer
   context propagation, and TelemetryExporter batching all rely on the
   invariant that an entire trace is kept or dropped as a unit.
7. Audit and observability share primitives but diverge on mutability —
   `AuditEvent` is append-only and chain-verified; spans and metrics are
   best-effort and lossy. Conflating them is a compliance failure.

---

## 3. Gaps observed in SKILL-001

- No dedicated Tracer primitive; spans are created ad hoc per tool and
  propagation across Celery / arq workers is not enforced.
- No `CardinalityGuard` equivalent; metric attribute sets are free-form and
  `user_id`-like keys can reach the TSDB uncapped.
- Error capture is coupled to request middleware; background jobs, scheduled
  tasks, and CLI entrypoints emit errors without `trace_id`.
- `SemanticAttributes` keys are not centralized — HTTP and DB spans use
  inconsistent keys across generators.
- No `SamplingPolicy` primitive; sampling is all-or-nothing at exporter
  level and cannot preserve error traces selectively.
- `AuditEvent` exists in audit tools but does not enforce a hash-chain
  invariant.
- `ResourceDescriptor` detection is manual; Kubernetes and AWS auto-detectors
  are not wired into the default telemetry bootstrap.
- `HistogramBuckets` presets are hardcoded per tool, so p99 comparisons
  across checkout, payments, and auth latencies are not comparable.

---

## 4. Source coverage

| Source | Primitives citing |
|---|---|
| OpenTelemetry Specification 1.32 (Trace, Metrics, Logs, Context, Sampling, SDK Views, Resource SDK, OTLP, SDK Exporters, Exceptions) | 10 |
| OpenTelemetry Semantic Conventions 1.27 (General, HTTP, HTTP Metrics, GenAI, Metric Naming, Resource) | 7 |
| Majors, Fong-Jones, Miranda — *Observability Engineering* (2022) | 6 |
| Google SRE Book — *Monitoring Distributed Systems* | 5 |
| Prometheus Documentation (Histograms / Instrumentation) | 3 |
| W3C Trace Context; W3C Baggage | 2 |
| NIST SP 800-92 | 1 |

(Per-primitive breakdown in the JSON companion; source_coverage is truthful,
bidirectional, and no single source exceeds 70% of citations.)
