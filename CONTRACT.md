# HuGR Arsenal — Inviolable Contract & Execution Checklist

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
      when ONE of:
      (a) a benchmark gap demands it;
      (b) the primitive is imported by a registered tool or module
          (i.e. a caller already exists in the skill surface);
      (c) the primitive is in-scope for a **triage pass** explicitly
          ratified in §E, where the pass classifies every item under
          review into promote / keep-staged-with-reason / delete.
          Triage passes are one-shot (start and end commit named in
          §E); they are NOT a recurring license for speculative
          promotion.
      "No preemptive triage" still forbids speculative promotion of
      individual primitives without one of (a), (b), (c). See
      `docs/decisions/0004-tier-lite.md §3` for rationale.

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

#### B0.4 — `SKILL.md` body counts reconcile against disk

> SKILL.md's **shape** is defined in §B2.5 (Anthropic Agent Skills
> frontmatter + HuGR body-metadata block, machine-checked by
> `_r_skill_md_contract`). §B0.4 is scoped narrower: it checks that
> any **narrative body claim about counts** (e.g. "N adapt tools"
> in a prose paragraph) is not drifting beyond 10% of disk reality.
> Quick drift-detector, not a shape validator.

- **DoD:** `skills/SKILL-001-fastapi-production/SKILL.md`:
  - Any count claim in the body prose (not the few-shot transcripts,
    which freeze illustrative snapshots per §B2.5) is within 10% of
    the corresponding disk count.
  - `_r_skillmd_honest` in `engine/audit/contract_check.py`
    implements the check on the `adapt/extend/add_*.py` count
    specifically — the only claim that has historically drifted.
    Additional body-prose claims are covered by `_r_counts_sync`
    (§B4.7, SKILL.md[Overview] scope).
- **Invariants:** Numbers in SKILL.md MUST reconcile against
  `engine/index/catalog.json` + the machine-generated
  `INVENTORY.md`. §B4.7 covers the narrative-doc set —
  CLAUDE / STATUS / ROADMAP / CHANGELOG / **SKILL.md[Overview]** /
  FREEZE / INTERFACES — and fails CI on any drift. The
  SKILL.md[Overview] scope is the paragraph under `## Overview` only;
  few-shot transcript counts are illustrative snapshots and
  deliberately not rule-checked.
- **Completeness:** See §B2.5 for required sections / frontmatter
  shape / license / transcripts. §B0.4 only checks body-prose
  counts.
- **Quality (SOTA):** Reads as operational reference, not marketing.
  Every section answers "what CAN the caller do NOW?" not "what WILL
  this someday be?"

#### B0.5 — `README.md` at repo root

- **DoD:** `/README.md` exists, ≤ 100 lines, containing:
  - One-paragraph elevator pitch (mirrors PRODUCT.md §1)
  - Link to PRODUCT.md / ROADMAP.md / CONTRACT.md
  - Install command stub (placeholder until Phase 4)
  - Current benchmark score line (placeholder "not yet measured"
    until Phase 3)
  - Project status badge (phase we are in).
- **Invariants:** README.md is NOT duplicating product docs — it's a
  pointer. Maintenance: phase badge updates with every phase transition.
- **Completeness:** One-screen (mobile-readable). All claims verifiable.
- **Quality (SOTA):** Respects a reader's time. No bullet soup. The 100-
  line budget is a hard limit; the pre-v1.0 limit was 80, but Wave-E
  added machine-verified surface-count tokens to the Current-status
  block (~5 lines the rule asserts), consuming budget the narrative
  prose needed. Sonnet flagged the README sitting at 79/80 with no
  headroom (Wave-F M3); 100 gives ~20 lines of honest margin for
  future status additions without turning a one-line edit into a
  structural rewrite.

#### B0.6 — `CLAUDE.md` memory pointer ✅ Done

- **DoD:** `.claude/projects/.../memory/venous_architecture.md` points
  to `/PRODUCT.md` + `/ROADMAP.md` + `/CONTRACT.md` as canonical
  session-startup docs.
- **Invariants:** Every future Claude session loads this pointer FIRST.
- **Completeness:** Memory entry covers product, roadmap, AND contract.
- **Quality (SOTA):** Reader-of-the-memory-alone would know where to go
  in one click.

#### B0.7 — Zero trivial-stub test functions

- **DoD:**
  - Every `test_*.py` under `/benchmark/`, `/benchmarks/`, and
    `core/venous/` (excluding `_extracted/`) has every test
    function execute a real code path. A test whose body reduces
    to exactly ``assert True`` is a stub.
  - Rule `_r_benchmark_no_stubs` in
    `engine/audit/contract_check.py` scans the three roots above,
    flags each stub function by ``<file>::<function>`` identifier,
    and fails CI with a per-function list. The rule inspects each
    function independently; mixed files with three stubs + one
    real test are rejected (pre-audit it only caught fully-stub
    files — that gap is closed).
  - Tests in `core/venous/_extracted/` are exempt; that tree is
    the staging pool by design. Promotion via §A12 requires
    replacing the stubs with real tests before the primitive
    lands in `primitives_by_concern.yaml`.
  - Gaps identified by `grep -l 'assert True' | grep -v REPLACE_ME`
    removed (historical wording preserved for reference).
- **Invariants:** From this point, no stub tests merged. Every
  shipped test function has ≥ 1 real assertion on ≥ 1 real code
  path. SKILL.md / INVENTORY counts that drive §B0.4 are
  machine-checked independently by §B4.7 `_r_counts_sync`; no
  separate STATUS.md is maintained.
- **Completeness:** 100% of benchmark directory AND
  `core/venous/` reviewed (modulo `_extracted/`). No "maybe flaky,
  skip for now".
- **Quality (SOTA):** Each surviving test has a one-line
  docstring explaining what it proves; per-function invariant
  IDs (e.g. ``CB_INV_01``, ``IS_INV_03``) are cited in the test's
  docstring or file-level module docstring so a reader tracing a
  failing witness to the named invariant finds the hit in one
  jump. Zero dead tests.

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
  && PYTHONPATH=. python -m engine.audit.contract_check \
  && test ! -f skills/SKILL-001-fastapi-production/engine/extraction/tools_latent_primitives.json  # gitignored
```
(`engine.audit.contract_check` enforces `§B0.1..§B0.8` and every
later phase's `§B*` items registered in `RULES`. There is no separate
`engine.audit.skillmd_counts` — §B2.5's `_r_skill_md_contract` +
§B4.7's `_r_counts_sync` carry that work.)

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
- **Completeness:** Works for every registered primitive in
  `engine/primitives_by_concern.yaml` (count tracked by
  `engine.inventory` → `INVENTORY.md`; no hand-maintained number
  here). Script handles cross-primitive imports (e.g.
  `IdempotentConsumer` depends on `InboxDeduplicator`) via a
  dependency resolver.
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
  - Rule `_r_registry_exists` in `engine/audit/contract_check.py`
    exits 0 verifying the above (there is no separate
    `engine/registry_check.py` — the contract-check harness subsumes it).
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

#### B1.3 — Rails-style wiring floor (≥ 15 extend tools import primitives)

- **DoD:** At least 15 tools under `adapt/extend/` emit generated
  code that imports from `core.venous.*`:
  - Emits ≥ 1 `from core.venous.<ns> import ...` in the tool's
    output OR declares the primitive via `MCP_TOOL.imports_primitives`.
  - Total inline glue per tool ≤ 20 lines per capability (§A1).
  - `MCP_TOOL` metadata lists `imports_primitives: [...]` so the
    catalog-builder (`engine.index.manifest`) surfaces the
    dependency graph.
  - Existing tool unit tests still pass; behaviour tests updated
    to witness the imported primitive in the emitted code.
- **Invariants:** A2 (generated code imports from core.venous) is
  CI-enforced by `_r_tools_import_primitives` in
  `engine/audit/contract_check.py`. The machine floor is
  **≥ 22 non-regression** (current: 24) — higher than the
  CONTRACT-text floor of 15 because the floor is a
  monotonically-increasing high-water mark that ratchets up as
  Rails-style refactors land. Lowering the floor requires an §E
  ratification block.
- **Completeness:** Phase 1 closes when the floor ratchets to
  ≥ 22 (met). Stretching to ≥ 35 is a post-v1.0 target per
  ROADMAP §6.1 (Wave 2).
- **Quality (SOTA):** Refactored tool is MORE readable than
  original (LoC drops ≥ 40%). Generated code is idiomatic —
  passes `ruff` lint on the scaffolded project with zero
  exemptions. Type-check discipline is `ruff`-driven;
  `mypy --strict` is NOT configured today (no `[tool.mypy]` in
  `pyproject.toml`, no mypy dependency) — tracked as a
  post-v1.0 Phase-7 decision per ROADMAP §3.1.

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

#### B1.7 — FastAPI adapter coverage

> Adapters are the thin framework-specific shims that wire framework-free
> primitives into FastAPI (ADR 0003). Without test coverage a subtle
> adapter bug breaks every generated app silently — so each adapter
> MUST have a `test_<Name>Adapter.py` beside it AND reference a
> primitive that exists in the registry.

- **DoD:**
  - `core/venous/_adapters/fastapi/` contains ≥ 15 `<Name>Adapter.py`
    files (floor chosen to match the 15 top-value Rails-style wirings
    enumerated in B1.3).
  - Every `<Name>Adapter.py` has a colocated `test_<Name>Adapter.py`.
  - Every adapter filename resolves to a registered primitive. The
    resolution rules (in priority order) are:
    1. Strip `Adapter` suffix → literal primitive name in registry
       (e.g. `CircuitBreakerAdapter` → `CircuitBreaker`).
    2. Family tag (e.g. `Workflow`, `AuditLog`, `OAuth2`, `Saga`,
       `WebhookReceiver`) maps to a registered primitive set;
       family tags are enumerated in `engine/audit/contract_check.py`.
    3. Registry name appears as a substring of the adapter stem.
  - Rule enforced by `_r_adapter_coverage` in
    `engine/audit/contract_check.py`.
- **Invariants:**
  - Adding a new adapter that breaks any resolution rule fails
    B1.7 in CI.
  - `MCP_TOOL` tools may call adapter helpers but MUST NOT import from
    `_adapters/fastapi/` when a registered primitive covers the need
    (§A2 first; adapters are Rails-style wiring, not shortcuts).
- **Completeness:** Every adapter in `_adapters/fastapi/` passes the
  three checks; no adapter bypasses the registry.
- **Quality (SOTA):** Adapters ship with a module-level docstring
  explaining which primitive(s) they wire and which FastAPI seam
  they attach to (middleware, dependency, route handler, startup
  hook). Adapters are LIBRARY CODE, not Maestro tools — they
  intentionally do NOT carry `MCP_TOOL` metadata. Discoverability
  happens at the tool layer (`adapt/extend/*` tools declare
  `imports_adapters` in their `MCP_TOOL`, surfacing adapter use in
  `catalog.json`).

#### B1.8 — Tier-lite eligibility

> Tier-lite (see ADR 0004) is a second valid registered tier for
> stateless primitives whose invariants collapse to first-order
> predicates over inputs — no TLA+ specification required. Tier-lite
> reduces ritual for primitives where formal verification adds zero
> safety, WITHOUT loosening the bar for stateful or concurrent ones.

- **DoD:**
  - `engine/primitives_by_concern.yaml` schema accepts
    `tier: "lite" | "full"`; default is `"full"` (backwards-compatible
    — all v0.x primitives retain `full` semantics).
  - For every registry entry with `tier == "lite"`,
    `_r_tier_lite_eligibility` in
    `engine/audit/contract_check.py` verifies ALL of:
    1. `core/venous/<ns>/<Name>/<Name>.py` exists and is readable.
    2. Zero `REPLACE_ME` markers in that file.
    3. No framework imports (`fastapi`, `starlette`, `sqlalchemy`,
       `sqlmodel`, `pydantic`, `django`, `flask`, `tornado`,
       `aiohttp`) AND no implicit framework tokens (`Mapped[`,
       `APIRouter(`, `Depends(`, `class Base(`) detected by the AST
       helpers in `engine/promotion/state.py`.
    4. No concurrency imports or primitives (`threading`, `asyncio`,
       `multiprocessing`, `Lock`, `Semaphore`, `Queue`, …).
  - Lite primitives indexed in `engine/index/catalog.json` with
    `tier="lite"`; consumers can filter by tier.
- **Invariants:**
  - A lite primitive found to violate any eligibility check at audit
    time fails B1.8 — silent drift rejected at CI.
  - Upgrading lite → full requires adding the `.tla` spec and
    flipping the registry field in a single PR; the primitive's
    public API MUST NOT change across the upgrade (§A10).
  - Lite primitives cannot depend on unregistered staged primitives
    (dependency closure must be fully registered).
- **Completeness:** All existing registered primitives keep
  `tier: "full"` at the v1.0 cut; any new lite primitive ships
  with an eligibility proof in its PR description (maps each of the
  four machine checks + three human-review bullets from ADR 0004 §2.1).
- **Quality (SOTA):** A lite primitive's `.md` documents WHY it
  qualifies for lite in a one-paragraph eligibility justification
  naming which of the seven ADR 0004 §2.1 bullets apply. Promotion
  executor (`engine/promotion/promote.py`) refuses `tier="lite"`
  until the ratification token `§B1.8 ratified` appears in
  CONTRACT.md §E.

**Phase 1 exit criterion (every item covered by a single command):**
```
cd skills/SKILL-001-fastapi-production && PYTHONPATH=. \
  python -m engine.audit.contract_check
# ↑ enforces:
#   • B1.0 / B1.0.1   _r_core_venous_distribution + _r_adapter_layer_invariant
#   • B1.1            _r_registry_exists (replaces fictional engine.registry_check)
#   • B1.2            _r_compose_with_coverage
#   • B1.3            _r_tools_import_primitives (replaces fictional tool_import_audit)
#   • B1.4            covered by B1.3's AST-import scan; MCP-tool payload
#                     shape is validated at catalog build time by
#                     `engine.index.manifest build` (no separate
#                     `engine.audit.tool_payload_schema` command — that
#                     label was historical; the check is real and lives
#                     inside manifest.build).
#   • B1.5            _r_no_manual_mcp_tool_decorator
#   • B1.6            _r_no_orphan_generators
#   • B1.7            _r_adapter_coverage
#   • B1.8            _r_tier_lite_eligibility
```
Catalog determinism (part of §B1.4 / §B2.4) is verified with:
```
cd skills/SKILL-001-fastapi-production && PYTHONPATH=. \
  python -m engine.index.manifest verify
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

#### B2.4 — Index catalog manifest: synced + deterministic

> The catalog (`engine/index/catalog.json`) is the single machine-
> readable view of every Maestro-visible surface. It MUST reflect
> on-disk reality AND MUST produce the same bytes (and therefore the
> same `stable_hash`) for the same disk state — otherwise consumers
> that pin to `stable_hash` see phantom drift.

- **DoD:**
  - `engine/index/catalog.json` exists with: tools[], primitives[],
    recipes[], and top-level `stable_hash` (SHA-256 over canonical
    content — sorted keys, no timestamps).
  - `engine.audit.contract_check._r_index_manifest` runs
    `engine.index.manifest build` twice against the same disk and
    asserts the `stable_hash` is byte-identical between runs.
  - Build output also satisfies: every MCP_TOOL on disk has a
    catalog entry, every primitive directory has an entry, every
    `## Compose with:` bullet is parsed into a recipe.
- **Invariants:**
  - Non-deterministic content (file-system iteration order, locale-
    sensitive sort, timestamps, random ids) is FORBIDDEN in the
    catalog emitter. Any drift between two builds on the same disk
    = regression, rejected at CI.
  - Editing `catalog.json` by hand is forbidden — the next `verify`
    run will catch the drift and fail.
- **Completeness:** All `TOOL_SCAN_ROOTS` in `engine/index/manifest.py`
  are visited; no scan root silently skipped.
- **Quality (SOTA):** `stable_hash` is cited verbatim (first 12 hex
  chars) in every `CHANGELOG.md [X.Y.Z]` block at release, so
  consumers without real-time catalog access can verify the version
  they serve matches the release notes. The emitter prints the hash
  on every `build` for ops visibility.

#### B2.5 — `SKILL.md` v2 Anthropic Agent Skills contract

> `SKILL.md` is the Maestro-facing entry document: the skill's
> "README for LLM consumers". v2 format has TWO YAML blocks:
> (a) Anthropic-spec frontmatter at the top (`name` / `description`
>     / optional `license`), and
> (b) a fenced ``` ```yaml ``` block inside the body under an
>     `## Machine-readable metadata` section carrying HuGR-specific
>     fields (`hugr_skill_version`, `spec_compat`, `kind`, `domains`,
>     `entry_tools`, `catalog_path`, `phases`, `invariants`).
> The split matches Anthropic's skill contract (which LLM hosts
> parse by the frontmatter) + HuGR's richer metadata (which our own
> catalog + Maestro drivers parse from the body). Do not conflate
> the two — putting HuGR fields in the frontmatter breaks
> Anthropic parsers, and putting Anthropic fields in the body
> block breaks the hosts.

- **DoD:**
  - `skills/SKILL-001-fastapi-production/SKILL.md` starts with
    Anthropic-spec YAML frontmatter containing: `name` (kebab-case,
    ≤ 64 chars), `description` (800-1200 chars, third-person,
    carrying both a "use when" trigger and a "do not" anti-trigger
    clause). `license` is optional but MUST be a valid SPDX
    identifier when present.
  - Body carries every section required by the machine check:
    `## Overview`, `## When to use`, `## When NOT to use`,
    `## Machine-readable metadata`, `## Workflow phases`,
    `## Tier-1 tool index`, `## Few-shot transcripts`,
    `## Anti-patterns`, `## Reference files`.
  - `## Machine-readable metadata` fenced ```yaml``` block contains
    all eight required keys (`hugr_skill_version`, `spec_compat`,
    `kind`, `domains`, `entry_tools`, `catalog_path`, `phases`,
    `invariants`).
  - Body ≤ 500 lines and ≤ 5000 tokens (estimate = `len(body)//4`).
  - ≥ 3 few-shot transcripts under `## Few-shot transcripts`.
  - `hugr_skill_version` is semver-shaped AND matches the `VERSION`
    file (§B4.6 triplet sync validates the latter independently).
  - `catalog_path` resolves to a JSON file carrying
    `schema_version`, `tools`, `primitives`, `recipes`, `counts`.
  - Every `entry_tools` entry resolves to a registered tool in
    `catalog.json` OR is a tree dispatcher / tier-1 meta name.
  - Rule `_r_skill_md_contract` in
    `engine/audit/contract_check.py` enforces every bullet above;
    failing any piece = CI fail.
- **Invariants:**
  - Body-block `hugr_skill_version` matches the skill-dir `VERSION`
    file (§B4.6 triplet sync covers skill-dir VERSION independently;
    the SKILL.md body value is the one Maestro consumes).
  - Few-shot transcripts reference only registered primitives,
    catalog tools, tier-1 meta tools, and tree dispatchers — no
    aspirational surface. Machine-checked by `_r_skill_md_contract`
    check #12b, which walks the transcripts section and asserts every
    `fastapi_*` token resolves against
    `catalog.json tool names ∪ tier-1 meta ∪ tree dispatchers`
    (the tree-dispatcher set is derived at check time by scanning
    `mcp_tools/tree/*.py`, so adding a new tree module auto-extends
    the allowlist).
  - No stale counts in body; the `## Overview` paragraph is
    machine-validated by §B4.7's `_r_counts_sync`. Counts that
    appear in few-shot transcripts are snapshots-for-illustration
    and NOT rule-checked (transcripts freeze a past release on
    purpose so readers can compare eras without every example
    churning per release).
- **Completeness:** Every `entry_tool` in frontmatter exists in
  `catalog.json`; every transcript's tool invocations resolve.
- **Quality (SOTA):** The doc reads as operational reference for an
  LLM that has never seen this codebase. Every architectural claim
  links to its canonical source (PRODUCT.md / this CONTRACT / the
  code) rather than restating. A first-time reader can produce a
  valid tool invocation without leaving SKILL.md.

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

#### B3.6 — Code-level benchmark harness

> Plan-level benchmark (B3.5) scores the mapping from requirement →
> primitive/tool. Code-level goes further: it runs the tool, generates
> the project, then scores an executable pytest suite over the output.
> This is the gate that catches "the plan was right but the emitted
> code is broken".

- **DoD:**
  - `benchmarks/code_level_score.json` exists; schema covers per-
    spec `score`, aggregate `overall`, `coverage` (fraction of the
    20 specs with a runnable code-level fixture).
  - Coverage ≥ 25% at v1.0; overall ≥ 70 on the covered subset.
  - `_r_code_level_benchmark` in `engine/audit/contract_check.py`
    enforces both thresholds.
- **Invariants:**
  - A covered spec scoring below 70 at two consecutive releases =
    treated as regression, investigated before the next cut.
  - Coverage monotonically non-decreasing across releases (you can
    add covered specs, you can't silently drop them).
- **Completeness:** Every covered spec has a fixture app under
  `benchmarks/code_level/<NNN>/` that `pytest -q` can execute
  without external services (or with gracefully-skipped ones).
- **Quality (SOTA):** Same run reproducibility bar as B3.5 — same
  seed, same disk state, same score (± 5 points).

#### B3.7 — Blind benchmark harness

> Blind harness runs pinned stub fixtures without the benchmark
> spec's `Expected primitives` / `Expected tools` sections visible
> to the scoring LLM. Measures what Maestro would do "cold", without
> the spec steering it.

- **DoD:**
  - `benchmarks/blind/results/` holds ≥ 1 archived run per release.
  - `_r_blind_benchmark_harness` verifies ≥ 15 blind specs authored
    with a stub fixture + a `blind_expected.json` oracle.
  - Nightly dispatch + explicit `workflow_dispatch` supported.
- **Invariants:**
  - Blind specs NEVER reveal the oracle to the scoring LLM. Cross-
    contamination (e.g. grep for `Expected primitives` in the prompt
    assembly step) = CI fail.
  - Results are reproducible given the same model + seed.
- **Completeness:** Every blind spec has both the stub fixture and
  the `blind_expected.json` oracle committed.
- **Quality (SOTA):** The blind score is published alongside plan +
  code scores in each release CHANGELOG entry — a three-number
  vector so consumers see honest capability across surfaces.

**Phase 3 exit criterion:**
```
test -f benchmarks/latest_score.json
[ $(jq '.overall_average' benchmarks/latest_score.json) -ge 30 ]
test -f benchmarks/code_level_score.json
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

#### B4.6 — VERSION triplet sync

> The repo ships THREE authoritative version files: repo-root
> `VERSION`, skill-dir `VERSION`, and `STATUS.md` frontmatter
> `version:` field. If they diverge, tooling picks up different
> numbers depending on where it starts reading — a real drift bug
> we've already hit. §B4.6 catches it at CI.

- **DoD:**
  - `/VERSION` exists (repo root).
  - `skills/SKILL-001-fastapi-production/VERSION` exists.
  - `skills/SKILL-001-fastapi-production/STATUS.md` YAML frontmatter
    carries a `version: "X.Y.Z"` field.
  - Rule `_r_version_sync` in `engine/audit/contract_check.py` reads
    all three and asserts string equality (post-normalisation —
    trimmed whitespace; no semver-parse, just equality).
- **Invariants:**
  - Bumping VERSION MUST touch all three files in the same commit.
  - Pre-release suffixes (`-rc.N`, `-beta.N`, `-alpha.N`) allowed
    and MUST be identical across the triplet.
- **Completeness:** No fourth VERSION-like file is allowed — if a
  new location is introduced, it joins the triplet check OR the PR
  is rejected.
- **Quality (SOTA):** The rule's error message names all three
  paths + their current values on failure so the fix is copy-
  pasteable.

#### B4.7 — Canonical counts sync

> Narrative docs across the repo carry counts that MUST reconcile
> against the machine-generated `INVENTORY.md` + `ledger.json`.
> Pre-freeze we had CLAUDE.md saying "194 staged", INVENTORY saying
> "181 staged" — the kind of drift that destroys trust in every other
> number in the doc. §B4.7 makes hand-maintained counts CI-rejected.
> Wave-D H5 expanded the rule to cover FREEZE and INTERFACES after
> the recipe count drifted to 385 in INTERFACES while the catalog
> + ROADMAP were at 392; Wave-E H2 reconciled this prose to match.

- **DoD:**
  - `skills/SKILL-001-fastapi-production/INVENTORY.md` is machine-
    generated; it is the canonical source for registered / staged /
    quarantined / adapter / recipe / generator counts. The
    classifier's `ledger.json` is the canonical source for the
    ledger-size total plus per-verdict subtotals
    (`NEEDS_CALLER`, `EXTRACT_MOTOR_PAIR`, …).
  - Rule `_r_counts_sync` parses INVENTORY + `ledger.json`, then
    searches for specific token patterns in **seven** narrative
    docs:
      1. `CLAUDE.md` — 4 tokens (registered / staged / quarantined /
         adapters).
      2. `STATUS.md` — 4 tokens (same four counts, table row shape).
      3. `ROADMAP.md` — 6 tokens (prior four + `Recipes` +
         `Ledger entries`).
      4. `CHANGELOG.md` **inside the `[1.0.0]` section body** —
         3 tokens (registered / adapters / staged).
      5. `SKILL.md` **inside the `## Overview` paragraph only** —
         1 combined token (`{registered} registered + {staged}
         staged`); transcripts deliberately not rule-checked.
      6. `FREEZE.md` — 2 tokens (`{ledger}-entry triage ledger`,
         `{needs_caller} NEEDS_CALLER items`).
      7. `INTERFACES.md` — 1 token (`**{recipes} recipes**`).
  - Any mismatch = CI fail with a precise list of `expected {tok}`
    lines per missing doc. The error message shows the exact token
    verbatim so authors can find-and-replace without guessing.
- **Invariants:**
  - Counts are NEVER hand-edited in the seven narrative docs;
    regenerate INVENTORY via `python -m engine.inventory`, regenerate
    `ledger.json` via `python -m engine.promotion.classify`, then
    update the narrative docs via the token-replacement patterns
    `_r_counts_sync` enforces.
  - Adding a new canonical count (e.g. "provider adapters" in the
    Overview) = schema change: add it to the INVENTORY emitter (or
    `ledger.json` if verdict-derived) AND to `_r_counts_sync`'s
    `required_tokens` dict AND to every narrative doc the new count
    belongs in, all in one commit.
  - `_r_counts_sync` is the single check that binds the seven
    narrative surfaces; §B0.4 handles body-prose tool-count drift
    inside SKILL.md only, and §B2.5 handles SKILL.md shape.
- **Completeness:** All eight count dimensions (registered / staged /
  quarantined / adapters / recipes / ledger / NEEDS_CALLER /
  EXTRACT_MOTOR_PAIR) flow from a machine source to exactly the
  narrative surfaces listed above; the rule is extensible — add a
  key to `required_tokens` to cover a new surface.
- **Quality (SOTA):** The rule's error message shows the exact
  expected token verbatim, including whitespace and punctuation —
  so doc authors can find-and-replace without guessing syntax.

**Phase 4 exit criterion:**
```
curl -sL $INSTALL_URL | bash                      # B4.1
test -d examples && [ $(ls examples | wc -l) -ge 5 ]  # B4.2
curl -sf $DOCS_URL                                # B4.3
test -f CHANGELOG.md && git tag --list | grep -q v0.1 # B4.4
test -f CONTRIBUTING.md                           # B4.5
diff <(cat VERSION) <(cat skills/SKILL-001-fastapi-production/VERSION) # B4.6
python -m engine.audit.contract_check             # all 36 green — B4.7 included
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

### Ratified YYYY-MM-DD by Gustavo (v1.0.0 pre-freeze)

Proposed + drafted by Claude; awaiting Gustavo's date + signature
alongside `FREEZE.md §4` and `ROADMAP.md §11`.

**§A amendments:**

- **§A12 amended.** The "pool, not backlog" discipline now admits
  three ratified promotion triggers:
  (a) benchmark gap demands it;
  (b) the primitive is imported by a registered tool or module;
  (c) the primitive is in-scope for a one-shot ratified triage pass
      (start and end commits cited in this §E block).
  Rationale: operational cleanup passes like Wave 1.5 (PubSub +
  Billing extraction; 3 staged + 3 quarantined items cleared)
  required a controlled escape hatch without weakening the rule
  against speculative promotion. See `docs/decisions/0004-tier-lite.md §3`.
- **§A12 token appears here** so the promotion executor
  (`engine/promotion/promote.py`) accepts `tier="lite"` work.

**§B additions** (all already landed + machine-checked via
`engine/audit/contract_check.py` pre-freeze; this block records
formal ratification):

- **§B1.7 — FastAPI adapter coverage** (ratified). Every
  `_adapters/fastapi/<Name>Adapter.py` has `test_<Name>Adapter.py`
  AND resolves to a registered primitive by the three-rule
  resolution scheme (literal strip, family map, substring match).
  Floor ≥ 15; currently 17 adapters, 100% covered.
- **§B1.8 — Tier-lite eligibility** (ratified). Registered-lite
  tier unlocked per ADR 0004. Machine check validates zero
  REPLACE_ME, no framework imports, no concurrency imports for
  every `tier: "lite"` entry. Vacuously green at 0 lite registered.
  `§B1.8 ratified` token appears here — `engine/promotion/promote.py`
  now accepts lite promotions.
- **§B2.4 — Index catalog manifest: synced + deterministic**
  (ratified). `stable_hash` idempotent across two consecutive
  builds; catalog reflects on-disk reality. Consumer pinning
  protocol documented in ROADMAP.md §2.12.
- **§B2.5 — SKILL.md v2 Anthropic Agent Skills contract**
  (ratified). `_r_skill_md_contract` parses frontmatter +
  validates ≥3 few-shot transcripts + ≥1 entry_tools list + body
  ≤ 500 lines (with Maestro-facing exceptions documented).
- **§B3.6 — Code-level benchmark harness** (ratified). Covers
  ≥ 25% of the 20-spec corpus with ≥ 70 average on covered.
  Currently 100.00 across 20/20 (100% coverage, 30-point
  headroom).
- **§B3.7 — Blind benchmark harness** (ratified). ≥ 15 blind
  specs authored with stub fixtures + `blind_expected.json`
  oracles. Nightly + workflow_dispatch.
- **§B4.6 — VERSION triplet sync** (ratified). Repo-root VERSION,
  skill-dir VERSION, STATUS.md frontmatter `version:` MUST agree
  string-equality. Machine-checked on every commit.
- **§B4.7 — Canonical counts sync** (ratified). INVENTORY.md is
  the source; CLAUDE / STATUS / ROADMAP / CHANGELOG reconcile via
  token-match. Hand-edited counts rejected at CI.

**Other:**

- **ADR 0004 (tier-lite) moves Proposed → Ratified.** Status
  flipped in `docs/decisions/0004-tier-lite.md` in the same
  commit as this block.
- **Wave 1.5 triage pass** recorded as the first §A12(c) triage
  under the new clause. Start commit: `f6bbf79`
  (`feat(SKILL-001/resiliency): add async acquire() …`). End
  commit: `d4cc4a9` (`chore(SKILL-001): delete 3 staged+quarantined …`).
  Scope: PubSub + Billing motor/adapter extraction; 3
  NEEDS_REVIEW ledger entries cleared. Ratified in retrospect
  alongside this block.

---

**End of contract. Executable. Enforceable. Sacred.**
