# HuGR SkillKit — Roadmap

> **Companion to `PRODUCT.md`.** PRODUCT.md describes the contract; this
> doc describes where we are and how we get there.
>
> **Last audited:** 2026-04-19 (Opus research + Explore audit).
> **Next review:** at end of every phase.

---

## Part 1 — Brutal ground truth (where we are today)

From a clean, agent-driven audit of the repo:

### What exists and works

- **One skill** (SKILL-001-fastapi-production) with a runnable FastMCP
  server.
- **~97 slice tools** under `adapt/extend/` (SKILL.md claim of 123 is
  inflated).
- **~33-45 generators** in `generators/` (SKILL.md claim of 52 is
  inflated).
- **~93 catalog-derived primitives** in `core/venous/<ns>/<Name>/` with
  real manifests, tests, TLA+ specs, invariants.
- **~10 primitives promoted from `_extracted/` staging** to
  production via the extraction pipeline.
- **~430 primitives staged in `core/venous/_extracted/`** — raw lifted,
  HuGR-shelled, T0-compile-green, but with `REPLACE_ME` stubs and no
  real tests.
- **Extraction pipeline** (`engine/extraction/`) — 8 modules, all green,
  idempotent, proven to scale to 500 primitives in seconds.
- **97 primitives audited via Opus** — 54 real bugs found and fixed
  during this session.
- **MCP tool auto-discovery** for adapt tools (via `MCP_TOOL` metadata
  scan).

### What is aspirational or broken

- **SKILL.md drift**: claims 175 MCP tools total, 3000+ tests, 35/35
  audit, 200+ cross-composition scenarios. Few of these hold up against
  a fresh count.
- **Primitives are orphaned from tools**: zero `from core.venous import`
  in `adapt/extend/*.py`. The Rails-style connection the product
  promises does not exist in code yet.
- **No registry**: `engine/primitives_by_concern.yaml` does not exist.
  Maestro cannot query "what's available for event sourcing?".
- **No composition recipes**: zero matches for "Compose with:" / "See
  also" across primitive `.md` files. Each primitive stands alone with
  no pointer to siblings.
- **Generators require manual registration** in `mcp_tools/generators.py`
  — 33+ hardcoded `@mcp_app.tool` decorators. Not auto-discovered.
- **`/examples/` is empty.** No real apps demonstrate the kit.
- **No `README.md`** at repo root. SKILL.md is the only entry point and
  it drifts.
- **No `install.sh`.** Dockerfile exists but untested end-to-end.
- **No Maestro benchmark harness.** Zero measurement of "does this
  actually help an LLM ship a SaaS".

### Honest summary

Roughly **80% infrastructure, 20% connected integration**. The pieces
exist in isolation; the Rails-analogy connection (tools reference
primitives, primitives have a registry, Maestro composes from index)
is not yet present.

---

## Part 2 — The phased plan

### Principles governing the roadmap

1. **Reality before volume.** Every phase closes an audit gap before
   adding new surface area. No more aspirational claims.
2. **Measure, don't speculate.** Phase 3 delivers a Maestro benchmark.
   From Phase 3 forward, every primitive / tool / recipe added must be
   justified by a benchmark gap.
3. **Composition is load-bearing.** A primitive without a recipe in
   its `.md` is incomplete. A tool without a reference to its
   composed primitives is incomplete.
4. **Zero ceremony for extraction.** The `_extracted/` staging area is
   a repository of future Lego, not a backlog obligation. Promote only
   what the benchmark asks for.

### Phase 0 — Ground truth + docs honesty (week 1)

Single-session sprint. Zero new features. Zero Maestro invocation cost.

1. **Publish `PRODUCT.md`** (this session).
2. **Publish `ROADMAP.md`** (this session).
3. **Replace SKILL.md** with a version that matches ground truth
   (real tool counts, real primitive counts, cite PRODUCT.md and
   ROADMAP.md rather than re-stating claims).
4. **Write `README.md`** at repo root: one-screen elevator + link to
   PRODUCT.md + ROADMAP.md.
5. **Update CLAUDE.md** memory pointer to reference PRODUCT.md so every
   future session starts from the canonical doc.
6. **Audit `/benchmark/`** — verify what tests actually pass. Delete
   stubs. Don't lie.

**Exit criteria:** every top-level .md in the repo maps to a verifiable
claim. Claim-vs-reality drift = 0.

---

### Phase 1 — Reconnect primitives to tools (weeks 2-3)

Turn the Rails-analogy promise into code. Without this, the kit is
Yeoman.

7. **Primitives-by-concern registry.** Write
   `engine/primitives_by_concern.yaml` — one entry per primitive,
   keyed by concern (`auth`, `data.persistence`, `observability`,
   `resiliency`, etc.), with:
   - name, namespace, 1-line purpose, composition hints (2-3 sibling
     primitives commonly paired with it).
   The registry is machine-readable AND human-scannable.
8. **Composition recipes in primitive `.md`.** Every production
   primitive (~103) gets a "Compose with:" section showing 2-3
   concrete pairings with sibling primitives. Example:
   `SignatureVerifier` + `IdempotentConsumer` + `AuditEvent` →
   "webhook receiver with single-delivery guarantee + tamper-evident
   audit trail."
9. **Connect 15 top-value tools to primitives.** Pick the 15 most-used
   tools (crud, auth_jwt, stripe_webhook, rate_limiting, migration,
   celery_task, audit_log, rbac, soft_delete, pagination, feature_flags,
   cache_layer, retry_budget, graceful_shutdown, observability-stack).
   Refactor each to EMIT code that imports from `core.venous.*`
   instead of inlining. Each tool shrinks ~50%.
10. **MCP tool responses cite primitives.** After a tool runs, its
    response (visible to the Maestro) lists the primitives the emitted
    code imports — so the Maestro can compose further.
11. **Generator auto-discovery.** Rewrite `mcp_tools/generators.py` to
    auto-scan `generators/` for `MCP_TOOL` metadata, same pattern as
    adapt tools. Eliminate the 33-line manual-registration drift.

**Exit criteria:** `grep -rE 'from core.venous' adapt/extend/*.py |
wc -l` returns ≥15. Registry YAML exists. ≥95 primitives have
composition sections. Generators are auto-discovered.

---

### Phase 2 — Discoverability layer (week 4)

Turn the registry into runtime Maestro-queryable APIs.

12. **`find_primitive` MCP tool.** Exposes
    `find_primitive(concern: str, query: str) -> list[PrimitiveHit]`
    backed by the registry YAML. Maestro uses it as the JIT discovery
    mechanism (Tool Search pattern, per LLM research).
13. **`suggest_composition` MCP tool.** Given a natural-language intent
    ("webhook with dedup + audit"), returns a ranked list of primitive
    combinations from the registry + recipe index. Pure retrieval; no
    LLM call.
14. **Primitive reference docs site.** Use `mkdocs` or `mintlify` to
    auto-generate per-primitive pages from `.md` + contract.json.
    Rails-API-docs style: one URL per primitive, with signature +
    invariants + compose-with links. Host on Vercel / Mintlify / GH
    Pages.

**Exit criteria:** Maestro (in a Claude Desktop session) can type
"I need to dedupe webhooks and sign the output" and receive back a
ranked composition of real primitives. Reference docs live at a URL.

---

### Phase 3 — Maestro benchmark harness (weeks 5-6)

The instrument we've needed since day one. Without it, every "SOTA"
claim is unfalsifiable.

15. **Define 20 benchmark specs.** Plain-English product requirements:
    - 5 baseline (crud-only, auth-only SaaS, webhook sink, rate-
      limited public API, basic multi-tenant admin).
    - 10 mid-complexity (SaaS with auth + Stripe billing, realtime
      chat, event-sourced order service, RBAC with audit, LLM agent
      backend, mobile-backend-as-a-service, compliance-critical log
      aggregator, GraphQL layer on top of REST, workflow
      orchestrator, BI export service).
    - 5 adversarial (spec with rare edge case, spec with internal
      contradiction, spec requiring two conflicting primitives to
      coexist, spec requiring a primitive we don't have yet, spec
      with hidden scaling requirement).
16. **Scoring rubric.** Per spec: scaffold completeness (25%), test
    suite pass (25%), T0-T9 gate pass on a sample of imported
    primitives (25%), hand-editability (25%, human-judged). 0-100
    scale.
17. **Benchmark runner.** A harness that invokes a Claude Sonnet /
    Opus Maestro against the skill's MCP server, records the session
    transcript + the produced codebase, and scores. Runs nightly in
    CI.
18. **Publish baseline score.** Run today's kit against all 20 specs,
    publish the score honestly. This becomes the north star.

**Exit criteria:** Baseline benchmark score exists. Reproducible. Any
future primitive / tool / recipe addition must cite which benchmark
scenario moved from red to green.

---

### Phase 4 — Productize SKILL-001 for real users (weeks 7-9)

Now it's worth inviting users.

19. **`install.sh` + CI.** End-to-end installation in a fresh Docker
    container, verified in GitHub Actions. Clone → install → run
    benchmark → publish score badge.
20. **`/examples/` populated.** 5 real apps built by Maestro using the
    kit, with sessions recorded for reference. Each example has a
    README linking to the primitives + tools it composed.
21. **Docs site v1.** PRODUCT.md + ROADMAP.md + per-primitive reference
    + per-tool reference + "Compose with" cross-links. Versioned per
    release.
22. **Semantic versioning + changelog.** v0.1.0 ships with the
    benchmark score and signed changelog.
23. **Contribution guide.** `CONTRIBUTING.md` explaining how to add
    a primitive (passes the 10-tier gate) and how to add a tool
    (passes the adapt contract + composes ≥1 primitive).

**Exit criteria:** `curl <install.sh> | bash` in a fresh Docker works.
Benchmark score is visible on the README. External contributor can
land their first primitive.

---

### Phase 5 — Fill gaps from benchmark (ongoing)

Every new primitive / tool / recipe must cite a benchmark gap it closes.

24. **Weekly benchmark review.** Which scenarios are still red?
    Diagnose: missing primitive, missing tool, missing recipe, flawed
    scaffold?
25. **Surgical additions only.** No more preemptive extraction. The
    `_extracted/` staging area serves as a pre-audited pool to draw
    from when benchmark says "we need a primitive for X".
26. **Target score: 70% by v1.0.** Ship v1.0 of SKILL-001 when
    benchmark hits ≥70%.

---

### Phase 6 — Second skill (month 3+)

Only after SKILL-001 hits 70% benchmark.

27. **SKILL-002 choice driven by demand.** Candidates: Next.js
    production frontend, Django lightweight backend, backend-for-
    LLM-agents. Choose based on inbound user interest / benchmark
    coverage gaps.
28. **Shared primitives across skills.** The `core/venous/` namespace
    is framework-agnostic where possible (e.g., `SignatureVerifier`
    works in FastAPI AND Django). Each skill brings framework-
    specific tools + a few framework-specific primitives.
29. **Multi-skill Maestro.** The Maestro picks the right skill for the
    task (FastAPI backend + Next.js frontend = two skills invoked in
    one session).

---

### Phase 7 — Ecosystem (month 6+)

30. **Community primitives with enforced gates.** External PRs land
    primitives that pass the T0-T9 gate + Opus audit.
31. **Benchmark scoreboard public.** Every release's score is visible.
    Marketing writes itself.
32. **SDK for Maestro authors.** If someone wants to build a different
    Maestro agent, they ship against the skill's MCP surface.

---

## Part 3 — Honest risks

- **Maestro success ceiling.** If even 70% benchmark is unattainable with
  current LLM capabilities, the whole thesis fails. De-risk by testing
  5 benchmarks manually before investing in full 20-spec harness.
- **Framework churn.** FastAPI / Pydantic make breaking changes. Skill
  maintenance cost is real. Mitigate by pinning versions per skill
  release and running the benchmark nightly.
- **Rails-analogy limits.** Rails has 20 years of community + a human-
  first runtime. HuGR is LLM-first. The analogy is a design lodestar,
  not a promise of equivalent ergonomics.
- **Generator ≠ tool drift.** Historical naming is messy (generators vs
  tools). Every phase tightens the terminology. If we fail to enforce,
  confusion returns.

---

## Part 4 — What to do RIGHT NOW

**This session's deliverables** (Phase 0, steps 1-5):

- ✅ PRODUCT.md (this session)
- ✅ ROADMAP.md (this session)
- ⏳ `SKILL.md` rewrite (next)
- ⏳ `README.md` at repo root (next)
- ⏳ `CLAUDE.md` memory pointer update (next)

**Next session (Phase 0, step 6 + Phase 1 start):**

- Audit `/benchmark/` tests; delete stubs; commit honest count.
- Write `engine/primitives_by_concern.yaml` (registry).
- Start composition-recipe pass on the 10 most-important primitives.

That's the next 10 days. Phase 1 completes by week 3 if we hold
discipline. Phase 3 baseline benchmark score by week 6. v1.0 ship by
month 3.
