# HuGR SkillKit — Roadmap

> **Companion to `PRODUCT.md`.** PRODUCT.md describes the contract; this
> doc describes where we are and how we get there.
>
> **Last audited:** 2026-04-21 (Opus, machine-verified via
> `engine.inventory` + `engine.audit.contract_check`).
> **Next review:** at end of every phase.
> **Canonical counts:** `skills/SKILL-001-fastapi-production/INVENTORY.md`.

---

## Part 1 — Ground truth (what actually exists, reconciled 2026-04-21)

Regenerate from the skill root with
`PYTHONPATH=. .venv/bin/python -m engine.inventory`. All numbers below
reconcile against INVENTORY.md — drift = audit bug.

### What exists and works

| Surface | Count | Notes |
|---|---:|---|
| MCP-registered tools on disk | 251 | Files with `MCP_TOOL` metadata scannable by `engine.index.manifest` |
| Tools indexed in `catalog.json` | 201 | Canonical `fastapi_<domain>_<verb>_<noun>` names |
| Tier-1 meta tools | 7 | home / search / describe / scaffold / compose / audit / verify |
| Tree dispatchers | 9 | auth, data, api, realtime, resiliency, observability, compliance, deployment, testing |
| Adapt tools | 126 | 100 extend / 8 evolve / 8 operate / 6 verify / 3 contracts / 1 proactive |
| Generators | 56 | auth, database, deployment, endpoints, infra, middleware, observability, schemas, testing, tools |
| Module packages | 28 | auth, background_jobs, caching, database, deployment, observability, payments, security, websockets |
| Registered primitives | 122 | `core/venous/<ns>/<Name>/` with contract.json + tests + TLA+ specs |
| FastAPI adapters | 16 | Production-wired in `core/venous/_adapters/fastapi/` |
| Staged primitives | 180 | PascalCase subset of `_extracted/`, surfaced in catalog as `status="staged"` |
| Quarantined primitives | 121 | Rejected by extraction gate, hidden from catalog |
| Recipes | 385 | Parsed from primitive `.md` `## Compose with:` sections |
| Benchmark specs | 20 | 5 baseline + 10 mid + 5 adversarial |
| Contract rules passing | 33/33 | Machine-verified by `engine.audit.contract_check` |

### What's done (formerly "aspirational")

- ✅ **Registry YAML** — `engine/primitives_by_concern.yaml` (Phase 1).
- ✅ **Composition recipes** — 385 recipes extracted from `## Compose with:` sections; BM25-searchable via `fastapi_meta_search_composition` (Phase 1+2).
- ✅ **MCP tool auto-discovery** — `MCP_TOOL` scan across adapt/, generators/, modules/, meta/, core/tools/, engine/discovery/ (Phase 1).
- ✅ **Discoverability layer** — `fastapi_meta_search` + `fastapi_meta_search_primitive` + `fastapi_meta_search_composition` (Phase 2).
- ✅ **Benchmark harness** — 20 specs, 4-dimension rubric, runner in `engine/bench/`, 6 live runs archived under `benchmarks/blind/results/` (Phase 3).
- ✅ **Plan-level baseline score** — 100.00 overall (best-of-ensemble v3). Honest caveat: this scores requirement→primitive/tool mapping, NOT executable behaviour (Phase 5 item).
- ✅ **install.sh + Dockerfile** — validated nightly in fresh `python:3.12-slim` via `.github/workflows/install-docker.yml` (Phase 4).
- ✅ **README.md + CLAUDE.md + PRODUCT.md + CONTRACT.md + CONTRIBUTING.md** at repo root (Phase 0+4).
- ✅ **SKILL.md v2** in Anthropic Agent Skills format (YAML frontmatter + ≤500-line body + 3 few-shot transcripts).
- ✅ **Tier-1 meta tools** (7) + **tree dispatchers** (9) + **fastapi_meta_compose** with 4-tier fallthrough (adapter_reuse > tool_delegate > recipe_template > ad_hoc).
- ✅ **Staged-primitive surface** — 180 pre-audited primitives visible to Maestro as `status="staged"`; `fastapi_meta_search` returns them so benchmark gaps can signal promotion needs.
- ✅ **Canonical naming** enforced across the entire surface. `fastapi_<domain>_<verb>_<noun>` with closed verb (9) and domain (10) vocabularies; manifest trusts author-declared canonical names.

### What's still open

- ⚠️ **Rails-vs-Yeoman rule (PRODUCT.md §6.1)** — only 18/100 `adapt/extend/` tools import from `core.venous.*`. The other 82 emit inline logic. ROADMAP Phase-1 item #9 remains open.
- ⚠️ **`/examples/`** — 5 directories, all empty. ROADMAP Phase-4 item #20 remains open.
- ⚠️ **Code-level benchmark** — current baseline is plan-level. ROADMAP Phase-5 needs an executable-run rubric (does `curl /health` actually return 200 from the emitted code?).
- ⚠️ **Extraction promotion queue** — 180 staged primitives visible but the promotion pipeline isn't triggered by benchmark signals yet. Phase-5 item #25 still open.

### Honest summary

The Rails-analogy pieces are ALL present now: macro scaffold (SKILL-001),
slice generators (adapt + generators + modules), a primitive catalogue
(`primitives_by_concern.yaml` + 385 recipes), discoverability
(`fastapi_meta_search`), and LLM-first composition
(`fastapi_meta_compose`). The remaining work is integration discipline
(82 tools still emit inline logic, violating §6.1), concrete examples
(5 empty dirs), and code-level behavioural scoring.

Infrastructure: **~98% complete**. Integration discipline: **~20%
complete** (18/100 extend tools wire primitives).

---

## Part 2 — The phased plan

### Principles governing the roadmap

1. **Reality before volume.** Every phase closes an audit gap before
   adding new surface area. No aspirational claims; `engine.inventory`
   is the source of truth.
2. **Measure, don't speculate.** Phase 3 delivered a benchmark harness.
   From Phase 3 forward, every primitive / tool / recipe added must be
   justified by a benchmark gap it moves from red to green.
3. **Composition is load-bearing.** A primitive without a `Compose with:`
   section is incomplete. A tool without `primitives_used` (real import
   OR templated-string import) is incomplete.
4. **Staging ≠ backlog.** The 180 `_extracted/` primitives are a
   pre-audited pool. Surface them (done), but promote only what a
   benchmark gap asks for.

### Phase 0 — Ground truth + docs honesty ✅ DONE

Originally scoped as single-session sprint. Outcome: PRODUCT.md (canonical
contract), ROADMAP.md, CONTRACT.md, CONTRIBUTING.md at repo root; README.md
rewritten; SKILL.md rewritten to v2 Agent Skills format; CLAUDE.md pointer
updated; STATUS.md for human-audience counts.

### Phase 1 — Reconnect primitives to tools (partially complete)

Rails-analogy wiring. **~80% complete, 1 key item open**.

| # | Item | Status |
|---|---|---|
| 7 | Primitives-by-concern registry (`engine/primitives_by_concern.yaml`) | ✅ done |
| 8 | Composition recipes in primitive `.md` (385 extracted) | ✅ done |
| 9 | **Connect 15 top-value extend tools to import `core.venous.*`** | ⚠️ **18/100 — open** |
| 10 | MCP tool responses cite composed primitives | ✅ done (`primitives_used` populated via AST + string-scan) |
| 11 | Generator auto-discovery via `MCP_TOOL` | ✅ done |

**Open work for Phase 1 closeout (#9):**
Refactor at least 15 high-leverage extend tools so their emitted code
uses `from core.venous.<ns>.<Name>` instead of inlining. Candidates (per
ROADMAP original list): crud, auth_jwt, stripe_webhook, rate_limiting,
migration, celery_task, audit_log, rbac, soft_delete, pagination,
feature_flags, cache_layer, retry_budget, graceful_shutdown,
observability-stack. Each tool shrinks ~50% on refactor.

**Exit criteria for Phase 1 closeout:**
`grep -rlE "^from core\.venous|from core\.venous" adapt/extend/*.py | wc -l`
≥ 35 (currently 18). Enforce going forward via a contract rule.

### Phase 2 — Discoverability layer ✅ DONE

| # | Item | Status |
|---|---|---|
| 12 | `find_primitive` MCP tool (BM25 over registry) | ✅ `fastapi_meta_search_primitive` |
| 13 | `suggest_composition` MCP tool (BM25 over recipes) | ✅ `fastapi_meta_search_composition` |
| 14 | Primitive reference docs site | ✅ `engine/docs/build.py` emits deterministic HTML |

Bonus delivered beyond original scope: unified `fastapi_meta_search`
tier-1 tool covers tools+primitives+recipes in one BM25 index with
domain + kind filters; `fastapi_meta_describe` shows full per-id spec.

### Phase 3 — Benchmark harness ✅ DONE (plan-level)

| # | Item | Status |
|---|---|---|
| 15 | 20 benchmark specs (5 baseline + 10 mid + 5 adversarial) | ✅ done |
| 16 | Scoring rubric (4 dimensions × 25%) | ✅ done |
| 17 | Benchmark runner + nightly CI hook | ✅ done (`engine/bench/blind/runner.py`) |
| 18 | Published baseline score | ✅ 100.00 (methodology `plan_level_v3_best_of_ensemble`) |

**Carry-forward to Phase 5:** the current score is plan-level (Maestro's
requirement→primitive/tool map). Code-level scoring (does the emitted
server actually pass behavioural tests?) moves to Phase 5.

### Phase 4 — Productize SKILL-001 for real users (partially complete)

**~75% complete, 1 key item open**.

| # | Item | Status |
|---|---|---|
| 19 | `install.sh` + Docker CI | ✅ nightly green |
| 20 | **`/examples/` populated with 5 real apps** | ⚠️ **5 empty dirs — open** |
| 21 | Docs site v1 | ✅ `engine/docs/build.py` |
| 22 | Semantic versioning + changelog | ✅ v0.1.0 shipped |
| 23 | Contribution guide | ✅ `CONTRIBUTING.md` |

**Open work for Phase 4 closeout (#20):**
Populate the 5 example directories with Maestro-built apps tied to
benchmark specs:

- `examples/06-auth-saas/` — `benchmarks/specs/baseline/02_auth_only_saas.md`
- `examples/07-multi-tenant-admin/` — `baseline/05_multi_tenant_admin.md`
- `examples/08-stripe-billing/` — `mid/01_saas_with_stripe_billing.md`
- `examples/09-event-sourced-orders/` — `mid/03_event_sourced_orders.md`
- `examples/10-llm-agent/` — `mid/05_llm_agent_backend.md`

Each example: MAESTRO_SESSION.md (plan-level transcript) + a working
FastAPI project + `pytest` green on E2E tests. Examples double as
regression fixtures for the code-level benchmark in Phase 5.

### Phase 5 — Code-level benchmark + surgical gap fills (current phase)

This is where we are NOW. Phases 1-4 are closed enough that new work
must justify itself against behavioural evidence.

| # | Item | Status |
|---|---|---|
| 24 | Weekly benchmark review — which specs still red? | pending — first review after #25 ships |
| 25 | Code-level scoring rubric — run emitted server, hit endpoints, assert behaviour | pending |
| 26 | Surgical primitive promotion from `_extracted/` when benchmark asks | pending — 180 candidates visible in catalog |
| 27 | Close Phase-1 item #9 (15+ extend tools import primitives) | pending |
| 28 | Close Phase-4 item #20 (populate 5 examples) | pending |
| 29 | Target score: ≥ 70% on the code-level rubric by v1.0 | pending |

**Exit criteria:** v1.0 ships when the code-level rubric hits ≥ 70% on
the canonical 20 specs.

### Phase 6 — Second skill (after v1.0)

Only after SKILL-001 hits 70% code-level benchmark.

| # | Item | Status |
|---|---|---|
| 30 | SKILL-002 candidate: Next.js / Django / LLM-agent backend — choose by demand | pending |
| 31 | Shared framework-free primitives across skills | pending |
| 32 | Multi-skill Maestro (FastAPI backend + Next.js frontend one session) | pending |

### Phase 7 — Ecosystem (post-v1.0)

| # | Item | Status |
|---|---|---|
| 33 | Community primitives with enforced T0-T9 gate + Opus audit | pending |
| 34 | Public benchmark scoreboard (per-release, code-level) | pending |
| 35 | SDK for Maestro authors (shipping against the skill's MCP surface) | pending |

---

## Part 3 — Honest risks

- **Maestro success ceiling.** If even 70% code-level benchmark is
  unattainable with current LLM capabilities, the product thesis fails.
  De-risk by scoring 5 specs manually before investing in full-harness
  code-level rubric (Phase 5 #25).
- **Rails-analogy limits.** Rails has 20 years of community + a human-
  first runtime. HuGR is LLM-first. The analogy is a design lodestar,
  not a promise of equivalent ergonomics.
- **Framework churn.** FastAPI / Pydantic breaking releases are real
  maintenance cost. Mitigate: pin versions per skill release, run the
  benchmark nightly against pinned versions.
- **Integration-discipline drift.** Right now 82 extend tools inline
  logic in violation of §6.1. Without a contract rule + CI gate, this
  regresses as new tools land. Add the rule when closing Phase-1 #9.
- **Staging pool temptation.** 180 `_extracted/` primitives are visible
  now. Temptation: promote them preemptively. Discipline: only when a
  benchmark gap says "we need X" does the extraction pipeline run.

---

## Part 4 — What to do RIGHT NOW

**Immediate (this sprint, order matters):**

1. **Close Phase-1 #9** — refactor 15 top-value extend tools to import
   `core.venous.*`. Adds a contract rule enforcing
   `primitives_used` non-empty on every tier-1 + tier-2 `add_*` tool.
2. **Close Phase-4 #20** — populate 5 example apps tied to benchmark
   specs, with `pytest` green.
3. **Design Phase-5 #25** — code-level rubric spec doc + reference
   implementation that runs emitted server in a sandbox and scores
   behaviour. Keep the plan-level rubric alongside for diagnostic value.

**Next 30 days:**

4. **Run Phase-5 #25** once on the 20-spec corpus, publish a honest
   code-level baseline. Likely < plan-level; that's the point.
5. **Phase-5 #26** surgical promotions driven by which specs went red.
   Target: promote 10 staged primitives, close 5 benchmark gaps.

**v1.0 gate:** code-level rubric ≥ 70%. Ship with honest changelog
citing which specs moved from red to green and which staged primitives
got promoted.
