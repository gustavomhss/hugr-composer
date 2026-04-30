# Dual-Index Design — SOTA synthesis

> **Pre-implementation design.** Distillation of four research reports
> (Anthropic/MCP, academic, production, cognition) into a single
> executable design for two indices: one for the LLM Maestro, one for
> humans. Shared source of truth, two renderings. Nothing here is built
> yet — this document is the contract the implementation will honour.
>
> Pre-registered 2026-04-20. Changes require version bump.

---

## 1. Convergent research verdict

The four reports reached the same conclusion from four angles:

| Angle | Finding | Source |
|---|---|---|
| Anthropic official | "30-50 tools" hard cliff for flat exposure. Tool Search + `defer_loading: true` is the fix. Agent Skills (SKILL.md) is the packaging primitive. | [Tool search tool docs](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool); [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) |
| Academic (Gorilla / ToolLLM / AnyTool) | Flat past ~50 tools hallucinates. Retrieval (BM25 or dense) is the only pattern that scales. RAG-MCP 13% → 43% accuracy gain. | [arxiv 2305.15334](https://arxiv.org/abs/2305.15334), [2307.16789](https://arxiv.org/abs/2307.16789), [2402.04253](https://arxiv.org/abs/2402.04253) |
| Production (LangGraph / LlamaIndex / Cursor / SWE-agent) | Every major framework that crossed ~100 tools added retrieval. Cursor chose 15 core tools deliberately. SWE-agent: 4 primary tools + ACI design. | [LangGraph bigtool](https://github.com/langchain-ai/langgraph/tree/main/libs/langgraph/langgraph/prebuilt), [LlamaIndex ObjectIndex](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/tools/) |
| Cognition / UX | Flat list → O(n) scan. Verb-noun (kubectl ~20 verbs) collapses to O(log n). Primacy/recency U-curve demands "home tool at position 1 + reminder at tail." Stable alphabetical order (VSCode) = prompt-cache-friendly. | [NN/g progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/), [Liu et al "Lost in the Middle"](https://arxiv.org/abs/2307.03172), microsoft/vscode #27317 |

**Decision:** we implement dual-index = **(a) LLM retrieval-based surface** +
**(b) human visual navigation surface**, both generated from a single
manifest. The Anthropic Tool Search + Agent Skills combination is the
officially-sanctioned path; we adopt it.

---

## 2. Two audiences, two designs

| Dimension | LLM index | Human index |
|---|---|---|
| Consumer | Claude (Sonnet/Opus/…) via MCP | Reviewer / contributor / user |
| Budget | Tokens (prompt cache 5-min TTL) | Bandwidth + visual attention |
| Access | MCP tools/resources/prompts | HTTPS + browser |
| Latency | ≤ 50 ms (cold retrieval) | ≤ 1 s page load |
| Layout | Linear stream, positional bias | 2D tree, sidebar + main |
| Primary action | "Find the right tool for the next step" | "Understand the system + its affordances" |
| Discovery | BM25 retrieval + home tool | Category tree + full-text search + cross-links |
| Hierarchy | Verb × tag (2 levels max) | Verb × tag × namespace (3 levels, progressive) |
| Stability | Alphabetical within category (cache) | User-sortable (alphabetical default) |
| Richness per entry | Tight: name + 1-line + next_steps | Full: signature, examples, primitives, tests, provenance |
| Retrievability | Fuzzy/semantic ← sees keywords + tags | Click + keyboard shortcut |
| Non-goals | Visual polish, full examples | Token efficiency |

**Principle:** an entry in the LLM index is a *coordinate* pointing at
the corresponding human-index page. When Claude returns `next_steps:
["fastapi_auth_add_oauth2(...)"]`, a reviewer clicks into the human
index at `/tool/fastapi_auth_add_oauth2` and sees the full context.

---

## 3. Shared source of truth

Single canonical catalog at `engine/index/manifest.py` that builds
`engine/index/catalog.json` (committed, stable-ordered, schema-versioned).

```jsonc
{
  "$schema_version": "2",
  "kit_commit": "<git sha>",
  "generated_at": "2026-04-20T...Z",
  "verbs":   [ { id: "add", name: "Add", purpose: "..." }, ... ],
  "domains": [ { id: "auth", name: "Auth",  purpose: "..." }, ... ],
  "tools": [
    {
      "name": "fastapi_auth_add_oauth2",
      "verb": "add",
      "domain": "auth",
      "synopsis": "Wire OAuth2 authorization code flow with PKCE",
      "when_to_call": "Use when the spec requires third-party sign-in...",
      "when_not_to_call": "Do not use for M2M tokens (see fastapi_auth_add_jwt_m2m)",
      "inputs":  { "providers": "list[Literal[...]]", ... },
      "returns": { "files_created": "list[str]", "next_steps": "list[str]", ... },
      "primitives_used": ["AuthorizationCodeFlow","TokenIntrospector","SessionStore"],
      "tags": ["oauth","federated-identity","auth","ssh"],
      "tier": 2,                    // 1 = always loaded, 2 = deferred (Tool Search)
      "module_path": "adapt/extend/auth_access/add_oauth2_provider.py",
      "test_paths":   ["adapt/extend/auth_access/test_add_oauth2_provider.py"],
      "status": "stable",           // experimental | stable | deprecated
      "since": "v0.1.0",
      "example_input": { ... },     // concrete, not stub
      "example_output": { ... }
    },
    ...
  ],
  "primitives": [ { name, namespace, concern, purpose, compose_with, ... }, ... ],
  "recipes":    [ { id, intent, primitives, description, ... }, ... ]  // 290 recipes as first-class
}
```

Everything else (LLM registration, HTML dashboard, reference docs,
contract check B2.4) reads from this file. Anyone can regenerate via
`python -m engine.index.manifest build`.

Invariants (enforced by new contract rule B2.4):
- Every `tools[*].name` matches an on-disk module's MCP_TOOL metadata.
- Every `tools[*].primitives_used` is a registered primitive.
- Every `tools[*].tags` ⊆ the declared tag vocabulary (closed set).
- `verbs` + `domains` are frozen; adding requires a protocol bump.
- Sort order: `(domain, verb, name)` alphabetical — stable across rebuilds
  (prompt cache-friendly).

---

## 4. LLM index — surface design

### 4.1 Tier-1 tools (always loaded, ≤ 8)

Based on Anthropic Tool Search + Cognition report primacy/recency:

| Position | Name | Role |
|---|---|---|
| 1 | `fastapi_home` | Entry point. Returns the landscape: 9 domains × ~20 tools/domain. 1200-token compact map. Agent calls this FIRST, always. |
| 2 | `fastapi_search` | BM25 over 201-tool catalog. `search(query, domain?, verb?, k=10)`. Returns name + synopsis + next_steps. |
| 3 | `fastapi_scaffold` | Rails-for-LLMs entry point. Wraps `fastapi_generate_project` with opinionated defaults + auto-scaffolds common slices from spec mentions. |
| 4 | `fastapi_describe` | Deep intro to a specific tool OR primitive OR recipe. `describe("fastapi_auth_add_oauth2")` returns full schema + example. |
| 5 | `fastapi_audit` | Runs `contract_check` on the emitted workdir. Breadcrumbs to next fix. |
| 6 | `fastapi_verify` | Runs the 10-tier gate on a primitive or the whole app. Returns per-tier pass/fail. |
| 7 | (reserved) | Intentional headroom — keeps tier-1 ≤ 8 tools. |
| 8 | (reserved) | " |

Note these are **new meta-tools**, not the existing 180. Every current
`fastapi_add_*` / `fastapi_generate_*` becomes tier-2 (deferred)
reachable via `fastapi_search` or direct invocation by name.

### 4.2 Tier-2 tools (deferred, searchable)

All 180 existing tools get `defer_loading: true` in their MCP
registration. Their names get the service+domain+verb prefix
(`fastapi_<domain>_<verb>_<noun>` — e.g., `fastapi_auth_add_oauth2`,
`fastapi_data_add_soft_delete`). Full descriptions (when/when-not/
params/returns/caveats, 3-4 sentences min) per Anthropic Sep 2025 guide.

Not exposed in the default tool list. Claude pulls them in via
`fastapi_search` or `fastapi_describe` on demand. Tool Search Tool
(`tool_search_tool_bm25_20251119`) handles the actual injection.

### 4.3 MCP Resources (read-only references)

Registered at session start; Claude Code's host policy decides when to
auto-include. Per MCP spec, resources are "application-driven."

| URI | Content |
|---|---|
| `skill://readme` | LLM-friendly short SKILL.md (≤ 500 tokens). "What I am, how to use me, the 7-step workflow." |
| `skill://index` | Compact JSON of `engine/index/catalog.json` minus full schemas. |
| `skill://primitives` | 122 primitives registry (short form: name, concern, 1-line purpose). |
| `skill://recipes` | 290 compose-with recipes as structured JSON. |
| `skill://examples/{slug}` | Full `examples/NN-slug/MAESTRO_SESSION.md` for each worked example. |
| `skill://workflow` | Canonical workflow: scaffold → add_slices → audit → verify → deploy. |

Resources are the answer to "how do I put docs in front of the LLM
without burning tokens on tools I'll never call." Host implementations
(Claude Code) may auto-include them; in strict server mode, Claude can
Read them explicitly.

### 4.4 MCP Prompts (user-invoked slash commands)

Per spec, prompts are user-triggered. For human-in-the-loop runs:

| Slash command | What it expands to |
|---|---|
| `/fastapi-scaffold <brief-path>` | Reads brief, calls `fastapi_scaffold(...)`, then iterates. |
| `/fastapi-audit` | Runs `fastapi_audit` against the current workdir. |
| `/fastapi-explain <tool>` | Expands to `fastapi_describe(<tool>)` + kid-sister explanation. |

Prompts are the HUMAN-INVOKED entry points. Distinct from the
LLM-autonomous tier-1 tools.

### 4.5 Agent Skill packaging

Ship `skills/SKILL-001-fastapi-production/SKILL.md` (already exists)
restructured per Anthropic Agent Skills v2 (Oct 2025 format):

```markdown
---
name: fastapi-production
description: HuGR SKILL-001 — production-grade FastAPI backend scaffold
             (Rails-for-LLMs). Call this skill when the user asks to
             scaffold, extend, deploy, or audit a FastAPI backend.
version: 0.3.0
---
<body loaded on trigger — ≤ 5k tokens of workflow + tier-1 tool doc>
```

Anthropic loads the YAML frontmatter at session start (~100 tokens);
the body activates when the skill is triggered. Bundled scripts (the
201 tools) stay zero-context until invoked via Bash.

### 4.6 Tier-1 tool return shape (next_steps = the magic)

Every tier-1 tool returns a uniform envelope:

```python
{
  "ok": true,
  "what_happened": "Generated project at /tmp/ledger. 47 files written.",
  "files_touched": [...],
  "next_steps": [
    "Your brief mentions webhooks — call fastapi_search(\"webhook signed idempotent\") to find the right add_*.",
    "No auth in profile=minimal. Call fastapi_search(\"auth refresh token\") if the spec requires user accounts.",
    "When ready to verify: fastapi_audit() or fastapi_verify()."
  ],
  "primitives_emitted": ["Repository","UnitOfWork","AuditEvent"],
  "elapsed_ms": 3421
}
```

`next_steps` is the critical affordance. It pulls Claude to the next
action without relying on it "remembering" the workflow from the prompt.
This is the cognition-report's "breadcrumbs over menus" operationalized.

---

## 5. Human index — minimal, one-page

> **Scope-cut (user decision 2026-04-20).** The human audience needs to
> know **what's in the box**. Not navigate + compose — that's the LLM's
> job. So one page, one table, searchable. Nothing else.

### 5.1 Single page: `/catalog.html`

- Three sections, collapsible: Tools (180), Primitives (122), Recipes (290).
- One row per entry. Columns tuned per section but all rows have:
  `name · category · one-line description · source link`.
- Client-side fuzzy search (VSCode subsequence algorithm) with sigil
  filters in the search box:
  - `>auth` → filter by domain
  - `@add` → filter by verb
  - `#webhook` → filter by tag
- Stable alphabetical sort within each section. No recency re-order.
- Source link per row → opens the underlying `.py` / `.md` on GitHub.
- No per-entity pages, no cross-links, no recipe walkthroughs. Those
  are the LLM's concern — the LLM has MCP resources + the catalog.json
  for deep navigation.

### 5.2 What is intentionally NOT shipped in the human index

- Per-tool pages (180 HTML files) — deleted from scope.
- Per-recipe pages (290 HTML files) — deleted from scope.
- Workflow walkthroughs — LLM-oriented, no reviewer need.
- Timelines, diff-by-version — reviewers read CHANGELOG.md for that.
- "Open in LLM session" button — reviewer is not the LLM.

Total page count: **1**. Previous design had 620+ HTML files (one per
tool + primitive + recipe + example + doc). The simpler surface is the
correct one for the actual human use case.

---

## 6. Migration — the actual work

A carefully staged sprint. Each step atomic, contract-green, reverts cleanly.

### Step A — Build the manifest (1 commit)

- `engine/index/manifest.py` — scans adapt/, generators/, mcp_tools/,
  primitives_by_concern.yaml, examples/, recipes; produces `catalog.json`.
- `engine/index/schemas.py` — Pydantic contracts for every entry shape.
- `engine/tests/test_manifest.py` — validates every MCP_TOOL maps to a
  manifest entry and vice-versa; every primitive used by a tool is
  registered; tag vocabulary is closed.
- New contract rule B2.4 "manifest is registry-synced."

### Step B — Rename tools to the `fastapi_<domain>_<verb>_<noun>` scheme (1 commit)

- Deterministic rename driven by the manifest.
- Every rename recorded in CHANGELOG with old → new mapping (so
  external integrators can search-replace).
- Backwards-compat shim: old names remain registered for one MINOR
  cycle with a deprecation description.

### Step C — Mark all current tools as deferred; add tier-1 meta-tools (1 commit)

- `MCP_TOOL["defer_loading"] = True` on every add_/generate_/… tool.
- New tier-1 tools:
  - `fastapi_home` / `fastapi_search` / `fastapi_scaffold` /
    `fastapi_describe` / `fastapi_audit` / `fastapi_verify`.
- Register Anthropic's `tool_search_tool_bm25_20251119` alongside
  (with defer_loading behavior).

### Step D — Ship MCP Resources surface (1 commit)

- `mcp_tools/resources.py` registers the 6 `skill://` URIs from §4.3.
- Corresponding content assembled from existing files (SKILL.md,
  primitives_by_concern.yaml, examples/, etc.) + the new manifest.

### Step E — MCP Prompts slash commands (1 commit)

- `mcp_tools/prompts.py` registers `/fastapi-scaffold`,
  `/fastapi-audit`, `/fastapi-explain`.

### Step F — `next_steps` wiring across all tier-1 returns (1 commit)

- Central helper `engine.index.breadcrumbs.next_steps_for(context)`
  inspects the return state + brief + manifest, returns the 2-3 most
  likely next actions. LLM-oriented prose.

### Step G — Tool descriptions pass (1 large commit)

- Every tool's description rewritten to the 3-4 sentence when-to-call /
  when-not / params / returns / caveats template. Derived from the
  manifest's `synopsis` + `when_to_call` + `when_not_to_call` fields
  (authoring burden is one manifest entry per tool, not 180 Python docstrings).

### Step H — Human index rebuild (1-2 commits)

- `engine/docs/build_v2.py` — reads `catalog.json`, emits the new
  pages from §5.1.
- Tag chips + sigil filters added to `search.js`.
- B4.3 contract rule tightened to require recipe + tool pages.

### Step I — Live benchmark re-run (Phase 6 blind harness, new run_id)

- Kit arm uses the new skill surface. Expectation: Claude calls
  `fastapi_home` at turn 1, `fastapi_scaffold` at turn 2-3,
  `fastapi_audit` at end. Orders of magnitude fewer tokens vs the
  current-state runs (runs 1-4 in `benchmarks/blind/results/`).

### Step J — Contract rule B3.7 tightening

- Rule now requires `catalog.json` exists, matches live MCP surface,
  `next_steps` present in tier-1 returns, tier-1 tool count ≤ 8.

Rough estimate: 9-10 commits. Each reversible. Every step keeps
31/31 green; the new rules B2.4 and tighter B3.7 bring us to 32-33/33.

---

## 7. Success criteria (measurable)

- [ ] `engine/index/catalog.json` exists, schema-validated, 180+ tool
      entries, 122 primitive entries, 290 recipe entries.
- [ ] Tier-1 MCP tool count ≤ 8. Tier-2 count ≥ 170 with defer_loading=True.
- [ ] `fastapi_home()` response ≤ 1200 tokens.
- [ ] `fastapi_search(query)` returns in ≤ 100 ms on the 201-tool corpus.
- [ ] `catalog.json` regenerated deterministically: same kit commit →
      identical SHA-256 (prompt-cache friendly).
- [ ] Human index: every tool page, every primitive page, every recipe
      page builds; Lighthouse ≥ 90 on landing; mobile responsive verified.
- [ ] Blind-benchmark live run on hard/01 with new surface:
      - Claude calls `fastapi_home` at turn ≤ 2.
      - Claude uses ≥ 3 kit tools (not just Write/Bash).
      - Emitted code imports ≥ 2 primitives from `core.venous.*`.
      - Margin kit-vs-naked ≥ 20 pts (first real discrimination data).
- [ ] Contract: 31/31 → ≥ 33/33 ALL GREEN (B2.4 + tightened B3.7).

---

## 8. What this does NOT do

- Does NOT reduce the 201-tool capability surface. Every existing tool
  stays reachable (as tier-2 deferred). No capability regression.
- Does NOT require retraining Claude. Uses Anthropic-native primitives
  (Tool Search, Agent Skills, deferred tools, resources, prompts).
- Does NOT introduce a parallel orchestration engine. We concluded in
  the prior discussion that a bespoke orchestrator is overhead; the
  fix is organization + retrieval + rich descriptions.
- Does NOT change the benchmark methodology. The blind harness is the
  measurement instrument; this work changes WHAT is being measured on
  the kit side, not HOW.

---

## 9. Open questions (surface before implementation)

1. **Tier-1 tool names.** Proposed `fastapi_home / search / scaffold /
   describe / audit / verify`. Alternatives: `skillkit_*` (cross-skill
   neutral), `hugr_*` (org neutral). Decision affects future SKILL-002.
2. **Closed tag vocabulary.** How many tags, what are they? Suggestion:
   ~30 tags across 9 domains, reviewed as part of Step A.
3. **Backwards-compat window for old names.** Proposed 1 MINOR cycle
   (v0.3.x); v0.4.0 removes the shims.
4. **"Recently used" in human index.** Client-side localStorage or
   server-side per-user? localStorage keeps us stateless-deployable.
5. **Anthropic Tool Search vs self-built BM25.** Anthropic's is
   official + integrated + claims 85% reduction. Ours is the existing
   `engine/discovery/find_primitive.py` (BM25 over primitives). For
   tools, defer to Anthropic's. For the human-index search, keep ours
   (different index, different ranking needs).
6. **Recipe-as-tool?** Should each of the 290 recipes become a
   callable tool that emits the composition? Cognition says no (290 is
   >> any threshold). Instead, `fastapi_describe("recipe:<id>")`
   surfaces the recipe on demand; recipes remain first-class in the
   human index.

---

Signed — design for review, 2026-04-20.
