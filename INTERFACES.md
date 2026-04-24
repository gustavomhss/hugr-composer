# INTERFACES — SKILL-001 ↔ Maestro / Forge contract

> **Purpose:** enumerate exactly what the skill promises to Maestro
> (consumer LLM agent) and to Forge (host editor/runtime). Anyone
> building against the skill reads this and knows what's stable, what's
> versioned, and what they can rely on.
>
> **Audience:** Maestro session & Forge session (pass verbatim to
> those teams).
>
> **Binding at:** v1.0.0. Breaking changes only on MAJOR bumps.

---

## §1 — How the skill is distributed

The skill is a **standalone module** living at `skills/SKILL-001-fastapi-production/`
in this repo. It has no runtime dependency on Forge or Maestro — both
consume it, neither owns it.

Installation surface:
- **Path install** (copy directory) — `install.sh` at repo root.
- **Docker smoke** — `.github/workflows/install-docker.yml` runs
  `install.sh` inside the stock `python:3.12-slim` container image
  (declared via `container: image: python:3.12-slim` in the
  workflow). There is NO repo-level `Dockerfile`; the workflow is
  the only gate, which keeps the install flow single-sourced and
  removes a Dockerfile-vs-install.sh drift risk. Validated nightly
  + on any change to `install.sh`, `pyproject.toml`, `VERSION`, or
  `requirements-mcp.txt`.
- **PyPI** — *not* shipped in v1.0. Install from git ref for now.

File that identifies the skill to a host:
- **`skills/SKILL-001-fastapi-production/SKILL.md`** (Anthropic Agent
  Skills format: YAML frontmatter + ≤500-line body). This is the
  entry point Maestro reads first.

---

## §2 — Contract exposed to **Maestro** (consumer)

Maestro is an LLM agent that invokes skill tools via MCP to build
FastAPI backends. The contract to Maestro has four surfaces:

### §2.1 — MCP tool catalog

Authoritative list: **`skills/SKILL-001-fastapi-production/engine/index/catalog.json`**.

- Versioned by the skill's semver. v1.0.0 catalog ships with its own
  `stable_hash` field embedded (SHA-256 of catalog content excluding
  the three non-deterministic fields `generated_at`, `kit_commit`,
  `stable_hash` itself). Consumers read it via
  `jq -r .stable_hash engine/index/catalog.json`.
- Every tool entry carries: `name` (canonical `fastapi_<domain>_<verb>_<noun>`),
  `legacy_name`, `verb`, `domain`, `synopsis`, `when_to_call`,
  `when_not_to_call`, `tags`, `tier`, `status`, `since`, `module_path`,
  `test_paths`, `primitives_used`, `example_input`, `example_output`.
- Count at v1.0.0: **201 catalog tools** (does NOT include the 7
  tier-1 meta tools or the 9 tree dispatchers; see §2.1.1 for the
  total surface).

### §2.1.1 — Tool surface total (201 + 7 + 9 = 217)

Three separate registration paths feed the Maestro MCP server:

1. **201 catalog tools** — scanned from `adapt/`, `generators/`,
   `modules/`, `benchmark/`, `meta/`, `core/tools/`,
   `engine/discovery/` (see `TOOL_SCAN_ROOTS` in
   `engine/index/manifest.py`). These are what `fastapi_meta_search`
   returns.
2. **7 tier-1 meta tools** — `mcp_tools/tier1.py` + `mcp_tools/compose.py`.
   Registered via `register_tier1_tools`. Deliberately excluded from
   the catalog scan because they operate ON the catalog (circular).
3. **9 tree dispatchers** — `mcp_tools/tree/*.py`. Registered via
   `register_tree_tools`. Also excluded from the catalog scan (they
   route to catalog tools via the dispatcher pattern).

**Stability guarantees (all three paths):**
- Tool names are **frozen** at v1.0.0. Renaming forbidden without a
  MAJOR bump.
- `primitives_used` on catalog entries is ground truth for "what this
  tool imports".
- New tools can be added in MINOR releases; deletions/renames need MAJOR.

### §2.1.2 — Tier-1 meta tools (7)

Always stable; the first tool Maestro calls in a session:

- `fastapi_meta_home` — skill landscape (domains × top tools × counts).
- `fastapi_meta_search` — BM25 over tools + primitives + recipes.
- `fastapi_meta_describe` — full spec for one id.
- `fastapi_meta_scaffold` — invokes `generate_project` with provenance.
- `fastapi_meta_compose` — 4-tier fallthrough
  (adapter_reuse > tool_delegate > recipe_template > ad_hoc).
- `fastapi_meta_audit` — runs `engine.audit.contract_check` on the
  SKILL tree itself (§A + §B rules). Skill-kit integrity ONLY.
- `fastapi_meta_verify` — runs the 10-tier primitive quality gate
  (`engine.check_primitive`) on the registered primitive surface
  of the skill tree. Skill-kit integrity ONLY.
- Emitted-project validation is intentionally out of scope for the
  meta surface; the scaffold ships its own `tests/` directory and
  pre-commit config — run `pytest` inside the emitted project for
  project-level validation. See SKILL.md §Workflow step 6 for the
  two-layer split.

### §2.1.3 — Tree dispatchers (9)

Domain routers; one per concern:

`fastapi_auth`, `fastapi_data`, `fastapi_api`, `fastapi_realtime`,
`fastapi_resiliency`, `fastapi_observability`, `fastapi_compliance`,
`fastapi_deployment`, `fastapi_testing`.

Each dispatcher takes a `(action, **kwargs)` tuple and forwards to
the matching catalog tool. Names are frozen; adding a new domain
requires a MINOR bump + a new dispatcher.

### §2.2 — Primitive catalogue

Authoritative list (registered): **`engine/primitives_by_concern.yaml`**
(schema in `engine/index/schemas.py`, `PrimitiveEntry`).

- **124 registered primitives** at v1.0.0, each with full shell
  (contract.json + protocol + md + tests + TLA+ + dashboard + invariants).
  `tier` field: `"full"` for all v1.0.0 registered primitives;
  `"lite"` is defined in §B1.8 but no v1.0.0 primitive ships at that
  tier (reserved for post-v1.0). Wave 1.5 added `events.PubSub` and
  `billing.Billing` (see FREEZE §1.6.5).
- **176 staged primitives** discoverable via `fastapi_meta_search`
  with `status="staged"` — usable as reference, NOT production-ready.
  Distributed across `_extracted/<namespace>/` (134) and
  `_extracted/_quarantine/` (42 PascalCase). Lowercase function
  extractions + the 3 Wave-1.5-redundant entries cleaned up.
- **17 FastAPI adapters** under `core/venous/_adapters/fastapi/`
  (the 17th, `BulkheadAdapter`, landed in Wave 1 pre-freeze — see
  FREEZE §1.6). Plus **2 provider adapters** beyond fastapi/:
  `_adapters/redis/PubSubAdapter.py` and
  `_adapters/stripe/BillingAdapter.py` (see FREEZE §1.6.5). Provider
  adapters are framework-isolated: consumers only opt in to the
  dependency when they select the matching backend.

**Stability guarantees:**
- Registered primitive names + namespaces frozen at v1.0.0 (MAJOR
  bump required for renames).
- Staged primitives are unstable; Maestro should cite them only
  after human review and only if a §A12(b) signal exists.
- Each registered primitive exports the class/protocol named in its
  manifest; module path is `core.venous.<namespace>.<Name>.<Name>`.

### §2.3 — Composition recipes

- **392 recipes** parsed from primitive `.md` `## Compose with:`
  sections.
- Searchable via `fastapi_meta_search_composition`.
- Every recipe names ≥ 2 sibling primitives + the invariant their
  composition guarantees.

**Stability guarantee:** recipe IDs are stable within a MINOR release;
a recipe can be refined but not removed mid-minor.

### §2.4 — What Maestro MUST do

- Always load `SKILL.md` first.
- Always check `status` of any primitive before citing — refuse to
  emit code referencing a `status="staged"` primitive without calling
  it out in the session transcript.
- Always call `fastapi_meta_scaffold` (not `generate_project` directly)
  so provenance manifest is written.
- Never emit generated code that imports framework modules
  (`fastapi`, `starlette`, `sqlalchemy`, `pydantic`) from
  `core.venous.<ns>.<Name>` — only from `core.venous._adapters.fastapi.*`.

### §2.5 — Points of attention for the Maestro session

1. **Canonical names locked.** If a benchmark run shows Maestro calling
   legacy names (`add_auth_jwt` vs `fastapi_auth_add_auth_jwt`), fix
   Maestro prompt, not the skill — skill's canonical names don't shift.
2. **Compose tier discipline.** Maestro must try tier 4a (tool_delegate)
   before falling to ad-hoc emission. Regression: if examples show
   Maestro skipping tiers, tighten the prompt.
3. **Staged primitive opt-in.** Maestro may only promote a staged
   primitive to production scaffold if it also writes a benchmark
   spec that cites the need (§A12 respected).
4. **No editing under `core/venous/_adapters/`** without matching
   primitive update. If Maestro tries to patch an adapter inline, that's
   a bug — adapter edits go through the adapter's own test suite.

---

## §3 — Contract exposed to **Forge** (host editor)

Forge is the HuGR editor runtime where Maestro sessions execute. Forge
loads the skill and exposes it to the running Maestro.

### §3.1 — Skill discovery

- Forge must treat `skills/SKILL-001-fastapi-production/SKILL.md` as
  the canonical entry point for the skill.
- SKILL.md follows the **Anthropic Agent Skills format**: the YAML
  frontmatter declares exactly three keys — `name`, `description`,
  `license` — nothing else. `description` is the Maestro-facing
  one-paragraph When-to-use (800-1200 chars, ≥3 transcripts in the
  body; machine-verified by `_r_skill_md_contract` — CONTRACT §B2.5).
- Canonical counts + entry-tool list + phase model + invariants are
  **body metadata**, not frontmatter. They live in a
  `## Machine-readable metadata` fenced YAML block containing:
  `hugr_skill_version` (semver), `spec_compat` (HuGR spec range),
  `kind`, `domains`, `entry_tools` (the 8 tier-1 tool names Forge
  surfaces first), `catalog_path` (`engine/index/catalog.json`),
  `phases`, `invariants`. Forge reads the YAML block for tool
  registration + session filtering.
- Counts (tools / registered / staged / adapters / recipes / ledger)
  are NOT in SKILL.md — they live in `INVENTORY.md` (machine-
  generated from disk) and the `counts` object inside
  `engine/index/catalog.json`. Cite those — never SKILL.md — for
  runtime numbers, since SKILL.md is prose + must stay stable
  across minor count drifts.

### §3.2 — MCP server lifecycle

- Forge spawns the MCP server via `mcp_tools/discovery.py::discover`
  (the single registration entry point). No "equivalent" alternatives
  — the helper is the contract.
- `discover(mcp_app)` sequentially calls:
  1. Auto-discovery scan over `TOOL_SCAN_ROOTS` (see
     `engine/index/manifest.py`): `adapt/`, `generators/`, `modules/`,
     `benchmark/`, `meta/`, `core/tools/`, `engine/discovery/`. Returns
     registered count.
  2. `register_tier1_tools(mcp_app)` — binds the 7 tier-1 meta tools.
  3. `register_tree_tools(mcp_app)` — binds the 9 tree dispatchers.
  4. `register_discovery_tools(mcp_app)` — binds legacy BM25 discovery
     aliases (CONTRACT §B2.1 + §B2.2).
- Server expects `PYTHONPATH=skills/SKILL-001-fastapi-production`.
- Server startup is **deterministic**: tools registered in
  filesystem-sorted order within each scan root; tier-1 + tree sets
  registered in fixed code order.
- Forge SHOULD compare the `stable_hash` from
  `engine/index/catalog.json` against a cached value at session start
  and surface a "skill updated during session" warning if they differ.

### §3.3 — Generated project provenance

- Every scaffolded project receives a `.venous_manifest.json` at its
  root listing which primitives + adapters were copied.
- Forge must NOT mutate this file — tools use it to detect already-
  shipped code on re-invocation (idempotency).

### §3.4 — Audit surface

- `engine/audit/contract_check.py` — **36 machine-check rules at
  v1.0** (§B0.1..§B4.7; includes §B1.8 tier-lite, §B2.5 SKILL.md
  Agent Skills contract, §B3.6 code-level harness, §B3.7 blind
  harness, §B4.6 VERSION triplet, §B4.7 counts sync w/ recipes +
  ledger). Exit 0 = green; any non-zero exit on `main` is a CI
  block. The CONTRACT.md §B bullet list is the binding spec; the
  rule count above reconciles to the length of the `RULES` tuple in
  `contract_check.py`.
- `engine/inventory.py` — regenerates `INVENTORY.md` from disk;
  byte-stable output.
- `engine/bench/blind/runner.py` — runs blind plan-level benchmark;
  writes `benchmarks/blind/results/*.json`.
- `engine/bench/code_level.py` — runs code-level benchmark across
  the 20 examples; writes `benchmarks/history/YYYY-MM-DD.json`.
- `engine/promotion/classify.py` + `engine/promotion/ledger.py` —
  triage pool; re-runnable without side effects.
- `engine/promotion/promote.py` — approved-action executor; refuses
  any entry that isn't `PROMOTE_AS_*` with zero blockers.
- Forge should expose these as one-click CI hooks in the editor.

### §3.5 — Version compatibility

Forge declares a **supported skill MAJOR range** (e.g. `>=1,<2`). The
skill loader reads `skills/SKILL-001-fastapi-production/VERSION` and:

- If the file's MAJOR is inside the supported range → load normally.
- If MAJOR is above range → refuse to load (surface "upgrade Forge").
- If MAJOR is below range → refuse to load (surface "upgrade skill"
  OR allow with explicit opt-in, Forge's call).

Forge declares its supported range at first-boot and bumps it
explicitly when tested against a new skill MAJOR. No auto-accept.

Skill MAJOR bumps are announced in CHANGELOG.md under a dedicated
`### Breaking changes` header so Forge maintainers can react.

### §3.6 — Points of attention for the Forge session

1. **Skill is not a plugin owned by Forge.** Forge reads the skill,
   does not rewrite it. Any change to skill files during a session
   is a bug — write to the user's generated project, never to
   `skills/SKILL-001-fastapi-production/`.
2. **Catalog hash pin.** Forge should record the skill's
   `stable_hash` at session start. If the hash changes mid-session
   (skill update during work), surface a notice before invoking tools.
3. **Install validation.** Forge's skill-import path must run
   `engine.audit.contract_check` on import. Skill with non-zero exit
   should be loaded in read-only mode (search/describe only), not
   scaffold/compose.
4. **Adapter registration.** Forge should NOT auto-register adapter
   files (`_adapters/fastapi/*.py`) as Maestro tools. Adapters are
   called from generated code, not via MCP.

---

## §4 — Shared guarantees (apply to both Maestro and Forge)

### §4.1 — Semver binding

- MAJOR = incompatible surface changes (tool renames, primitive
  renames, MCP schema changes, removal of a tier-1 meta tool).
- MINOR = additive (new tools, new primitives, new recipes, new
  adapters, new examples).
- PATCH = bug fixes, docs, non-surface refactors.
- Every release cites its plan + code benchmark scores in CHANGELOG.

### §4.2 — Frozen files (no change without MAJOR bump)

- `engine/index/catalog.json` schema.
- `engine/primitives_by_concern.yaml` schema (entry keys, `tier` literal).
- Tier-1 meta tool names + return shapes.
- Tree dispatcher names + kwargs names.
- `.venous_manifest.json` schema.
- CONTRACT §A (12 inviolable rules).

### §4.3 — Non-frozen (can evolve within MINOR)

- Tool `synopsis`, `when_to_call`, `when_not_to_call`, `example_*`.
- Primitive `.md` composition recipes.
- Benchmark specs (can be added; can't be removed mid-major).

### §4.4 — Error surface

- Skill errors use `skill_error_code` + `message` + `remediation`
  (stable schema).
- Forge surfaces the remediation string to the user.
- Maestro surfaces error_code in the session transcript.

---

## §5 — Escalation path

- **Discrepancy between skill and this doc:** skill wins for runtime
  behaviour; this doc wins for contractual intent. File an INTERFACES
  drift issue, update both in the same PR.
- **Breaking-change request from Maestro or Forge team:** opens a
  MAJOR-bump discussion, not a silent patch.
- **Security issue:** out-of-band to Gustavo; skill has no runtime
  hotfix path beyond a PATCH release.

---

## §6 — Open questions for Maestro + Forge teams

Items the skill cannot answer unilaterally; relay to those sessions:

1. **Maestro:** what's the expected transcript format when skill tools
   are invoked? The skill produces structured `ToolResult`s; Maestro
   session must decide render format.
2. **Maestro:** how should staged primitives be presented in search
   results — filtered out by default, or shown with warning badge?
3. **Forge:** does the skill loader run in the same process as the
   Maestro session, or is it IPC? Affects how `MCP_TOOL` discovery
   errors surface.
4. **Forge:** does the editor have a per-skill "pinned catalog hash"
   UI? If yes, skill `stable_hash` flow should integrate; if no, add
   to §3.6 roadmap.
5. **Both:** is there a shared **session replay** format (Maestro
   transcript + generated project snapshot) that includes the skill
   version + stable_hash so failures can be reproduced? The skill
   doesn't define it today.
6. **Forge:** install strategy — does Forge vendor the skill inside
   its distribution, or fetch from a pinned git ref at runtime?
   Affects §3.5 version compatibility enforcement.

---

## §7 — Change log for this doc

- 2026-04-22: initial draft (Claude). Awaits Gustavo review + relay
  to Maestro + Forge sessions.
