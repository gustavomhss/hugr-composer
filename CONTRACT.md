# HuGR SkillKit — Inviolable Contract & Execution Checklist

> **This is the binding document.** Every future session, every commit,
> every PR is judged against it. `PRODUCT.md` describes the product;
> this file decides what we're allowed to do AND what "done" means per
> micro-step.
>
> **Every §B item carries four mandatory blocks:**
> - **Definition of Done (DoD)** — machine-verifiable "is this on disk?"
> - **Invariants** — rules that must never break as consequence
> - **Completeness criteria** — scope boundary (what in-scope vs out)
> - **Quality standards (SOTA)** — the excellence bar; no lower
>
> **An item without all four blocks satisfied is NOT DONE, regardless of
> checkbox state.** Partial compliance is failure.
>
> **Last ratified:** 2026-04-19.

---

## §A — Inviolable rules (apply forever)

Break any rule below and the Rails-style architecture collapses into
Yeoman scaffolding. A single authored exception becomes the template
for the next 50 violations.

- [ ] **A1 — Tools emit ≤ 20 lines of glue per capability.** Measured
      excluding imports + docstrings. Violating tool fails adapt
      contract gate.
- [ ] **A2 — Generated code imports from `core/venous/*`.** Every file
      a tool writes includes ≥ 1 `from core.venous.<ns> import ...`.
      Tools producing zero such imports are rejected.
- [ ] **A3 — Primitives are orthogonal.** Each does one thing; no
      primitive depends on mutating another at runtime. Violation
      surfaces in the 10-tier T4 metamorphic gate.
- [ ] **A4 — Running a tool twice does not clobber user edits.**
      Fingerprints + `dry_run` + idempotency. Enforced by adapt
      contract; non-negotiable forever.
- [ ] **A5 — Every primitive has ≥ 3 composition examples in its
      `.md`.** `grep -L "## Compose with:" core/venous/*/*/*.md`
      returns empty.
- [ ] **A6 — Every tool has an `MCP_TOOL` metadata block.** Auto-
      discovery mandatory; manual MCP registration forbidden Phase 1+.
- [ ] **A7 — Registry is single source of truth for discoverability.**
      `engine/primitives_by_concern.yaml` indexes every production
      primitive. Missing from registry = doesn't exist.
- [ ] **A8 — No claim in any doc without code on disk.** Drift = audit
      bug to fix SAME DAY as discovery.
- [ ] **A9 — Benchmark is arbiter Phase 3+.** No surface merged
      without citing a benchmark scenario it moves red→green.
- [ ] **A10 — Terminology lock (PRODUCT.md §8) is sacred.** Casual
      renaming is a bug, not a style preference.
- [ ] **A11 — Opus for correctness-critical audit, not Sonnet.**
      Sonnet hallucinated a race condition this session; Opus caught
      30 real bugs Sonnet missed.
- [ ] **A12 — `_extracted/` is a pool, not a backlog.** Promote only
      when benchmark gap demands. No preemptive triage.

---

## §B — Execution checklist (phase-ordered, each with DoD / Invariants / Completeness / Quality)

---

### Phase 0 — Ground truth + docs honesty

#### B0.1 — `PRODUCT.md` canonical ✅ Done

- **DoD:** File exists at `/PRODUCT.md` with §1-§9 as specified
  (terminology lock §8 mandatory, 3-layer architecture §2 Rails-mapped,
  success criteria §4 with benchmark target ≥70%).
- **Invariants:** Document is READ-ONLY for normal sessions; amendments
  require explicit ratification line at bottom with new date.
- **Completeness:** All 9 sections present. Terminology covers all
  8 terms (skill/tool/primitive/generator/adapter/recipe/Maestro + verb).
- **Quality (SOTA):** Every claim maps to a code location OR a
  ROADMAP.md step; zero "aspirational" phrasing; non-goals §5 explicit.

#### B0.2 — `ROADMAP.md` honest + phased ✅ Done

- **DoD:** File at `/ROADMAP.md` with Part 1 brutal ground truth +
  Part 2 phased plan (0-7) + Part 3 risks + Part 4 immediate actions.
- **Invariants:** Brutal-ground-truth section updated at end of every
  phase with fresh audit. Phases can add but not delete items silently.
- **Completeness:** 8 phases cover first-commit → ecosystem. Every
  phase has concrete numbered items linkable from this contract.
- **Quality (SOTA):** Every promise tied to a measurable exit criterion;
  risks §3 named honestly (Maestro ceiling, framework churn, etc.).

#### B0.3 — `CONTRACT.md` (this file) ✅ Done

- **DoD:** `/CONTRACT.md` exists with §A inviolable rules (12 items),
  §B enriched checklist (every item has DoD + Invariants + Completeness
  + Quality), §C enforcement rules, §D non-promises.
- **Invariants:** §A rules cannot be amended inside a session (only by
  explicit ratification); violating commits are rejected.
- **Completeness:** All Phase 0-7 items covered; no item without its
  four blocks.
- **Quality (SOTA):** Each item's Quality block sets a bar ABOVE
  mechanical correctness — SOTA demands the "excellent" standard, not
  merely "compliant".

#### B0.4 — `SKILL.md` rewritten to match ground truth

- **DoD:** `/skills/SKILL-001-fastapi-production/SKILL.md` updated:
  - Tool count matches `find adapt/extend -name 'add_*.py' | wc -l`
  - Primitive count matches `find core/venous -name '*.manifest.json' | wc -l`
  - Test count matches actual CI pass (not claims)
  - Every number has a `$(command)` comment showing how to verify
  - Cites PRODUCT.md + ROADMAP.md + CONTRACT.md; does NOT re-state
    architectural claims inline.
- **Invariants:** Numbers in SKILL.md MUST regenerate via a script
  `engine/audit/skillmd_counts.py` that diff's against disk. Drift = CI fail.
- **Completeness:** All claimed metrics have a verification command.
  All architectural sections replaced by a link to canonical doc.
- **Quality (SOTA):** Reads as operational reference, not marketing.
  Every section answers "what CAN the caller do NOW?" not "what WILL
  this someday be?"

#### B0.5 — `README.md` at repo root

- **DoD:** `/README.md` exists, ≤ 80 lines, containing:
  - One-paragraph elevator pitch (mirrors PRODUCT.md §1)
  - Link to PRODUCT.md / ROADMAP.md / CONTRACT.md
  - Install command stub (placeholder until Phase 4)
  - Current benchmark score line (placeholder "not yet measured"
    until Phase 3)
  - Project status badge (phase we are in).
- **Invariants:** README.md is NOT duplicating product docs — it's a
  pointer. Maintenance: phase badge updates with every phase transition.
- **Completeness:** One-screen (mobile-readable). All claims verifiable.
- **Quality (SOTA):** Respects a reader's time. No bullet soup. The 80-
  line budget is a hard limit.

#### B0.6 — `CLAUDE.md` memory pointer ✅ Done

- **DoD:** `.claude/projects/.../memory/venous_architecture.md` points
  to `/PRODUCT.md` + `/ROADMAP.md` + `/CONTRACT.md` as canonical
  session-startup docs.
- **Invariants:** Every future Claude session loads this pointer FIRST.
- **Completeness:** Memory entry covers product, roadmap, AND contract.
- **Quality (SOTA):** Reader-of-the-memory-alone would know where to go
  in one click.

#### B0.7 — `/benchmark/` audited + stubs deleted

- **DoD:**
  - Every test file under `/benchmark/` and `/benchmarks/` either
    passes `pytest` or is deleted
  - A file `benchmark/STATUS.md` enumerates real test count +
    pass/fail breakdown + last-run timestamp
  - Stub files identified by `grep -l 'assert True' | grep -v REPLACE_ME`
    removed
  - SKILL.md references updated to match real count (drives B0.4).
- **Invariants:** From this point, no stub tests merged. Every test
  has ≥ 1 real assertion on ≥ 1 real code path.
- **Completeness:** 100% of benchmark directory reviewed. No "maybe
  flaky, skip for now".
- **Quality (SOTA):** Each surviving test has a one-line docstring
  explaining what it proves. Zero dead tests.

#### B0.8 — Machine-generated artefacts `.gitignore`d

- **DoD:** `.gitignore` lists:
  - `engine/extraction/tools_latent_primitives.json`
  - `engine/extraction/primitive_candidates_ranked.json`
  - `engine/extraction/dedupe_report.json`
  - `engine/extraction/ambiguous_primitives.json`
  - `engine/extraction/_t0_report.json`
  These are re-creatable from source — not code.
- **Invariants:** No machine-generated file in git history going
  forward. `pre-commit` hook rejects them.
- **Completeness:** Every file produced by pipeline stages is enumerated.
- **Quality (SOTA):** Pipeline can be rerun blind by anyone cloning
  repo. Artefacts regenerate deterministically.

**Phase 0 exit criterion (machine-checkable):**
```
test -f PRODUCT.md && test -f ROADMAP.md && test -f CONTRACT.md \
  && test -f README.md \
  && python -m engine.audit.skillmd_counts \
  && test ! -f engine/extraction/tools_latent_primitives.json  # gitignored
```

---

### Phase 1 — Reconnect primitives to tools

#### B1.0 — Distribution strategy for `core.venous` (prerequisite to B1.3)

- **DoD:**
  - Decision documented at `/docs/decisions/0002-core-venous-distribution.md`:
    which strategy (copy-in / PyPI / path-bridge) and why.
  - Copy-in mechanism implemented: `generators/scaffold_venous.py` —
    called by `fastapi_generate_project` — copies requested primitives
    into the generated project's `core/venous/<ns>/<Name>/`.
  - Copy-in tracks provenance (`.venous_manifest.json` at generated-
    project root) so subsequent tool adds know what's already shipped.
  - CI check: generated sample project imports from its own
    `core/venous/...` without ImportError.
- **Invariants:** Generated projects are SELF-CONTAINED — no runtime
  dependency on the skill repo. A user who deletes the skill repo
  must still be able to run the generated app.
- **Completeness:** Works for all 97 production primitives. Script
  handles cross-primitive imports (e.g. `IdempotentConsumer` depends
  on `InboxDeduplicator`) via a dependency resolver.
- **Quality (SOTA):** Primitives copied under MIT license with
  attribution footer in each copied file; provenance manifest is
  machine-readable; re-running generate_project is idempotent
  (no dup imports, no partial copies).

#### B1.0.1 — Adapter layer decision (prerequisite to B1.3)

- **DoD:**
  - Decision documented at `/docs/decisions/0003-adapter-layer.md`:
    primitives stay framework-agnostic; framework glue lives in
    `core/venous/_adapters/fastapi/<Name>Adapter.py`.
  - Adapter pattern: `<Name>Adapter` wraps the pure primitive with a
    FastAPI-idiomatic surface (Depends-compatible, middleware factory,
    router helpers as needed). Adapter imports primitive; tool emits
    adapter invocation.
  - One reference adapter shipped: `core/venous/_adapters/fastapi/
    GracefulShutdownAdapter.py` — wraps `GracefulShutdown` with
    FastAPI `@app.on_event("shutdown")` + drain middleware.
  - `add_graceful_shutdown.py` refactored end-to-end to prove the
    pattern: emits ≤20 lines of glue + copies the primitive + copies
    the adapter + tests assert import chain.
- **Invariants:** No FastAPI / Starlette / SQLAlchemy import may appear
  in `core/venous/<ns>/<Name>/` (only in `core/venous/_adapters/`).
  CI enforces: `grep -rlE 'from (fastapi|starlette|sqlalchemy)'
  core/venous/ | grep -v _adapters` returns empty.
- **Completeness:** Reference adapter works end-to-end (unit test + CI
  generates project that imports it without error).
- **Quality (SOTA):** Adapter adds < 30 lines per primitive on average;
  design doc explains why an adapter ≠ a god-primitive; no adapter
  depends on more than 2 primitives (composability preserved).

#### B1.1 — `engine/primitives_by_concern.yaml` registry

- **DoD:**
  - File exists; YAML-parseable; top-level `version: 1`.
  - Entry count equals `find core/venous -name '*.manifest.json' | wc -l`.
  - Each entry keys: `name`, `namespace`, `concern` (from fixed
    taxonomy), `purpose` (max 120 chars), `compose_with` (≥ 2, ≤ 5
    sibling primitive names that all exist in the YAML).
  - Script `engine/registry_check.py` exits 0 verifying above.
- **Invariants:** Every new production primitive merged adds a registry
  entry in the same PR. CI check mandatory. Broken `compose_with`
  references fail CI.
- **Completeness:** 100% of production primitives (manifest.json
  present). Staged `_extracted/` explicitly NOT included.
- **Quality (SOTA):** `purpose` is verb-first ("Verifies HMAC
  signatures with domain separation"), no marketing adjectives.
  `compose_with` entries are chosen for REAL synergy (a senior
  engineer would pair them), not alphabetical neighbors. YAML sorted
  by namespace then name for reviewability.

#### B1.2 — "Compose with:" in every production primitive's `.md`

- **DoD:**
  - `grep -L "^## Compose with:" core/venous/*/*/*.md | grep -v _extracted`
    returns EMPTY.
  - Every "Compose with:" section has ≥ 3 concrete patterns; each
    pattern names ≥ 2 sibling primitives + 1-sentence use case.
- **Invariants:** PR template requires "Compose with" recipes for any
  new primitive. Audit adds automated check.
- **Completeness:** 100% of production primitives (manifest.json).
- **Quality (SOTA):** Recipes describe REAL patterns a senior engineer
  would ship (not "you could theoretically combine..."). Each pattern
  includes: (a) which primitives, (b) in what order/composition, (c)
  what invariant the composition gives that no single primitive gives
  alone. Example quality bar: "SignatureVerifier + IdempotentConsumer
  + AuditEvent → webhook receiver with single-delivery guarantee + tamper-
  evident audit trail. Order: verify → dedup → business-handler →
  audit-append-on-success."

#### B1.3 — 15 top-value tools refactored (list in ROADMAP §1.3)

- **DoD:** For each of the 15 enumerated tools:
  - Emits ≥ 1 `from core.venous.<ns> import ...` in generated output.
  - Total glue ≤ 20 lines per capability (A1 satisfied).
  - `MCP_TOOL` metadata lists `imports_primitives: [...]` explicitly.
  - Existing tool unit tests still pass; generated-code tests updated
    to import from `core.venous.*`.
- **Invariants:** A2 (imports from core.venous) becomes CI-enforced
  for all 15. Rollback = PR rejection.
- **Completeness:** All 15 tools refactored. Partial set = Phase 1
  not done.
- **Quality (SOTA):** Refactored tool is MORE readable than original
  (LoC drops ≥ 40%). Generated code is idiomatic — passes `ruff` +
  `mypy --strict` on the scaffolded project with zero exemptions.

#### B1.4 — MCP tool responses cite primitives

- **DoD:** Every tool's `ToolResult.payload` includes
  `imports_primitives: list[str]` enumerating the primitives the
  emitted code imports, in canonical form `core.venous.<ns>.<Name>`.
- **Invariants:** Field is required in `adapt/` contract schema going
  forward; legacy tools without it flagged by CI.
- **Completeness:** All refactored tools (B1.3). Non-refactored tools
  may have empty list for now — explicit, not silent.
- **Quality (SOTA):** List is ACCURATE (not a wish-list). Verified by
  parsing emitted code + extracting imports. A discrepancy between
  `imports_primitives` and actual imports fails CI.

#### B1.5 — Generator auto-discovery

- **DoD:**
  - `mcp_tools/generators.py` has 0 hardcoded `@mcp_app.tool`
    decorators (`grep -c '@mcp_app.tool' mcp_tools/generators.py`
    returns 0).
  - Generators discovered by scanning `generators/` for `MCP_TOOL`
    dicts, same pattern as `adapt/` tools.
  - Generator count exposed via MCP matches
    `find generators -name '*.py' -not -name '__init__.py' | wc -l`.
- **Invariants:** Every new generator dropped into `generators/`
  auto-appears on MCP without touching `mcp_tools/*`.
- **Completeness:** All existing generators migrate. Legacy registration
  removed, not commented.
- **Quality (SOTA):** Discovery is filesystem-order deterministic and
  diff-reviewable. MCP tool metadata identical between generators and
  adapt tools — no schema bifurcation.

#### B1.6 — Phase 1 import gate

- **DoD:** `grep -rE 'from core.venous' adapt/extend/*.py | wc -l` ≥ 15.
- **Invariants:** Script runs in CI on every commit. Drop below 15 =
  fail.
- **Completeness:** 15+ tools pass A2.
- **Quality (SOTA):** Not just any 15 — the 15 enumerated in B1.3
  (highest-value, most-composed patterns).

**Phase 1 exit criterion:**
```
python -m engine.registry_check                                # B1.1
[ $(grep -L "^## Compose with:" core/venous/*/*/*.md | wc -l) -eq 0 ]  # B1.2
python -m engine.audit.tool_import_audit --require 15          # B1.3 + B1.6
python -m engine.audit.tool_payload_schema                     # B1.4
[ $(grep -c '@mcp_app.tool' mcp_tools/generators.py) -eq 0 ]   # B1.5
```

---

### Phase 2 — Discoverability runtime

#### B2.1 — `find_primitive(concern, query)` MCP tool

- **DoD:**
  - MCP tool exposed with schema
    `{concern: str, query: str}` → `list[{name, namespace, purpose, score}]`.
  - Implementation is pure retrieval over `primitives_by_concern.yaml`;
    ZERO LLM calls.
  - Ranking uses BM25 or equivalent over `purpose` + `compose_with`
    + primitive `.md` body.
  - Returns ≤ 10 hits, ranked by relevance.
- **Invariants:** Retrieval latency < 50 ms (unit test enforces).
  No network calls. No cache-stampede risk — registry loaded once
  per process.
- **Completeness:** Every concern in the fixed taxonomy returns ≥ 1
  hit when queried empty-string (taxonomy is exhaustive).
- **Quality (SOTA):** Results match what a Rails-senior engineer
  would pick manually for ≥ 80% of a test set of 20 curated queries.
  Test set lives in `benchmarks/discovery_test_set.json`.

#### B2.2 — `suggest_composition(intent)` MCP tool

- **DoD:**
  - Schema: `{intent: str}` → `list[{primitives: list[str], rationale: str, score: float}]`.
  - Pure retrieval — intent is matched against combined "Compose
    with:" recipes across all primitives via BM25.
  - Returns ≤ 5 ranked compositions.
- **Invariants:** Deterministic given identical input + registry state.
  Zero LLM invocation. Latency < 100 ms p95.
- **Completeness:** Test set of 20 realistic intents covers all major
  concerns; each returns ≥ 1 relevant composition.
- **Quality (SOTA):** Top-1 composition matches expert ground truth
  ≥ 70% of the time on the test set. Precision@3 ≥ 90%.

#### B2.3 — Reference docs site

- **DoD:**
  - A URL (GH Pages / Mintlify / Vercel) serves pages for every
    production primitive.
  - Each page: signature + invariants + compose-with links + source-
    code link + last-audit timestamp.
  - Docs generated from `.md` + `contract.json` + `primitives_by_concern.yaml`
    via a build step (`engine/docs/build.py`).
  - CI publishes the site on every main merge.
- **Invariants:** Stale docs = CI fail. Build is idempotent; running
  it twice yields identical site hash.
- **Completeness:** 100% of production primitives have a page.
  Every tool has a page cross-referencing its imports_primitives.
- **Quality (SOTA):** Navigation is flat per Rails API docs —
  every primitive reachable in ≤ 2 clicks from landing page. Search
  functional. Mobile-readable. Load time < 1 s.

**Phase 2 exit criterion:**
```
curl -s $DOCS_URL/primitives | grep -q "<primitive-count>"
python -m engine.discovery.quality_bench --min-precision-3 0.9
```

---

### Phase 3 — Maestro benchmark harness

#### B3.1 — 20 benchmark specs

- **DoD:** `/benchmarks/specs/` contains 20 Markdown files, tagged
  by tier:
  - `baseline/*.md` (5): crud-only, auth-only SaaS, webhook sink,
    rate-limited public API, multi-tenant admin.
  - `mid/*.md` (10): see ROADMAP.md Phase 3 §15.
  - `adversarial/*.md` (5): see ROADMAP.md Phase 3 §15.
- **Invariants:** Specs are plain English; NO hints about which
  tools/primitives to use. Spec quality review required before adding.
- **Completeness:** 20 specs exactly. Each has: title, requirements
  (bulleted), acceptance criteria, explicit non-requirements.
- **Quality (SOTA):** Specs resemble real product briefs (Gustavo
  validates each spec as "something a real client would ask for").
  Adversarial tier genuinely nasty: contradictions, hidden scaling
  requirements, primitive gaps.

#### B3.2 — Scoring rubric

- **DoD:** `benchmarks/scorecard.py` implements rubric:
  - 25% scaffold completeness (files exist, structure correct).
  - 25% test suite pass rate in the produced codebase.
  - 25% T0-T9 gate pass on sampled primitives imported by generated
    code.
  - 25% hand-editability (human scores a sample file 1-10).
  - Produces `benchmarks/scorecards/<spec-id>/<run-timestamp>.json`.
- **Invariants:** Rubric weights documented; changes require
  contract amendment. Hand-editability scoring rubric is a rubric,
  not vibes (5 criteria: idiomatic imports, clear names, small
  functions, tests as docs, no magic).
- **Completeness:** Every component scored 0-100; average produces
  overall.
- **Quality (SOTA):** Rubric documented so a different human scorer
  produces same score ± 5 points.

#### B3.3 — Benchmark runner

- **DoD:** `benchmarks/runner.py`:
  - Invokes Claude Sonnet / Opus against skill's MCP server for
    each spec.
  - Records session transcript + produced codebase + scorecard.
  - Reproducible with a seed; re-runs produce same transcript modulo
    LLM nondeterminism (capture rate ≥ 80% same-score).
- **Invariants:** Runner is deterministic except for LLM output.
  Recorded artefacts versioned under `benchmarks/runs/<date>/`.
- **Completeness:** All 20 specs runnable from CLI + from CI.
- **Quality (SOTA):** Runner fails-closed: any non-ok response during
  execution preserved in artefacts, not hidden.

#### B3.4 — Nightly CI job

- **DoD:** GitHub Actions workflow runs benchmark nightly. Stores
  score history in `benchmarks/history/YYYY-MM-DD.json`. Emits
  README badge. Alerts on regression > 5 points.
- **Invariants:** History never deleted. Badge always reflects last
  SUCCESSFUL run.
- **Completeness:** Runs all 20 specs; partial = fail.
- **Quality (SOTA):** Full run cost tracked + published; budget
  capped per run.

#### B3.5 — Baseline score published

- **DoD:** `benchmarks/latest_score.json` exists with honest baseline
  ≥ 30% overall average; per-spec breakdown committed. README cites
  the score.
- **Invariants:** Score never fudged. Regressions explicitly
  acknowledged in `benchmarks/history/NOTES.md`.
- **Completeness:** All 20 specs scored. No skips.
- **Quality (SOTA):** Score publicly reproducible — external reviewer
  can re-run with the same seed and get within ± 5 points.

**Phase 3 exit criterion:**
```
test -f benchmarks/latest_score.json
[ $(jq '.overall_average' benchmarks/latest_score.json) -ge 30 ]
```

---

### Phase 4 — Productize

#### B4.1 — `install.sh` CI-validated

- **DoD:** `/install.sh` runs to completion in a fresh `python:3.12-slim`
  Docker container via GitHub Actions. Validated nightly.
- **Invariants:** Install flow is hermetic — no required external
  state (no "first run `apt install`"). Failure surfaces in CI not
  in user's terminal.
- **Completeness:** Clone → install → benchmark runs end-to-end in
  < 5 min.
- **Quality (SOTA):** Install emits progress lines every step; failure
  surfaces specific remediation ("install 'tlc' via homebrew …").

#### B4.2 — `/examples/` populated

- **DoD:** ≥ 5 subdirectories in `/examples/`, each containing:
  - `README.md` describing the app in one paragraph
  - `MAESTRO_SESSION.md` with the transcript Maestro used to build it
  - Working code passing `pytest`
  - Cross-link table "tools used" + "primitives imported"
- **Invariants:** Examples not allowed to drift from the kit — every
  release re-runs examples in CI; broken = blocker.
- **Completeness:** 5+ examples covering ≥ 3 different tiers from
  benchmark specs.
- **Quality (SOTA):** Examples are NICE to read — not generated slop.
  A senior engineer would copy-paste snippets from them.

#### B4.3 — Docs site v1 published

- **DoD:** Public URL serves: PRODUCT.md + ROADMAP.md + CONTRACT.md +
  primitives reference + tools reference + examples. Versioned
  per release.
- **Invariants:** Every release tag produces a versioned snapshot
  reachable at `docs.hugr.dev/v0.1.0/...` (or equivalent).
- **Completeness:** All four top-level docs visible; 100% of
  production primitives + tools have pages.
- **Quality (SOTA):** Navigation flat; search works; mobile-readable;
  lighthouse score ≥ 90.

#### B4.4 — Semver + CHANGELOG

- **DoD:** `/CHANGELOG.md` exists with v0.1.0 entry citing benchmark
  score. Git tag `v0.1.0` pushed.
- **Invariants:** Every release updates CHANGELOG; `main` branch
  never untagged for > 1 week.
- **Completeness:** v0.1.0 entry names: benchmark score, primitive
  count, tool count, phase number.
- **Quality (SOTA):** CHANGELOG readable — users know what changed,
  why, and whether they need to act.

#### B4.5 — `CONTRIBUTING.md`

- **DoD:** File explains:
  - How to add a primitive (10-tier gate requirements).
  - How to add a tool (adapt contract requirements).
  - How to compose primitives into a new recipe.
  - Local dev setup.
- **Invariants:** Instructions tested — a stranger can follow them
  end-to-end without maintainer intervention.
- **Completeness:** All three surfaces (primitive / tool / recipe)
  covered.
- **Quality (SOTA):** Time-to-first-PR < 1 hour for someone who has
  never seen the repo.

**Phase 4 exit criterion:**
```
curl -sL $INSTALL_URL | bash                      # B4.1
test -d examples && [ $(ls examples | wc -l) -ge 5 ]  # B4.2
curl -sf $DOCS_URL                                # B4.3
test -f CHANGELOG.md && git tag --list | grep -q v0.1 # B4.4
test -f CONTRIBUTING.md                           # B4.5
```

---

### Phase 5 — Close benchmark gaps (ongoing)

Every commit must cite `phase-5: close red→green on benchmarks/specs/<id>`.

#### B5.1 — Score ≥ 50%

- **DoD:** `jq '.overall_average' benchmarks/latest_score.json` ≥ 50.
- **Invariants:** No surface added without benchmark citation.
- **Completeness:** All 20 specs still running.
- **Quality (SOTA):** Score is sustained 3 consecutive nightly runs.

#### B5.2 — Score ≥ 70% (v1.0 ship criterion)

- **DoD:** Same as B5.1 but ≥ 70.
- **Invariants:** v1.0 tag only after 7 consecutive nightly runs at
  ≥ 70.
- **Completeness:** All specs, no skips, no stunts.
- **Quality (SOTA):** Independent replication: an external reviewer
  re-runs the benchmark, arrives at ≥ 65% (allowing ± 5 for LLM noise).

---

### Phase 6 — SKILL-002

#### B6.1 — Demand-driven skill choice

- **DoD:** `/skills/SKILL-002-<stack>/SKILL.md` exists. Stack chosen
  per documented demand signal (≥ 3 user requests OR benchmark
  coverage gap).
- **Invariants:** Stack choice is publicly justified in a decision
  doc under `/docs/decisions/0001-skill-002-choice.md`.
- **Completeness:** SKILL.md parallels SKILL-001's structure.
- **Quality (SOTA):** Choice defensible against "why not X?" —
  alternatives considered in decision doc.

#### B6.2 — ≥ 30 shared primitives

- **DoD:** `engine/primitives_by_concern.yaml` shows ≥ 30 primitives
  with `skills: [SKILL-001, SKILL-002]`.
- **Invariants:** Shared primitives are framework-agnostic; violating
  one breaks both skills' tests.
- **Completeness:** Count ≥ 30 verified.
- **Quality (SOTA):** Each shared primitive genuinely framework-free
  (no `from fastapi import` etc.).

#### B6.3 — Multi-skill Maestro example

- **DoD:** `/examples/fullstack-<name>/` contains a session where
  Maestro invokes BOTH skills to build a full-stack app.
- **Invariants:** Example runs end-to-end in CI.
- **Completeness:** Both front- and back-end built, tests green.
- **Quality (SOTA):** Transcript readable; session cost < budget.

**Phase 6 exit criterion:** `ls skills/ | wc -l ≥ 2` + fullstack
example green.

---

### Phase 7 — Ecosystem

#### B7.1 — External PR lands primitive

- **DoD:** One PR from a non-maintainer merged, passing all gates
  without maintainer code edits.
- **Invariants:** Gate automation must be strong enough that no
  human intervention needed.
- **Completeness:** Primitive passes 10-tier + Opus audit.
- **Quality (SOTA):** PR time-to-merge < 72 hours.

#### B7.2 — Public benchmark scoreboard

- **DoD:** Permanent URL serving historical scores, trends,
  per-release breakdown.
- **Invariants:** Never deleted, never fudged.
- **Completeness:** All runs ever executed available.
- **Quality (SOTA):** Chart readable, regression alerts automated.

#### B7.3 — SDK docs for external Maestro authors

- **DoD:** `/docs/maestro-sdk/` explains how to build a Maestro
  against HuGR's MCP surface.
- **Invariants:** Docs tested — a stranger builds a toy Maestro in
  < 1 day.
- **Completeness:** All MCP endpoints documented + example client code.
- **Quality (SOTA):** Examples run as-is; no "pseudo-code, adapt for
  your runtime".

---

## §C — Enforcement

- [ ] **C1 — Session-opening audit.** Every session that modifies
      code MUST open `CONTRACT.md`, verify §A rules still hold, and
      check off any completed §B items. Session refusing = violation
      of A8.
- [ ] **C2 — PR discipline.** Every PR description MUST include:
      - `Phase: N.K` (which §B item this closes)
      - `§A compliance:` (list of rules touched and verified)
      - `DoD:` (copy of the DoD block; each item marked ✓ or N/A with
        reason)
      - `Invariants:` (same)
      - `Completeness:` (same)
      - `Quality (SOTA):` (same)
      PRs missing any of the six = REJECTED.
- [ ] **C3 — Quarterly ratification.** Gustavo reviews §A and §B
      quarterly. Amendments require explicit signed line at bottom
      of this file with new date. Silent drift ≠ amendment.
- [ ] **C4 — Amendment log.** Every ratification appends a block:
      ```
      ### Ratified YYYY-MM-DD by Gustavo
      - <bullet list of rule / item amendments>
      ```
- [ ] **C5 — Machine-verified on every commit.** The checker
      `engine/audit/contract_check.py` runs in pre-commit and CI.
      Full command:
      ```
      cd skills/SKILL-001-fastapi-production \
        && PYTHONPATH=. python3 -m engine.audit.contract_check
      ```
      Exit 0 required. Adding a new §B item requires adding its
      `Rule(...)` entry to `RULES` in `contract_check.py` in the
      same commit. Items without machine-checks are allowed only
      during Phase N while N is the active phase; once N closes,
      non-machine-checkable items must either acquire a check or be
      removed from §B.
- [ ] **C6 — Phase-gate CI.** Merging to `main` from a branch
      targeting Phase N fails CI unless `contract_check --phase N`
      passes. Prevents cross-phase code from landing before its
      phase's prerequisites are green.
- [ ] **C7 — Pre-commit hook sample.** The following lives at
      `.git/hooks/pre-commit` (or equivalent husky / pre-commit
      config):
      ```bash
      #!/usr/bin/env bash
      set -euo pipefail
      cd "$(git rev-parse --show-toplevel)/skills/SKILL-001-fastapi-production"
      PYTHONPATH=. python3 -m engine.audit.contract_check --phase 0
      ```
      Extended per-phase as phases close. A commit that fails the
      hook MUST be fixed, not bypassed. `--no-verify` forbidden.

---

## §D — Explicit non-promises

- Does NOT promise Maestro success rates > 70% — that's a target, not a
  guarantee of capability.
- Does NOT commit SKILL-003/004 timelines — exist only if Phase 7
  ecosystem pulls them.
- Does NOT forbid experiments — experiments live on branches, merged
  only after §A + phase's §B items pass.
- Does NOT replace `PRODUCT.md` — architectural contract lives there;
  "how we build it" lives here.
- Does NOT tolerate "temporary" violations of §A. Temporary = no.

---

## §E — Amendment log

### Ratified 2026-04-19 by Gustavo
- Initial contract issued. 12 inviolable rules. 40+ micro-step checklist.
- DoD / Invariants / Completeness / Quality blocks mandatory per §B item.
- PR discipline §C2 enforced.

---

**End of contract. Executable. Enforceable. Sacred.**
