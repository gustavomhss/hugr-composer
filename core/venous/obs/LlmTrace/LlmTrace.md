# LlmTrace

## What it does (plain language)

LlmTrace records one structured span per LLM model call, tagged with the model
identity, prompt fingerprint, token usage, and finish reason — all using the
attribute names mandated by the OpenTelemetry GenAI semantic conventions
(1.27+). Engineers can then answer cost, latency, and quality questions with
one query across every model, every provider, and every dashboard backend.
Tool-calls initiated by the model nest as child spans under the model span so
the causal chain is fully reconstructable end-to-end.

## Purpose

Emit structured spans for each model call with attributes aligned to
OpenTelemetry GenAI semantic conventions so token counts, model identity, and
prompt/response linkage land in traces consistently.

## When to use and when NOT to use

- USE: every provider API call (completion, embeddings, tool invocation,
  streaming generation); child tool-call spans for agent reasoning.
- DO NOT USE: raw HTTP tracing — that is the general `Tracer` primitive.
- DO NOT USE: storing full prompt / response content for audit — pair with
  `AuditEvent` for tamper-evident records, and keep LlmTrace privacy-first.

## API surface

The catalog `api_signature` is the sole authority; see
`LlmTrace.contract.json` for the verbatim Protocol declaration.
`LlmTrace.start(operation, model_handle, prompt_fingerprint)` returns a
context manager yielding an `LlmSpan`. The span exposes `set_usage`,
`set_finish_reason`, and `record_error`. Optional extended methods
(`set_cache_usage`, `set_temperature`) map to additional OTel GenAI attrs.

## Invariants

| ID | Rule |
|---|---|
| LLMTRACE_INV_01 | Every model call SHALL open exactly one LlmTrace span; unspanned calls are FORBIDDEN. |
| LLMTRACE_INV_02 | Span attribute names MUST use OpenTelemetry GenAI SemConv (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, cache_read/cache_creation token variants). |
| LLMTRACE_INV_03 | Spans MUST record `prompt_fingerprint` so the trace can be correlated with the PromptTemplate version that generated it. |
| LLMTRACE_INV_04 | On provider error the span MUST call `record_error` before exiting; swallowing the error without recording is FORBIDDEN. |
| LLMTRACE_INV_05 | Child tool-call spans MUST nest under the model-call span so the causal chain is reconstructable end-to-end. |

## Invariant → test mapping

Each invariant is covered by three tests named
`test_inv_<slug>_{confirms,prevents,under_failure}`. See
`invariant_bindings.json` for the authoritative binding.

## Thread and async safety

- All `LlmSpan` mutating methods (`set_usage`, `set_finish_reason`,
  `record_error`, `set_cache_usage`, `set_temperature`, `end`) are
  thread-safe via an internal lock.
- `InMemoryLlmTrace.start` is safe under concurrent callers; each call
  returns an independent span, and parent / child nesting is resolved against
  a tracer-local stack.

## Operational characteristics (for SRE)

- Span creation is non-blocking; an adapter-based OTLP exporter is the
  expected production deployment.
- Self-observability metrics: `llmtrace.spans.created`,
  `llmtrace.tokens.input`, `llmtrace.tokens.output`,
  `llmtrace.cache.hit_ratio`, `llmtrace.provider.errors`.
- Cardinality: `model` label is intentionally present; guard it behind
  `CardinalityGuard` when onboarding new providers.

## Security and privacy considerations

- **Privacy-first by construction.** The reference tracer NEVER attaches
  prompt or response content. Only the `prompt_fingerprint` (a hash of the
  rendered prompt + template version) is attached. Callers who need content
  capture MUST explicitly opt in via `InMemoryLlmTrace(capture_content=True)`
  and are responsible for downstream redaction.
- `gen_ai.error.message` is written only with the exception class name by
  default to avoid leaking provider-supplied strings that may echo prompt
  content. Opt-in content capture expands it to `str(exc)`.
- `record_error` is the ONLY channel to annotate failure; silent swallow is
  forbidden by LLMTRACE_INV_04 and enforced by auto-recording on exception
  propagation.

## Provenance

- Source agent: Agent #8 LLM_ERA
  (`docs/research/outputs/AGENT_8_LLM_ERA.json`).
- Primary sources:
  - OpenTelemetry Semantic Conventions for Generative AI (1.27+) —
    `gen_ai.*` attribute namespace.
  - Langfuse 2.x — Trace / Observation / Generation hierarchy with
    prompt_version linkage.

## Alternatives considered and rejected

- Plain log lines per call — no span hierarchy, no vendor-neutral attribute
  names.
- Vendor-specific SDK tracing only — locks observability to one provider's
  schema.

## Extension contract

The trace core is a thin adapter over an OpenTelemetry tracer; projects add
exporters (OTLP, Langfuse, vendor-specific) by registering them against the
OTel provider without modifying call-site code. Extensions MUST preserve the
five invariants above; content capture MUST remain opt-in.

## Schema of `LlmTrace.contract.json`

The contract file is a verbatim copy of the `PrimitiveSpec` dict from the
research catalog (`docs/research/outputs/AGENT_8_LLM_ERA.json`). Fields:
`name`, `namespace`, `purpose`, `api_signature`, `invariants[]`,
`extension_contract`, `consumption_example`, `sources[]`, `why_essential`,
`alternatives_considered[]`, `maturity`.

## Usage

```python
def call_model(tracer: LlmTrace, fp: str) -> None:
    # INV-03: prompt_fingerprint is required; INV-02: attribute names are
    # OTel GenAI SemConv. INV-04: on error record_error auto-fires.
    with tracer.start("completion", "planner-v2", fp) as span:
        span.set_usage(1200, 340)
        span.set_finish_reason("stop")
```

## Compose with:

- **GenAI-conventional spans** → `Tracer` + `SemanticAttributes`
  Every model call emits a span with gen_ai.* attributes; dashboards across services line up without per-app mapping.

- **Template-attributed cost** → `PromptTemplate` + `MetricMeter`
  Spans carry template name + version; cost attribution is per template — A/B prompt changes show as cost deltas.

- **Tail-sampled outliers** → `SamplingPolicy` + `OutputGuardrail`
  Slow or rejected generations are always retained; normal traffic is sampled — the debug corpus stays representative.
