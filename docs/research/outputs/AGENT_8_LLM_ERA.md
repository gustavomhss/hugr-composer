# AGENT 8 — LLM_ERA

> Venous-system primitives for LLM-calling targets: prompt management,
> model registry, vector store, guardrails, HITL, evaluations, cost tracking,
> response cache, model routing, tool use, and standardized tracing.

## Scope recap

- **IN:** versioned prompts, model registry metadata, tenant-scoped vector store, input/output guardrails, human-in-the-loop checkpoints, eval harness with golden sets, per-tenant cost meter, response cache (exact + semantic), model router with fallback, tool schema with scope checks, GenAI-aligned tracing, budget enforcement, prompt-injection quarantine for untrusted context.
- **OUT:** Verbatim OpenAI/Anthropic/Google API surfaces, training or fine-tuning infrastructure, embedding-model comparison benchmarks.
- **Namespaces owned:** `llm`, `cost`, `obs`.

## Sources consulted

1. Anthropic Model Context Protocol (MCP) 1.x specification — Tools, Resources, Sampling.
2. OWASP Top 10 for LLM Applications (2023) — LLM01, LLM02, LLM06, LLM08, LLM09.
3. Langfuse 2.x architecture — Trace/Observation/Generation model, Prompt Management, Datasets + Evaluations.
4. Portkey gateway architecture (portkey-ai 1.x) — Routing strategies, Virtual Keys, usage headers.
5. Helicone gateway architecture — Cache feature, rate limits and cost ceilings.
6. LiteLLM 1.x unified completion — `Router` class, `model_cost_map.json`, fallbacks.
7. Weights & Biases Weave (weave-python 0.50+) — `weave.Prompt`, `weave.Evaluation`.
8. Weights & Biases Models (wandb 0.17+) — Model Registry with alias and metadata.
9. OpenTelemetry Semantic Conventions for Generative AI (1.27+) — `gen_ai.*` attributes.

## Primitives delivered (14)

### `llm` namespace

| Primitive | What it pins |
|---|---|
| `PromptTemplate` | Named + integer-versioned + variable-pinned prompts with a fingerprint that threads through traces, evals, and caches. |
| `ModelRegistry` | Logical handles to provider endpoints with capability tuples (context window, tool-use, streaming, modality). |
| `VectorStore` | `upsert` / `search` / `delete` with tenant scoping, dimension validation, and schema-constrained metadata filters. |
| `InputGuardrail` | Deterministic (+ optional judge) interceptor chain over user input; verdicts: allow / redact / block. |
| `OutputGuardrail` | Post-generation verdicts on model output against schema, policy, and safety before it reaches tools or users. |
| `HumanCheckpoint` | Blocks workflow until an authorized reviewer approves / rejects / edits a proposed action; default-deny on timeout. |
| `EvalHarness` | Golden dataset × prompt_version × model_handle → graded results; dataset mutations require a new version. |
| `ResponseCache` | Exact and semantic memoization with TTL, namespaced by tenant; cache-hit tokens reported to the meter. |
| `ModelRouter` | Policy-driven handle selection with quality floor, tenant overrides, and bounded failover chains. |
| `ToolSchema` | JSON-schema input, side-effect class, required scopes; `validate_arguments` is pure, execution is explicit. |
| `PromptInjectionFilter` | Wraps retrieved / tool-output / user content in data delimiters and strips instruction-like fragments. |

### `cost` namespace

| Primitive | What it pins |
|---|---|
| `TokenMeter` | Per-call ledger of prompt / completion / cache-read / cache-write tokens with tenant + feature labels. |
| `BudgetGuard` | Per-tenant, per-feature ceiling over a window; default-deny for unknown scopes; deterministic throttle. |

### `obs` namespace

| Primitive | What it pins |
|---|---|
| `LlmTrace` | Span-per-call using `gen_ai.*` attribute names; nests tool-call spans under model-call spans; errors must be recorded. |

## Cross-cutting insights

1. **Token accounting and budget enforcement share identity.** `TokenMeter` records what `BudgetGuard` decides against, and both pivot on the tenant/feature label pair used by `ModelRouter`.
2. **Prompt identity is the linchpin.** `PromptTemplate.fingerprint` threads through `EvalHarness` run records, `LlmTrace` span attributes, and `ResponseCache` keys so every observation pins to an exact text version.
3. **Defense against LLM01 injection is two-primitive.** `PromptInjectionFilter` wraps untrusted context; `InputGuardrail` rejects or redacts before prompt assembly. Neither is sufficient alone.
4. **Model substitution safety is a three-primitive contract.** `ModelRegistry` (capability truth) + `ModelRouter` (policy) + `BudgetGuard` (economic guardrail). Bypassing any of the three silently breaks reproducibility or cost controls.
5. **Output trust is the LLM02/LLM08 dividing line.** `OutputGuardrail` validates shape and safety before `ToolSchema.validate_arguments` gates side effects, and `HumanCheckpoint` inserts when the action is high-impact.
6. **OpenTelemetry GenAI attributes are the observability convergence point.** Langfuse, W&B Weave, Portkey, and Helicone can all ingest the same span data once `LlmTrace` aligns with `gen_ai.*`.
7. **Multi-tenancy is a non-local property.** `VectorStore`, `ResponseCache`, `TokenMeter`, and `BudgetGuard` each enforce tenant isolation; any single bypass is a cross-tenant data or cost leak.

## Gaps relative to SKILL-001

- No first-class `PromptTemplate` object with versioned fingerprint; prompts today are inline strings without diffable identity.
- No shared `VectorStore` primitive, so tenant scoping and deletion propagation are re-solved per feature.
- No `OutputGuardrail` chain wired to the tool-call dispatcher; LLM02 validation is implicit and per-endpoint.
- No `HumanCheckpoint`; high-impact actions that should require approval execute on model output alone.
- `TokenMeter` and `BudgetGuard` not factored out; cost attribution relies on post-hoc log parsing.
- `LlmTrace` not aligned with OTel GenAI semantic conventions, blocking vendor-neutral backends.
- No `PromptInjectionFilter`; retrieved documents and tool outputs concatenate into prompts without a quarantine step.

## Source coverage

| Source | Primitives citing |
|---|---|
| OWASP Top 10 for LLM Applications (2023) | 6 |
| Anthropic Model Context Protocol (MCP) 1.x specification | 4 |
| Langfuse 2.x architecture and tracing model | 4 |
| Portkey gateway architecture (portkey-ai 1.x) | 3 |
| Helicone gateway architecture (helicone.ai) | 2 |
| LiteLLM 1.x unified completion interface | 2 |
| Weights & Biases Weave (weave-python 0.50+) | 2 |
| OpenTelemetry Semantic Conventions for Generative AI (1.27+) | 2 |
| Weights & Biases Models (wandb 0.17+) | 1 |

No source dominates more than 24% of citations; diversity floor satisfied.

## Self-check

```
$ skills/SKILL-001-fastapi-production/.venv/bin/python \
    docs/research/contracts/check_deliverable.py \
    --agent 8 \
    --deliverable docs/research/outputs/AGENT_8_LLM_ERA.json
✓ DELIVERABLE VALID
  Agent 8 (LLM_ERA)
  Primitives: 14 (min 12)
  Unique sources: 9 (min 6)
  Insights: 7
  Gaps observed: 7
```
