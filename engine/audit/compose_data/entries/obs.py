"""WP-17 — curated compose-data entries for the `obs` namespace.

Pure-data module. Mirrors the source section that lived in
``engine/audit/_build_compose.py`` between the ``# === obs`` marker
and the next namespace marker. No imports beyond ``annotations``; merged
into the master ``E`` dict by ``engine.audit.compose_data._assembly``.

Entry shape (preserved verbatim from the pre-split file):
    (purpose, compose_with_siblings, [(pattern_name, [siblings...], invariant), ...])
"""

from __future__ import annotations

ENTRIES: dict[str, tuple[str, list[str], list[tuple[str, list[str], str]]]] = {
    # ======================================================== obs
    "AccessLog": (
        "Record every successful READ of a classified record separately from the security audit log so accounting-of-disclosures stays tractable.",
        ["AuditEvent", "TamperEvidentAuditLog", "PiiClassification", "CurrentPrincipal"],
        [
            (
                "Dual-stream auditing",
                ["AuditEvent", "TamperEvidentAuditLog"],
                "Reads and security events hash-chain into distinct sealed streams; query volume never drowns security signal.",
            ),
            (
                "Classification-driven reads",
                ["PiiClassification", "CurrentPrincipal"],
                "Every read captures actor + data_class + purpose_of_use; HIPAA accounting-of-disclosures is one projection over the stream.",
            ),
            (
                "Tamper-evident forensics",
                ["TamperEvidentAuditLog", "SignatureVerifier"],
                "Access records seal into the chain; auditors verify 'this read log was not edited' with one signature check.",
            ),
        ],
    ),
    "CardinalityGuard": (
        "Bound the unique attribute-value combinations attached to a metric or log stream to prevent label explosion.",
        ["MetricMeter", "HistogramBuckets", "SemanticAttributes", "StructuredLogger"],
        [
            (
                "Safe labeling",
                ["MetricMeter", "SemanticAttributes"],
                "High-cardinality labels (user id, trace id) are rejected at registration; developers cannot accidentally 10x the metrics bill.",
            ),
            (
                "Bounded log dimensions",
                ["StructuredLogger", "SemanticAttributes"],
                "Structured log fields are capped to a declared set; 'just add one more dimension' goes through review, not PR auto-merge.",
            ),
            (
                "Quantile integrity",
                ["HistogramBuckets", "MetricMeter"],
                "Fixed buckets + bounded cardinality keep p99 estimation honest; a hot label does not collapse bucket fidelity.",
            ),
        ],
    ),
    "CorrelationContext": (
        "Propagate a stable request identifier and optional baggage across threads, async tasks, and network boundaries.",
        ["CorrelationId", "StructuredLogger", "Tracer", "MiddlewarePipeline"],
        [
            (
                "End-to-end stitching",
                ["CorrelationId", "StructuredLogger"],
                "Every log line inherits the active correlation id; one grep reconstructs the full causal chain of a request.",
            ),
            (
                "Trace-log correlation",
                ["Tracer", "StructuredLogger"],
                "Trace id and correlation id travel together; jumping from a slow span to its logs is one click, not a timestamp search.",
            ),
            (
                "Async-safe propagation",
                ["MiddlewarePipeline", "RequestContext"],
                "Context survives task spawning and executor handoffs — handler code never re-threads identifiers by hand.",
            ),
        ],
    ),
    "CorrelationId": (
        "Opaque string that travels with a request across services and log lines so a reader can stitch together the full call chain.",
        ["CorrelationContext", "StructuredLogger", "Tracer", "RpcInterceptor"],
        [
            (
                "Cross-service trail",
                ["RpcInterceptor", "CorrelationContext"],
                "Outbound RPCs inject the id; inbound middleware adopts it — the same string threads every hop regardless of transport.",
            ),
            (
                "Log-trace bridge",
                ["StructuredLogger", "Tracer"],
                "Logs and traces share the id; an SRE pivots between the two without re-querying by timestamp.",
            ),
            (
                "Audit correlation",
                ["AuditEvent", "AccessLog"],
                "Audit and access records carry the same id — forensic reconstruction is a join, not a reconstruction.",
            ),
        ],
    ),
    "ErrorSink": (
        "Capture uncaught exceptions with fingerprint grouping, attach current trace and correlation context, and forward to a sink for triage.",
        ["StructuredLogger", "Tracer", "CorrelationContext", "HealthProbe"],
        [
            (
                "Grouped triage",
                ["StructuredLogger", "Tracer"],
                "Exceptions are fingerprinted, deduped, and linked to the active span — one incident produces one issue, not one per request.",
            ),
            (
                "Context-rich capture",
                ["CorrelationContext", "CurrentPrincipal"],
                "Each captured error carries principal, correlation, and request context — reproducing the bug does not require the customer's cooperation.",
            ),
            (
                "Health integration",
                ["HealthProbe", "MetricMeter"],
                "Spike-based probes turn red on sudden exception rates; pages fire before synthetic checks notice.",
            ),
        ],
    ),
    "EventBus": (
        "In-process publish/subscribe point for named framework and application events with structured payloads.",
        ["LifecycleHook", "StructuredLogger", "EventEnvelope", "MetricMeter"],
        [
            (
                "Framework extensibility",
                ["LifecycleHook", "StructuredLogger"],
                "Lifecycle phases publish on the bus; plugins subscribe without patching core — observability hooks compose cleanly.",
            ),
            (
                "Telemetry fan-out",
                ["MetricMeter", "StructuredLogger"],
                "Metrics meters and log handlers subscribe to the same event without coupling; one source of truth drives multiple sinks.",
            ),
            (
                "In-process → bus bridge",
                ["EventEnvelope", "TopicBus"],
                "Internal events convert to envelopes at the edge; cross-process subscribers see the same semantics through the topic bus.",
            ),
        ],
    ),
    "HealthProbe": (
        "Expose a typed liveness / readiness signal that reflects the real state of the process and its dependencies.",
        ["LifecycleHook", "CircuitBreaker", "MetricMeter", "ResourceDescriptor"],
        [
            (
                "Readiness-gated traffic",
                ["LifecycleHook", "CircuitBreaker"],
                "Readiness flips false while dependencies warm up or a breaker stays open — the orchestrator drains traffic before the instance serves errors.",
            ),
            (
                "Real-state liveness",
                ["MetricMeter", "ResourceDescriptor"],
                "Liveness reflects in-process signals (deadlock detectors, GC stalls) rather than a 200 OK — zombie processes are reclaimed.",
            ),
            (
                "Dependency rollup",
                ["CircuitBreaker", "OutboundBinding"],
                "Outbound bindings report into the probe; readiness composes over real dependency health, not synthetic self-checks.",
            ),
        ],
    ),
    "HistogramBuckets": (
        "Define explicit latency and size bucket boundaries for histogram instruments so quantile estimation is stable across versions.",
        ["MetricMeter", "CardinalityGuard", "SemanticAttributes", "SamplingPolicy"],
        [
            (
                "Stable quantiles",
                ["MetricMeter", "SemanticAttributes"],
                "Fixed buckets let alerts on p99 compare like-for-like across deploys; a silent bucket change cannot invalidate the SLO.",
            ),
            (
                "Budgeted cardinality",
                ["CardinalityGuard", "MetricMeter"],
                "Bucket count × label cardinality is bounded at registration — the metrics bill does not drift with the codebase.",
            ),
            (
                "Aligned sampling",
                ["SamplingPolicy", "Tracer"],
                "Tail-based sampling uses the same buckets as histogram boundaries; retained traces line up with the outlier tail of the distribution.",
            ),
        ],
    ),
    "LifecycleHook": (
        "Named callback fired at a defined application phase (starting, ready, stopping) so tools can initialize and drain in order.",
        ["HealthProbe", "EventBus", "DiContainer", "ResourceDescriptor"],
        [
            (
                "Ordered startup",
                ["DiContainer", "HealthProbe"],
                "Hooks fire in dependency order; readiness flips true only after every 'ready' hook returns — no premature traffic.",
            ),
            (
                "Graceful shutdown",
                ["HealthProbe", "EventBus"],
                "Stopping hooks drain queues, flush telemetry, close connections — SIGTERM-to-exit is a predictable sequence, not best effort.",
            ),
            (
                "Self-describing process",
                ["ResourceDescriptor", "StructuredLogger"],
                "Hooks emit phase events with the resource descriptor attached — deploys and rollouts appear as discrete events in the log stream.",
            ),
        ],
    ),
    "LlmTrace": (
        "Emit structured spans for each model call with attributes aligned to OpenTelemetry GenAI semantic conventions.",
        ["Tracer", "SemanticAttributes", "PromptTemplate", "SamplingPolicy"],
        [
            (
                "GenAI-conventional spans",
                ["Tracer", "SemanticAttributes"],
                "Every model call emits a span with gen_ai.* attributes; dashboards across services line up without per-app mapping.",
            ),
            (
                "Template-attributed cost",
                ["PromptTemplate", "MetricMeter"],
                "Spans carry template name + version; cost attribution is per template — A/B prompt changes show as cost deltas.",
            ),
            (
                "Tail-sampled outliers",
                ["SamplingPolicy", "OutputGuardrail"],
                "Slow or rejected generations are always retained; normal traffic is sampled — the debug corpus stays representative.",
            ),
        ],
    ),
    "MetricMeter": (
        "Record numeric measurements through four instrument shapes — counter, up-down counter, histogram, async gauge — with explicit label schemas.",
        ["HistogramBuckets", "CardinalityGuard", "SemanticAttributes", "TelemetryExporter"],
        [
            (
                "Safe instruments",
                ["HistogramBuckets", "CardinalityGuard"],
                "Every instrument declares buckets and bounded labels; stability across deploys is mechanical, not cultural.",
            ),
            (
                "Conventional attribute schema",
                ["SemanticAttributes", "TelemetryExporter"],
                "Labels use OTel semconv keys; exports land in dashboards without a per-service mapping layer.",
            ),
            (
                "SLO-grade signal",
                ["HealthProbe", "SamplingPolicy"],
                "The same histograms drive readiness thresholds and tail sampling; SLO math is one query.",
            ),
        ],
    ),
    "ResourceDescriptor": (
        "Describe the entity producing telemetry — service, version, deployment environment, instance id — and attach it to every emitted signal.",
        ["TelemetryExporter", "SemanticAttributes", "HealthProbe", "LifecycleHook"],
        [
            (
                "Uniform telemetry identity",
                ["TelemetryExporter", "SemanticAttributes"],
                "Every span, metric, and log carries the same resource attributes; dashboards filter by service.version without ad-hoc tagging.",
            ),
            (
                "Deployment correlation",
                ["LifecycleHook", "StructuredLogger"],
                "Startup hooks stamp the descriptor into ready events; regressions line up with deploy boundaries in the log stream.",
            ),
            (
                "Probe-visible identity",
                ["HealthProbe", "Tracer"],
                "Probes report the descriptor alongside health; on-call sees 'which instance of which version' at a glance.",
            ),
        ],
    ),
    "SamplingPolicy": (
        "Decide whether a given trace or span is retained, combining head-based and tail-based rules for a predictable observability bill.",
        ["Tracer", "HistogramBuckets", "TelemetryExporter", "LlmTrace"],
        [
            (
                "Budgeted retention",
                ["Tracer", "TelemetryExporter"],
                "Head-based sampling caps volume at ingress; tail-based rules always retain errors and outliers — the bill is bounded without losing the interesting tail.",
            ),
            (
                "Outlier-biased traces",
                ["HistogramBuckets", "LlmTrace"],
                "Tail samplers bias toward spans in the slow-tail bucket; GenAI anomalies are always inspectable after the fact.",
            ),
            (
                "Per-service policy",
                ["ResourceDescriptor", "Tracer"],
                "Policies are keyed by resource descriptor; a noisy service throttles without dragging neighbors.",
            ),
        ],
    ),
    "SemanticAttributes": (
        "Expose OpenTelemetry semantic-convention attribute keys as typed constants and enforce that primitives emit only conventional keys.",
        ["Tracer", "MetricMeter", "StructuredLogger", "CardinalityGuard"],
        [
            (
                "Convention-over-string",
                ["Tracer", "MetricMeter"],
                "Every span/metric uses typed keys (http.request.method, db.system.name); a typo is a compile error, not a dashboard mystery.",
            ),
            (
                "Portable dashboards",
                ["StructuredLogger", "TelemetryExporter"],
                "Logs, spans, and metrics agree on attribute names across services; dashboards migrate between backends without rewrites.",
            ),
            (
                "Cardinality-safe by construction",
                ["CardinalityGuard", "HistogramBuckets"],
                "Each typed key declares its cardinality budget — review happens at the source, not on the billing page.",
            ),
        ],
    ),
    "StructuredLogger": (
        "Emit machine-parseable key/value log records with a fixed level taxonomy and attached trace/span ids.",
        ["CorrelationContext", "Tracer", "SemanticAttributes", "CardinalityGuard"],
        [
            (
                "Queryable logs",
                ["SemanticAttributes", "CardinalityGuard"],
                "Fields are typed and bounded; log aggregation scales without a cardinality-cliff incident.",
            ),
            (
                "Trace-bound context",
                ["Tracer", "CorrelationContext"],
                "Each record carries trace + correlation ids; a slow span's logs are one join away.",
            ),
            (
                "Error forensics",
                ["ErrorSink", "StructuredLogger"],
                "Errors are captured with their log trail; reproducing a failure is a matter of filtering the stream, not ssh'ing to a pod.",
            ),
        ],
    ),
    "TelemetryExporter": (
        "Serialize batched spans, metrics, or log records into an OTLP-compatible envelope and deliver them to a collector with backoff.",
        ["Tracer", "MetricMeter", "ResourceDescriptor", "CircuitBreaker"],
        [
            (
                "OTLP contract",
                ["Tracer", "MetricMeter"],
                "All signal types share a serializer; swapping backends is a collector-config change, not a code change.",
            ),
            (
                "Backpressure-aware",
                ["CircuitBreaker", "LoadShedder"],
                "Exporter fails fast when the collector is unavailable; telemetry loss is bounded instead of causing request-path slowdowns.",
            ),
            (
                "Self-describing batches",
                ["ResourceDescriptor", "SemanticAttributes"],
                "Every batch carries the resource descriptor; the collector attributes data to the right service without extra metadata.",
            ),
        ],
    ),
    "Tracer": (
        "Create spans that represent a unit of work, attach attributes and events, link related spans, and propagate context across boundaries.",
        ["SemanticAttributes", "SamplingPolicy", "CorrelationContext", "TelemetryExporter"],
        [
            (
                "End-to-end traces",
                ["CorrelationContext", "SemanticAttributes"],
                "Spans inherit context across threads, tasks, and RPCs; attribute keys come from semconv — distributed traces line up without per-service wiring.",
            ),
            (
                "Budgeted observability",
                ["SamplingPolicy", "TelemetryExporter"],
                "Sampling controls volume; exporter handles delivery; the product gets a representative, bounded trace stream.",
            ),
            (
                "Debuggable errors",
                ["ErrorSink", "StructuredLogger"],
                "Uncaught exceptions attach to the active span; the error triage UI links to the full trace and log trail.",
            ),
        ],
    ),
}
