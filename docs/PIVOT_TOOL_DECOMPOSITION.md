# Pivot: decompor EXTEND tools em primitives

> **Status:** proposed — 2026-04-19
> **Author:** Gustavo + Claude (design dialog)
> **Supersedes:** "continue derivando primitives do catálogo de pesquisa até N=113/200/300"

## The insight

The 100 EXTEND tools (`add_stripe_webhook`, `add_auth_jwt`, `add_crud_endpoint`, etc.) already
contain working, tested, production-used implementations of ~4-6 reusable patterns each.

A rough inventory of latent primitives per tool:

| Tool | Latent primitives |
|---|---|
| `add_stripe_webhook` | SignatureVerifier • IdempotentConsumer • DomainEvent • RetryPolicy • AuditEvent |
| `add_auth_jwt` | TokenIntrospector • SessionStore • MiddlewarePipeline • CurrentPrincipal |
| `add_crud_endpoint` | Pagination • FilterSpec • SortSpec • ResponseEnvelope • RequestContext |
| `add_database_migration` | SchemaDiff • DependencyGraph • RollbackLog • UnitOfWork |
| `add_rate_limiting` | RateLimiter • TokenBucket • KeyDerivation • StateStore |
| `add_celery_task` | WorkflowRun • DurableTimer • RetryPolicy • DeadLetterRoute |
| `add_stripe_subscription` | Subscription • Invoice • DunningPolicy • PaymentMethod |
| ... (93 more) | ... |

**Napkin math:** 100 tools × avg 4-6 latent primitives = **400-600 extractable primitives**.

## Why extraction beats derivation

| Axis | Derive from catalog (status quo) | Extract from tools (pivot) |
|---|---|---|
| Code correctness | LLM writes new; may regress | Already working in production |
| Token cost / primitive | ~80-150k (builder+gates) | ~5-15k (read + carve + lift) |
| Time / primitive | 4-15 min wall-clock | ~1-3 min |
| Battle-test level | T6/T9 LLM ensemble (theater) | Real users in real projects |
| Composition hints | Has to be invented | Already shown by tool usage |
| Bug discovery | Red-team simulation | Real bug reports |

**10-20× cheaper per primitive. More accurate. More composable. More real.**

## Effect on the library

- **Library size jumps 4-5×**: 113 → ~500 primitives in weeks instead of months.
- **Tools shrink ~5×**: after extraction, each EXTEND tool becomes thin orchestration (~50-100 lines) over primitive imports, instead of ~300-800-line self-contained scripts.
- **Cross-tool consistency** becomes automatic: fixing a primitive patches every tool that imports it. Today, 30 tools re-implement idempotency subtly differently.
- **Composition discovery is natural**: the agent LLM can read the tool source as an example of "how do I combine primitives to achieve X".

## Process

1. **Audit pass** — script walks every `add_*.py`, emits a candidate list per tool:
   `{tool: [(function_name, role, size_bytes, cross_tool_dupe?), ...]}`.
2. **Dedupe pass** — cluster candidates by signature similarity. If 30 tools carry an
   `idempotency_key` check, that is ONE primitive.
3. **Priority queue** — extract in order of (reuse_count × size). Top-10 extracted first
   deliver the biggest wins.
4. **Extraction** — for each unique candidate:
   - Lift the function/class into `core/venous/<namespace>/<PrimitiveName>/`
   - Wrap with the HuGR shell (Protocol + invariant_bindings + observability schema +
     short `.md`). No TLA+ required unless the primitive is genuinely stateful.
   - Minimal T0 + T1 gate only (not the full 10-tier: the code is already proven).
5. **Refactor tools** — replace inlined code with `from core.venous.* import ...`.
6. **Cross-check** — run the existing tool test suites after refactor. They must stay green.

## Maturity tiering for extracted primitives

Extraction is a different risk profile than derivation. New tier proposed:

- **`derived`** — invented from catalog, full 10-tier gate.
- **`extracted`** — lifted from tool, T0 + T1 + T7 only (static + behavioral + observability).
  Battle-testing level = however long the source tool has been in use.

This cuts gate cost per extracted primitive by ~80%.

## Open questions

1. **Catalog-vs-extracted overlap:** some primitives will be extracted AND already in the
   derived catalog. Merge policy: extracted wins for implementation, derived invariants
   stay.
2. **Licensing:** EXTEND tools are MIT/internal. Extracted primitives stay MIT. No issue.
3. **Ordering:** does the library need to FINISH the 113 derived set first, or pivot now?
   → See "Why start now" below.

## Why start the pivot NOW (not after finishing the 25)

Honest cost-benefit, no sugar:

- **25 remaining × ~80k tokens** (with OSS-aware briefings) = **2M tokens** to finish the catalog.
- **Same 2M tokens on extraction** yields **~400 primitives** (at ~5k each).
- 2M tokens on finishing the catalog gives 25 more primitives. 2M tokens on extraction gives
  400. **16× ROI difference.**
- The 4 builders still running (RateLimiter, InputGuardrail, OutputGuardrail, PromptInjectionFilter)
  will finish on their own — no reason to kill them. But stop dispatching NEW from-scratch
  builders.
- The derived-catalog primitives we already have (88/113) are sufficient to cover the
  critical categories (auth, resiliency, events, compliance, security). The remaining 25 are
  completeness nice-to-haves, not load-bearing.

**Recommendation:** let the 4 in-flight finish. Start the audit pass (step 1) in parallel
right now. Do not dispatch primitives 90-113 from scratch — extract their equivalents from
the tool corpus instead.

## Next immediate action

Write `engine/extraction/audit_tools.py`: scan every `adapt/extend/*.py`, produce a report
of latent primitives with dedupe signatures. Deliverable = `tools_latent_primitives.json`
ready for the dedupe and priority passes.
