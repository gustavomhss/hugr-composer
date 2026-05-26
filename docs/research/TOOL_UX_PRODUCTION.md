# Research Findings — Production Agent Tool Patterns (v1, 2026-04-20)

> Mission: benchmark how top agent frameworks organize + expose tool surfaces at scale,
> and extract patterns for HuGR Arsenal (currently 180 flat MCP tools, empirically
> under-used by Claude). Sources span 2024-2026 with most evidence from late 2025/2026.

## TLDR (7 bullets)

1. **The flat catalog is a known failure mode, not a HuGR bug.** Every major framework that
   crossed ~100 tools hit the same wall and responded with **retrieval-over-registry**:
   LangGraph `bigtool`, LlamaIndex `ObjectIndex`, Anthropic Tool Search Tool, RAG-MCP,
   Toolshed. Empirical ceiling is ~50-100 tools per single invocation; above that
   selection accuracy collapses (RAG-MCP reports 13.6% baseline → 43.1% with retrieval).
2. **Anthropic's own guidance (Oct 2025 "Writing effective tools for agents") is the single
   most actionable source** for HuGR. Tool Search Tool claims 85% token reduction at ~100+
   skills; "efficiency starts degrading" past that threshold is stated explicitly.
3. **Naming > descriptions > count.** Every framework converges on `service_verb_object`
   namespacing (Anthropic: `github_list_prs`, `slack_send_message`). HuGR's
   `add_{feature}` is shallow — collides across domains and is not service-namespaced.
4. **SWE-agent's ACI paper is the canonical design doctrine for code-gen agents.**
   Four tools, lint-on-edit, consolidated actions. Fewer, smarter tools beat many dumb ones.
   Zapier ships 8000 integrations but exposes 30k actions through MCP — the catalog is
   a retrieval layer, not the agent's working set.
5. **Rails/Yeoman's lesson for HuGR is hierarchy + sub-generators**, not flat names.
   `rails generate scaffold User` / `yo name:subcommand` — namespacing is the discovery
   mechanism. HuGR already has `extend/crud_data/`, `extend/auth_access/` on disk but
   does not project that hierarchy into tool names or MCP surface.
6. **Semantic Kernel deprecated its planners** (Stepwise, Handlebars) in favor of native
   function calling. The industry consensus: stop encoding multi-step plans in framework
   code; let the model plan if tools are well-designed, otherwise gate with graph state
   (LangGraph dynamic tools, CrewAI Tasks).
7. **MCP won the protocol layer but surfaces the UX problem.** MCP's `tools/list` dumps
   all metadata into context → "tool bloat" is the canonical 2025 complaint
   (arxiv:2505.03275, WRITER engineering blog, RedHat Nov 2025). Solution is not to
   abandon MCP but to add a retrieval tier in front of it.

## 1. Framework comparison table

| Framework | Typical tools / call | Organization | Discovery | Notes |
|---|---|---|---|---|
| **LangChain / LangGraph** | 10-50 direct; unlimited via `bigtool` | Flat list of `StructuredTool` + optional Store index | Semantic search over LangGraph memory store; `create_agent(retrieve_tools_function=...)` | `langgraph-bigtool` demo tops out at ~50 `math` tools; dynamic tool calling (2025) lets different graph nodes see different toolsets |
| **LlamaIndex** | 10-30 direct; unlimited via `ObjectIndex` | `ToolSpec` bundles (e.g. Gmail = N functions under one spec) | `ObjectIndex` + `ObjectRetriever` → top-k tools injected into function-calling API | Bundles are the key primitive: service-level, not action-level |
| **Semantic Kernel** | Dozens of plugins, each w/ N `KernelFunction`s | 2-level: Plugin → Function. Auto-discovery from attributes/decorators | Native function calling (planners deprecated 2024-2025) | Closest spiritual match to HuGR's `extend/{category}/{tool}` layout |
| **OpenAI Assistants / Function Calling** | Hard cap 128; degradation well before | Flat `tools` array on request | None built-in; devs bolt on retrieval | o3/o4-mini "in distribution" at <100 tools, <20 args each |
| **Anthropic Claude (direct + MCP)** | ~100 before quality drops | Flat; optional Tool Search Tool | **Tool Search Tool** (Oct 2025): on-demand loading, 85% token reduction at ~100+ skills | Descriptions capped 1024 chars; explicit service namespacing guidance |
| **CrewAI** | 3-10 per Agent | 3-tier: Crew → Agent → Tool. Tools attached per-agent role | Static binding at Agent construction; no retrieval | Scoping by role is the discovery mechanism (agent only sees its own tools) |
| **AutoGen** | 5-20 per agent | Per-agent tool lists in conversation config | Static; group-chat routing via agent selection | — |
| **Cursor** | ~15 core (`edit_file`, `read_file`, `grep`, `run_terminal`, ...) | Flat, hard-coded | None — fixed working set; repo search is a tool, not discovery | Matches SWE-agent ACI philosophy: few tools, smart affordances (semantic diff apply model) |
| **SWE-agent** | 4 primary + scripted helpers | Flat, ACI-designed | None — tiny working set by design | Linter-integrated edit, 100-line file viewer, directory search |
| **MCP ecosystem** | 100s exposed; 10s usable per session | Per-server bundles; `tools/list` pagination | `tools/list` is eager by default → "prompt bloat"; RAG-MCP / MCPProxy add retrieval | Protocol won adoption but made the UX problem global |
| **Zapier** | 30,000+ actions over MCP | Per-app (8000 apps) → action | Natural-language search; agent-side MCP server | Agents see curated subsets; full catalog is human-facing |
| **VS Code command palette** | ~1000-2000 commands | Flat with category prefix (`Git: `, `Python: `) | Fuzzy search, but sorted stably by name (intentional — aids memorization) | Stability over ranking: commands keep their position so users learn the list |
| **Rails generators** | ~20 top-level | Hierarchical: `rails g scaffold User name:string` | `rails g -h` lists groups; sub-generators discovered from `lib/generators/` | `scaffold` is a meta-generator composing others — HuGR's composition story in 2010 form |
| **Yeoman** | Unlimited via `yo <generator>:<sub>` | 2-level namespace | Discovery via npm + `generators/` folder convention | Sub-generator composition is explicit, not implicit |

## 2. Patterns worth copying

- **Retrieval-over-registry (LangGraph bigtool / LlamaIndex ObjectIndex / Anthropic Tool Search Tool / RAG-MCP).**
  *What:* Replace the eager `tools/list` with a 2-call protocol: first an LLM call with
  one meta-tool `search_skills(query, k=5)`; then a second call with only the top-k skill
  schemas loaded. *Why:* RAG-MCP reports 3× tool-selection accuracy (13% → 43%) and 50%+
  prompt-token reduction. *How for HuGR:* wrap `mcp_tools/discovery.py` registration with
  a `tier=1 (always loaded)` vs `tier=2 (retrievable)` flag, keep 10-15 always-loaded
  orchestration tools, demote the 165 specific `add_*` tools to retrievable.

- **Service-namespaced tool names (Anthropic Oct 2025 guidance).**
  *What:* `fastapi_crud_add_soft_delete` instead of `add_soft_delete`.
  *Why:* Anthropic explicitly cites "especially important when using tool search".
  HuGR's filenames already carry the implicit namespace (`adapt/extend/crud_data/add_soft_delete.py`);
  just project it into `MCP_TOOL["name"]`.

- **ToolSpec bundles (LlamaIndex).**
  *What:* Group N related functions under one importable object.
  *How for HuGR:* expose `fastapi_crud` as a single MCP "tool" whose first param is
  `action: Literal["add_soft_delete","add_audit_log",...]`. Reduces surface from 180
  to ~8 (one per `extend/` subfolder). Compatible with MCP — the schema enum encodes
  the taxonomy.

- **Sub-generator composition (Rails scaffold / Yeoman).**
  *What:* A "meta" generator that fans out to N primitive ones.
  *How for HuGR:* `fastapi_scaffold_resource(name, fields, features=[...])` composes
  model + CRUD + auth + pagination in one tool call. Rails proved this UX for 20 years.

- **Per-role tool scoping (CrewAI).**
  *What:* Each agent only sees tools relevant to its role.
  *How for HuGR:* if Maestro has phases (plan → generate → verify → operate), expose
  only phase-relevant tools. Maps onto existing `extend/`, `verify/`, `operate/`,
  `evolve/` directory structure — the infrastructure is already there.

- **Lint-on-edit / result-side validation (SWE-agent ACI).**
  *What:* Tools reject invalid output before returning.
  *How for HuGR:* already implemented via AST-parse-before-return; reinforce and
  document as an ACI principle, not an incidental check.

- **Semantic-diff + fast-apply model (Cursor).**
  *What:* Don't make Opus rewrite files; emit diff + let Haiku apply.
  *How for HuGR:* this is exactly the Layer 2 → Layer 3 split in PRODUCT_VISION.md.
  Confirms the architecture; cite Cursor as precedent in docs.

## 3. Anti-patterns observed

- **Eager `tools/list` dump into context (vanilla MCP).** Every agent invocation
  re-pays the token cost for tools it won't use. WRITER engineering blog and RedHat
  Nov 2025 converge on this as the #1 MCP scaling pathology.

- **Framework-encoded planners (Semantic Kernel Stepwise / Handlebars, LangChain
  AgentExecutor).** Both deprecated/superseded in 2024-2025. Lesson: don't hardcode
  multi-step workflows in framework code; either let the model plan (well-designed
  tools) or gate with typed graph state (LangGraph) — not a third DSL.

- **Overlapping tool purposes with vague descriptions (OpenAI community, arxiv:2602.14878
  "MCP Tool Descriptions Are Smelly").** The failure mode is not tool count alone — it's
  count × semantic overlap. HuGR's 100 `extend/` tools risk this: `add_search`,
  `add_cursor_pagination`, `add_bulk_operations` — are these composable or alternatives?
  The tool description must say.

- **Fuzzy-ranking command palettes that reorder results on every keystroke.** VS Code
  deliberately rejects this: stable sort aids human learning. For LLMs the analog is
  *don't re-embed descriptions between calls* — keep retrieval deterministic within a
  session so the agent can cache "I searched for X and got Y" reasoning.

- **Tool descriptions as marketing copy.** Anthropic: keep ≤1024 chars, high-signal,
  semantic identifiers only. Bloated responses waste context and degrade next-step
  reasoning.

## 4. Rails / Yeoman / cookiecutter lessons

What makes `rails generate -h` work for humans and could work for LLMs:

1. **Hierarchy in the name itself.** `rails g scaffold User` encodes domain (scaffold),
   target (User), and implicit ordering (model → controller → views → tests). The LLM
   analog: `fastapi_scaffold_resource(name="Invoice", fields={...})` instead of 8 separate
   `add_*` calls.
2. **Sub-generator registry auto-discovery.** Rails walks `lib/generators/`; Yeoman walks
   `generators/` + npm. HuGR already walks `adapt/**/*.py` for `MCP_TOOL` dicts — same
   pattern. Missing: the **group** level (category → tool), which Rails surfaces in
   `rails g -h` output but HuGR flattens into 180 names.
3. **Composition over primitives.** Rails `scaffold` = model + migration + controller +
   routes + tests. One command, many files. HuGR's `extend/` tools are at the primitive
   tier; a `scaffold`-tier composition layer is missing.
4. **Cookiecutter hooks (`pre_prompt`, `pre_gen_project`, `post_gen_project`).** Validation
   and file manipulation at lifecycle boundaries. HuGR's `ensure_prerequisites()` is the
   equivalent of `pre_gen_project`; explicit post-hooks (register router, update config)
   are currently scattered inside each tool.

Translation for LLMs: **two-tier taxonomy is universal** because the naming space is too
big for a flat list — both for humans (scrollbar fatigue) and for LLMs (context budget).

## 5. Command palette UX → agent UX

- **Fuzzy finding for humans ≠ embedding-retrieval for LLMs.** VS Code chose
  stable-sort over fuzzy-rank specifically to aid *memorization*. For LLMs the analogous
  principle is **determinism**: same query → same k tools. Deterministic retrieval is
  cacheable (Anthropic prompt cache TTL 5 min); stochastic ranking blows the cache.

- **Which-key / group-then-act (Emacs, Neovim which-key.nvim).** Press `<leader>g`,
  then a menu of `g`-prefixed commands appears, then select. Two-hop navigation scales
  further than one flat search. LLM translation: a `list_skills_in_category(category)`
  meta-tool as the first hop; a second call to invoke.

- **Superhuman / Linear command palette design.** Conventional wisdom (Superhuman blog,
  2024): don't just fuzzy-match — predict intent from recency and context. LLM analog:
  **conversation-aware tool retrieval** (top-k conditioned on prior tool results, not
  just the current user turn).

## 6. MCP vs proprietary protocols

- **Who uses MCP:** Anthropic (native), OpenAI (GPT Store + plugins migration 2024-2025),
  Microsoft (Copilot), Google, Cloudflare, Zapier (30k actions). Python + JS SDK combined
  ~20M weekly downloads (late 2025).
- **Who doesn't (purely):** Cursor (hand-crafted tool set, SWE-agent philosophy), Devin
  (closed/proprietary), SWE-agent (custom ACI), CrewAI/LangChain agents when not bridging
  to MCP servers (they use native function-calling and expose MCP as an adapter).
- **Why MCP won the protocol war:** neutrality (not tied to one provider), cap discovery
  + streaming + resources in one spec, strong tooling (Inspect AI, MCPProxy,
  MCPRepository).
- **Why MCP is insufficient alone:** `tools/list` is eager; no native retrieval tier;
  descriptions live in server metadata so you can't easily re-rank without re-fetching.
  The emerging norm (RAG-MCP, Toolshed, Anthropic Tool Search Tool) is **MCP at the
  transport layer + retrieval tier in front**. HuGR should keep MCP and add retrieval.

## 7. Recommendations for HuGR Arsenal

Grounded in precedent, priority-ordered:

### P0 — Critical (address "flat catalog not used naturally")

1. **Add Tool Search Tier 1 / Tier 2 split.** Precedent: Anthropic Tool Search Tool
   (85% token reduction at 100+ skills), LangGraph `bigtool`, RAG-MCP (3× accuracy).
   Refactor: `skills/SKILL-001-fastapi-production/mcp_tools/discovery.py` — add a
   `tier: Literal[1,2]` field to `MCP_TOOL` dicts. Tier 1 (always loaded): ~10-15
   orchestration tools (`fastapi_scaffold_resource`, `fastapi_search_skills`,
   `fastapi_audit`, `fastapi_verify`, the `evolve/` meta-tools). Tier 2: the 100
   `extend/` tools, loaded on-demand via the search tool.

2. **Service-namespace every tool name.** Precedent: Anthropic Oct 2025 guidance.
   Refactor: in `mcp_tools/discovery.py`, auto-derive name from path:
   `adapt/extend/crud_data/add_soft_delete.py` → `fastapi_crud_add_soft_delete`.
   Zero code changes inside tool bodies; one regex in discovery.

3. **Introduce a `scaffold` meta-tool.** Precedent: `rails generate scaffold`.
   New file: `skills/SKILL-001-fastapi-production/adapt/extend/fastapi_scaffold_resource.py`.
   Takes `name`, `fields`, `features: list[Literal[...]]` and fan-outs to existing
   primitive tools. This is the single most likely tool the LLM *will* reach for
   naturally — it maps to how humans describe requirements ("add a users resource
   with auth and soft-delete"), not how HuGR currently decomposes them.

### P1 — High value

4. **Bundle tools into `ToolSpec`-style facets.** Precedent: LlamaIndex ToolSpec.
   Refactor: expose 8 MCP tools named after `extend/` subdirs
   (`fastapi_crud`, `fastapi_auth`, `fastapi_infrastructure`, ...), each with an
   `action` enum arg. Drops visible tool count from 180 → ~20 without losing
   functionality. Compatible with P0.1 (Tier 1 becomes the facets; Tier 2 is the
   internal action enum).

5. **Phase-scoped tool exposure.** Precedent: CrewAI per-role tools.
   If Maestro has phases, mirror `extend/` vs `verify/` vs `operate/` vs `evolve/`
   onto phase-gated tool sets. Infrastructure already exists in
   `adapt/{extend,verify,operate,evolve}/`.

### P2 — Nice to have

6. **Tool-description linter as part of META-003 audit.** Already have 20 checks;
   add: (a) description ≤1024 chars, (b) name matches `{service}_{category}_{verb}_{noun}`,
   (c) description opens with action verb, (d) no overlap with sibling tools (cosine
   similarity > 0.85 → warn). Precedent: arxiv:2602.14878.

7. **Document the ACI principles explicitly in CLAUDE.md.** Cite SWE-agent.
   Currently the patterns block enumerates mechanics (MCP_TOOL dict, fingerprint)
   but not the *why* (agent affordances). A 5-line "ACI principles" section gives
   new tool authors a mental model.

### File/module paths for concrete refactors

- `skills/SKILL-001-fastapi-production/mcp_tools/discovery.py` — add tier + namespacing
- `skills/SKILL-001-fastapi-production/mcp_tools/server.py` — register Tool Search meta-tool
- `skills/SKILL-001-fastapi-production/adapt/extend/fastapi_scaffold_resource.py` — new
- `skills/SKILL-001-fastapi-production/adapt/extend/__init__.py` — facet bundles
- `docs/PRODUCT_VISION.md` — add "Retrieval-tier architecture" subsection
- `CLAUDE.md` — add ACI principles block

## Sources

- [langgraph-bigtool (GitHub)](https://github.com/langchain-ai/langgraph-bigtool) — semantic search over LangGraph memory store; demo at ~50 tools, designed to scale higher via retrieval.
- [LangChain dynamic tool calling changelog](https://changelog.langchain.com/announcements/dynamic-tool-calling-in-langgraph-agents) — graph-node-scoped tool availability (2025).
- [LlamaIndex ObjectIndex + ToolSpec docs](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/tools/) — ToolSpec bundles + ObjectRetriever is the canonical 2-tier pattern.
- [LlamaIndex retrieval-augmented agent example](https://developers.llamaindex.ai/python/examples/agent/openai_agent_retrieval/) — practical top-k-tools-to-LLM loop.
- [Semantic Kernel Plugins docs](https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/) — Plugin→Function 2-level hierarchy; planners deprecated in favor of native function calling.
- [SWE-agent ACI paper (arxiv:2405.15793)](https://arxiv.org/abs/2405.15793) — 4 principles: simple actions, efficient actions, lint-on-edit, compact feedback.
- [SWE-agent ACI docs](https://swe-agent.com/1.0/background/aci/) — concrete ACI implementation; note: superseded by mini-swe-agent (maintenance-only).
- [Anthropic "Writing effective tools for AI agents" (Oct 2025)](https://www.anthropic.com/engineering/writing-tools-for-agents) — the single most decision-relevant source; namespacing, 1024-char cap, Tool Search Tool, 85% token reduction at 100+ skills.
- [Anthropic tool use overview](https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview) — current Claude tool-use spec.
- [OpenAI function calling guide](https://platform.openai.com/docs/guides/function-calling) — 128 hard cap; practical degradation well before.
- [RAG-MCP (arxiv:2505.03275, May 2025)](https://arxiv.org/abs/2505.03275) — 3× selection accuracy, 50%+ token reduction via retrieval-augmented MCP tool selection.
- [Toolshed (scitepress, 2025)](https://www.scitepress.org/Papers/2025/133030/133030.pdf) — 46-56% recall@5 improvements; pre/intra/post-retrieval RAG-Tool Fusion.
- [WRITER "When too many tools become too much context"](https://writer.com/engineering/rag-mcp/) — industry confirmation of MCP tool-bloat.
- [RedHat "Tool RAG: The Next Breakthrough" (Nov 2025)](https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/) — convergence signal across vendors.
- [MCP Tools spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) — `tools/list` is eager + paginated; no built-in retrieval.
- [arxiv:2602.14878 "MCP Tool Descriptions Are Smelly"](https://arxiv.org/html/2602.14878v1) — description-quality degradation patterns.
- [CrewAI Tools docs](https://docs.crewai.com/en/concepts/tools) — Crew→Agent→Task→Tool 3-tier scoping.
- [Cursor Agent System Prompt (Mar 2025 gist)](https://gist.github.com/sshh12/25ad2e40529b269a88b80e7cf1c38084) — ~15-tool working set; `edit_file` + semantic-diff apply model.
- [How Cursor (AI IDE) Works — sshh.io](https://blog.sshh.io/p/how-cursor-ai-ide-works) — community reverse-engineering of Cursor's tool architecture.
- [Yeoman Composability docs](https://yeoman.io/authoring/composability.html) — sub-generator composition; `yo name:sub` namespacing.
- [Rails custom generator guide (Reintech)](https://reintech.io/blog/create-custom-generator-in-rails) — `lib/generators/` auto-discovery, Thor-based CLI.
- [Cookiecutter Hooks docs](https://cookiecutter.readthedocs.io/en/stable/advanced/hooks.html) — pre_prompt / pre_gen / post_gen lifecycle.
- [VS Code command palette UX](https://code.visualstudio.com/api/ux-guidelines/command-palette) — stable-sort over fuzzy-rank, explicit design choice.
- [Zapier MCP / 30k actions review (startupowl)](https://startupowl.com/reviews/zapier) — 8k apps, 30k actions exposed via MCP.
- [n8n vs Zapier 2026 (hatchworks)](https://hatchworks.com/blog/ai-agents/n8n-vs-zapier/) — agent-facing catalog navigation comparison.
