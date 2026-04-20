# SamplingPolicy

## What it does (plain language)

SamplingPolicy decides which traces to keep and which to drop, coherently
across a whole trace (never a single span alone). Ingest cost stays bounded,
error-heavy traces are always kept, and p99 debugging still works. Product
impact: observability spend caps while high-value traces remain visible.

## Purpose

Decide whether a given trace or span is retained, combining head-based
(at span start) and tail-based (post hoc) rules, honoring the parent sampling
decision.

## When to use and when NOT to use

- USE: one policy per tracer, composed from built-in `ParentBasedHeadSampler`,
  `AlwaysOnSampler`, `AlwaysOffSampler`, or a custom Protocol implementation.
- DO NOT USE: per-span random draws — that shatters traces.
- DO NOT USE: after spans are exported — tail decisions must precede export.

## Invariants

| ID | Rule |
|---|---|
| SAMP_INV_01 | Parent sampled → child MUST inherit unless policy declares parent-overriding. |
| SAMP_INV_02 | Decisions SHALL be deterministic for the same trace_id. |
| SAMP_INV_03 | Probabilistic sampling MUST use trace_id hash; NEVER per-span draw. |
| SAMP_INV_04 | Policies CANNOT raise; failure falls back to default deny + counter. |
| SAMP_INV_05 | Tail-based decisions MUST NOT retroactively modify exported spans. |
| SAMP_INV_06 | description() stable, NEVER includes secrets or high-cardinality values. |

## Thread safety

Sampling decisions are pure functions of their inputs; no shared mutable state
beyond the fallback counter, which is atomically incremented.

## Operational characteristics

- Decision cost: O(1) hex parse + comparison.
- Fallback-deny on exception path: `sampler.fallback.count{reason}` exposes
  policy bugs; alert on sustained non-zero rate.
- Policy description: printed to configuration logs at startup; stable string
  is safe to diff across deployments.

## Security considerations

- `description()` is explicitly free of secrets and cardinality-exploding
  values — it is published in configuration dumps.
- Failure mode is fail-closed (deny-by-default) to avoid accidental full-volume
  retention on bugs.

## Provenance

- Source agent: Agent #7 OBSERVABILITY.
- OpenTelemetry Specification 1.32 — Sampling, Sampler and ParentBased.
- *Observability Engineering* (2022), chapter 17.
- Google SRE Book chapter 6 section on sampling.

## Alternatives considered and rejected

- 100% sampling — rejected: storage and egress scale linearly without bound.
- Random per-span sampling — rejected: shatters traces into incomplete subtrees.
- Client-side header-only sampling — rejected: error-only decisions need span-time evaluation.

## Extension contract

Downstream tools compose a new policy by implementing the `SamplingPolicy`
Protocol and registering it with the `TracerProvider`. Composite policies chain
via the compose adapter (latency-threshold OR error-seen OR head-probability)
and trace-state propagation is preserved by returning the caller's trace_state
unchanged when undecided.

## Usage

```python
def build_sampler(head_ratio: float, keep_errors: bool) -> SamplingPolicy:
    class Combined:
        def should_sample(self, *, parent_context, trace_id, name, kind, attributes, links):
            if keep_errors and attributes.get("error") is True:
                return SamplingDecision(True, {"sampler.reason": "error"}, None)
            keep = int(trace_id[-8:], 16) / 0xFFFFFFFF < head_ratio
            return SamplingDecision(keep, {"sampler.reason": "head"}, None)
        def description(self) -> str:
            return f"combined(head={head_ratio}, errors={keep_errors})"
    policy: SamplingPolicy = Combined()
    return policy
```

## Compose with:

- **Budgeted retention** → `Tracer` + `TelemetryExporter`
  Head-based sampling caps volume at ingress; tail-based rules always retain errors and outliers — the bill is bounded without losing the interesting tail.

- **Outlier-biased traces** → `HistogramBuckets` + `LlmTrace`
  Tail samplers bias toward spans in the slow-tail bucket; GenAI anomalies are always inspectable after the fact.

- **Per-service policy** → `ResourceDescriptor` + `Tracer`
  Policies are keyed by resource descriptor; a noisy service throttles without dragging neighbors.
