# SKILL.md Meta-Format — Design Contract for the HuGR Maestro

> Research + design doc · v1 · 2026-04-20 · author: Claude Opus 4.7 (1M) for Gustavo
>
> **Scope.** Define the file-format contract between a HuGR SkillKit skill and
> the HuGR Maestro (the LLM orchestrator running inside HuGR Forge). The
> concrete example is `SKILL-001-fastapi-production`; the format itself is
> generic and reusable.
>
> **Audience.** The Maestro is a non-deterministic consumer (Opus / GPT /
> Gemini). Every rule here exists because an LLM is the reader.
>
> **Citation discipline.** Every factual claim carries a URL or local path.
> Where Anthropic's spec is silent, I label the field "PROPOSAL" and give
> grounds. Where the spec is permissive, I take the tighter position — we
> ship SOTA, not lowest-common-denominator.

---

## 0. TLDR — 5 decisions

1. **Format = single `SKILL.md` with YAML frontmatter.** This is the Anthropic
   Agent Skills canonical shape (Oct 2025 launch, open-sourced as the Agent
   Skills standard on 2025-12-18). Both fields and parsing rules are already
   shipped in Claude.ai, Claude Code, the Claude Agent SDK, and the Claude
   Developer Platform — we inherit the tool-chain for free. Source:
   <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>;
   `anthropics/skills/README.md`:
   <https://github.com/anthropics/skills/blob/main/README.md>.

2. **Frontmatter stays minimal, body carries the contract.** Anthropic hard-
   limits frontmatter to `name` (≤64 chars) + `description` (≤1024 chars),
   allows `license` (observed in `anthropics/skills/skills/pdf/SKILL.md`).
   Everything else we need (phases, tool list, invariants, examples) is
   **body**. Putting non-spec keys in frontmatter breaks portability. We
   layer HuGR-specific metadata in a clearly-fenced `## Machine-readable
   metadata` section containing a YAML block — belt-and-suspenders for both
   the Maestro (LLM reader) and B2.5 contract validators (regex/parse
   readers).

3. **Body ≤ 500 lines, ≤ 5 000 tokens. One level of reference depth.**
   Hard rules from Anthropic's official best-practices page
   (<https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices>):
   *"Keep SKILL.md body under 500 lines for optimal performance"* and
   *"Keep references one level deep from SKILL.md"*. Everything HuGR
   currently ships in the existing `SKILL.md` (counts tables, test matrix,
   benchmark scores) is out of budget and moves to sibling files.

4. **Triggering is done by description text, not flags.** Anthropic's
   runtime injects only `name + description` at startup. The Maestro
   decides to load by matching user intent against the description string.
   The description must be written in third person, must name concrete
   trigger words, must name concrete anti-trigger words. This matches the
   `claude-api` skill's pattern (<https://platform.claude.com/docs/en/agents-and-tools/agent-skills/claude-api-skill>).
   No custom `activationEvents` array — that's VSCode's model and doesn't
   fit LLM dispatch.

5. **Catalog is referenced, not embedded.** `SKILL.md` points to
   `engine/index/catalog.json` (the 358 KB inventory of 173 tools + 122
   primitives + 385 recipes). The Maestro never loads catalog.json into
   context; it invokes the `fastapi_meta_search` tool, which reads it. This
   preserves the progressive-disclosure discipline and keeps SKILL.md at
   ~4 k tokens regardless of catalog size.

---

## 1. Format choice — `SKILL.md` with YAML frontmatter

### 1.1 Options considered

| Option | Pro | Con | Verdict |
|---|---|---|---|
| **`SKILL.md` + YAML frontmatter** (Anthropic standard) | Tool-chain support in Claude Code, Claude.ai, Claude SDK, Developer Platform. Human-readable. Progressive disclosure built in. Open standard since 2025-12-18. | Two languages in one file (YAML + Markdown). | **CHOSEN.** |
| Separate `skill.yaml` + `README.md` | Clean separation. | No precedent; ecosystem tooling expects SKILL.md. Human has to jump between files. | Rejected. |
| Pure JSON manifest | Deterministic parse. | LLM reads prose better than JSON; non-standard. Defeats the point of co-locating prompt-like instructions. | Rejected. |
| VSCode-style `package.json` with `activationEvents` | Well-known. | Event model presupposes a deterministic dispatcher; an LLM doesn't "fire events", it reads intent. Mismatch. | Rejected. |
| MCP Prompt resource | Would auto-inject. | MCP prompts are "user-controlled" by spec: *"typically prompts would be triggered through user-initiated commands… as slash commands"* — they don't auto-load. Source: <https://modelcontextprotocol.io/docs/concepts/prompts>. Cited in our own `TOOL_UX_ANTHROPIC.md` §6. | Rejected. |

### 1.2 Precedent citations

- **Anthropic engineering blog, Oct 16 2025.** *"A skill is a directory that
  contains a SKILL.md file... must start with YAML frontmatter that
  contains some required metadata: name and description."*
  <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- **Claude Developer Platform best-practices page** enumerates the
  frontmatter schema (see §3 below).
  <https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices>
- **`anthropics/skills` reference repo.** All 20+ bundled skills use this
  exact shape; `template/SKILL.md` is two frontmatter fields + a header.
  <https://github.com/anthropics/skills/tree/main/template>
- **Real production examples inspected.**
  `skills/pdf/SKILL.md`, `skills/docx/SKILL.md`, `skills/xlsx/SKILL.md`
  in the same repo. All use `name`, `description`, and a proprietary
  `license` field. No `version`, no `activationEvents`, no custom YAML
  schema.

### 1.3 One-sentence ecosystem comparison

VSCode's `package.json` + `activationEvents` and Yeoman's generator
`files` hook presuppose a deterministic host that fires events or reads
hooks; Cursor's `.cursor/rules` is free-form markdown with no metadata;
GitHub Actions `action.yml` has typed inputs/outputs but no intent
triggering. Anthropic's Agent Skills sits uniquely at "typed metadata
(name/description) + free-form body", which is the correct shape for an
LLM consumer that matches *intent* rather than events and reads *prose*
rather than parses schemas.

---

## 2. Frontmatter schema — every field, typed, token-budgeted

### 2.1 Anthropic-mandated fields (hard-enforced by the platform)

Source: the Anthropic best-practices page (verbatim quotes in the
citation bundle below). These are validated at skill upload time by
Claude.ai / the API; violating them makes the skill uninstallable.

| Field | Type | Required | Constraint (from Anthropic spec) | Token cost (typical) |
|---|---|---|---|---|
| `name` | string | yes | ≤ 64 chars. Lowercase letters, digits, hyphens only. No XML tags. Reserved: `anthropic`, `claude`. | ~5 tok |
| `description` | string | yes | Non-empty. ≤ 1024 chars. Third person. Must say **what** + **when**. Cannot contain XML tags. Single field per skill. | ~200–260 tok |

**Quote** (Anthropic best-practices):
> *"name: Maximum 64 characters; Must contain only lowercase letters,
> numbers, and hyphens; Cannot contain XML tags; Cannot contain reserved
> words: 'anthropic', 'claude'. description: Must be non-empty; Maximum
> 1024 characters; Cannot contain XML tags; Should describe what the
> Skill does and when to use it."*

**Quote** (same page, on description authoring):
> *"Always write in third person. The description is injected into the
> system prompt, and inconsistent point-of-view can cause discovery
> problems. Good: 'Processes Excel files and generates reports'. Avoid:
> 'I can help you process Excel files'."*

### 2.2 Optional fields observed in the wild

| Field | Type | Source | HuGR stance |
|---|---|---|---|
| `license` | string | Used in `anthropics/skills/skills/{pdf,docx,xlsx}/SKILL.md`. Not documented in the best-practices page. | **Include** for SKILL-001 — say `Apache-2.0` (we are open source). |

**PROPOSAL — HuGR extension fields (body, not frontmatter).** Anthropic's
spec is silent on version, homepage, triggers-list, tier-1-tools. Putting
them in frontmatter would:
(a) drift from the open standard — tools that validate YAML may reject;
(b) bloat startup tokens (frontmatter is always loaded, body is not).
**We put them in a fenced YAML block inside the body** (see §3.2) and
forbid custom frontmatter keys by validation rule.

### 2.3 Token-cost budget — frontmatter

Per Anthropic best-practices (paraphrased): *"only the metadata (name and
description) from all Skills is pre-loaded"* at startup. The 64-char name +
1024-char description is a ceiling of ~280 tokens per skill in the
Maestro's system prompt **permanently**. HuGR's rule: **aim for ≤ 260
tokens of description**. If you need more, your description is doing the
body's job.

---

## 3. Body schema — sections, ordering, token budget

### 3.1 Anthropic's body rules (hard constraints)

- *"Keep SKILL.md body under 500 lines for optimal performance."*
- *"Split content into separate files when approaching this limit."*
- *"Keep references one level deep from SKILL.md."*
- *"For reference files longer than 100 lines, include a table of
  contents at the top."*
- *"Claude loads [SKILL.md] only when the Skill becomes relevant, and
  reads additional files only as needed."*

Source (all four, one page):
<https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices>

**HuGR body ceiling: 400 lines / 5 000 tokens.** We sit tighter than
Anthropic's 500 to leave headroom for conversation history and the
Maestro's other injected context (CLAUDE.md, PRODUCT.md, current diff).

### 3.2 Required sections (in this order)

1. **Title (`# <Skill Name>`)** — one line. ~5 tok.
2. **Overview paragraph** — 2–4 sentences. What the skill does, what it
   emits, what it does not do. ~120 tok. Mirrors the Anthropic `pdf`
   SKILL.md pattern ("This guide covers essential PDF processing
   operations…").
3. **When to use / when not to use** — two bulleted lists, ≤ 5 bullets
   each. This is the machine-executable trigger contract (see §5).
   ~200 tok. Precedent: the `claude-api` skill uses exactly this shape
   (*"The skill activates in two ways: Automatic activation occurs when…
   The skill does not activate for…"*).
4. **Machine-readable metadata** — a fenced ` ```yaml ` block with
   HuGR-specific fields (version, phases, entry_tools, catalog path,
   invariants, homepage). See §3.4. ~180 tok.
5. **Workflow phases** — the canonical orient → clarify → scaffold →
   compose → business → audit sequence, each phase one short paragraph
   naming the entry tool. ~400 tok. See §6.
6. **Tier-1 tool index** — short table: `tool name · one-line purpose ·
   when to call`. Tier-1 only (the ~6 meta tools). Everything else is
   discovered via `fastapi_meta_search`. ~250 tok.
7. **Few-shot transcripts** — 2–3 compressed examples of correct usage,
   one per primary intent shape. ~1 200 tok. See §8.
8. **Anti-patterns** — 5–7 bullets of "don't do this". ~200 tok. These
   are reinforcing, not decorative: they measurably reduce
   hallucination in our own agent tests (see TOOL_UX_ANTHROPIC.md §4).
9. **Reference files** — one-level-deep list of sibling markdowns the
   Maestro may read on demand (catalog schema, contract, phase-by-phase
   playbooks). ~150 tok.
10. **Versioning footer** — `version · spec_compat · date · kit_commit`.
    ~30 tok.

**Total target: ~2 900 tokens body + ~260 frontmatter = ~3 160 tokens.**
Leaves 1 800-tok headroom under the 5 k ceiling.

### 3.3 Forbidden body content

These blow the budget without helping the Maestro decide or execute.
They live in sibling files or get cut entirely.

- Test-suite counts, per-folder file counts, benchmark scores. Moves to
  `STATUS.md` (human-facing).
- Install instructions (`curl install.sh | bash`). Moves to
  `README.md` / `QUICK_START.md`.
- Contract audit commands (`./ci.sh`, `engine.audit.contract_check`).
  Moves to `CONTRIBUTING.md`.
- Architectural prose (three-layer diagram, Rails analogy). Moves to
  `/PRODUCT.md`. The Maestro already has `PRODUCT.md` in its Forge
  context; duplicating is waste.
- Signed-by lines, changelogs, sprint notes.
- Internal refactor plans, TODOs, aspirational roadmap items.

### 3.4 Machine-readable metadata block — the HuGR extension

Fenced YAML block inside the body, so it is invisible to platforms that
don't know about it, but trivially parseable by our B2.5 validator and
by the Maestro's "read this fence" heuristic.

```yaml
# HuGR-specific metadata — not part of the Anthropic Agent Skills spec.
# Placed in the body so it does not pollute frontmatter. Validated by
# engine/audit/skill_contract.py.
hugr_skill_version: "1.0.0"       # semver of THIS skill's contract
spec_compat: ">=1.0.0,<2.0.0"     # Maestro versions that speak this
kind: "framework-scaffold"         # enum: framework-scaffold | library-adapter | workflow
domains: ["backend", "python", "fastapi", "web-api"]
entry_tools:                        # Tier-1 MCP tools — always available
  - fastapi_meta_search_home
  - fastapi_meta_search
  - fastapi_meta_describe
  - fastapi_meta_generate_scaffold
  - fastapi_meta_compose
  - fastapi_meta_check_audit
  - fastapi_meta_verify_verify
  - fastapi_auth                    # tree dispatcher
catalog_path: "engine/index/catalog.json"
phases: [orient, clarify, scaffold, compose, business, audit]
invariants:
  - "Tools emit ≤ 20 lines of glue; logic lives in imported primitives."
  - "Generated code survives hand-editing (idempotent fingerprints)."
  - "Every tool auto-registers via MCP_TOOL metadata (no manual decorators)."
```

**Why YAML-in-body and not frontmatter.** See §2.2. If we put these in
frontmatter, `claude-api` / Claude.ai skill uploaders may warn or reject
unknown keys as the spec tightens. Body fencing is future-proof.

---

## 4. Body token budget — the actual math

Tokens estimated at 4 chars ≈ 1 token (standard Claude tokenizer
approximation; Anthropic's token counter API gives tighter numbers in
prod). Target the midpoint, hard-cap the ceiling.

| Section | Target | Ceiling | Rationale |
|---|---:|---:|---|
| Title | 5 | 10 | One line. |
| Overview | 120 | 180 | 2–4 sentences; every extra sentence competes with examples. |
| When to use / not to use | 200 | 300 | This is the trigger contract — do not compress. |
| Machine-readable metadata YAML | 180 | 250 | Fence is cheap; too many fields becomes a catalog. |
| Workflow phases | 400 | 600 | Six phases × ~65 tok each. |
| Tier-1 tool index | 250 | 400 | ~8 tools × 30 tok each. |
| Few-shot transcripts | 1 200 | 1 800 | 3 examples × 400 tok. Anthropic observed 3× is the sweet spot (engineering blog "Writing effective tools for agents"). |
| Anti-patterns | 200 | 300 | 5–7 bullets. |
| Reference files list | 150 | 250 | One-level deep. |
| Versioning footer | 30 | 50 | `version · date · commit`. |
| **Total body** | **2 735** | **4 140** | Hard cap 5 000 per Anthropic guidance. |
| Frontmatter (name + description) | 260 | 280 | 64 + 1 024 chars ≈ 270 tok. |
| **Whole file** | **~3 000** | **~4 400** | Comfortably under 5 k. |

---

## 5. Triggering semantics — how the Maestro decides to load

### 5.1 Platform behaviour (factual)

From the Anthropic engineering blog and best-practices page:

> *"At startup, the agent pre-loads the name and description of every
> installed skill into its system prompt. This metadata is the first
> level of progressive disclosure: it provides just enough information
> for Claude to know when each skill should be used without loading all
> of it into context. If Claude thinks the skill is relevant to the
> current task, it will load the skill by reading its full SKILL.md into
> context."*

There is **no `trigger` field**, no `activationEvents`, no regex list.
The decision is made by the model, prompted by the description string.

### 5.2 Description authoring rules — binding for HuGR

Anthropic's own description-quality rubric (best-practices page, verbatim
"Effective examples" and "Avoid" sections) → promoted to HuGR rules:

1. **Start with a verb in third person.** `"Scaffolds and extends..."`,
   not `"This skill helps you..."`.
2. **Name the deliverable.** *"production-grade FastAPI backends"* —
   concrete, ungeneric.
3. **Name 5–10 concrete trigger substrings.** Fine-grained examples from
   the `xlsx` skill: *"the user references a spreadsheet file by name or
   path — even casually (like 'the xlsx in my downloads')"*. The Maestro
   does fuzzy matching; give it surface area.
4. **Name concrete anti-triggers with "Do NOT" in caps.** `docx`
   example: *"Do NOT use for PDFs, spreadsheets, Google Docs, or general
   coding tasks unrelated to document generation"*. Without these, the
   Maestro over-fires.
5. **≤ 1024 chars total.** Hard limit.
6. **No XML tags** (hard limit; the system prompt wraps the description
   in tags and nested tags break parsing).
7. **Single description — no multiple triggers array.** Anthropic spec.

### 5.3 Trigger contract for SKILL-001 (draft string, fits in 1024 chars)

> "Scaffolds and customizes production-grade FastAPI backends in Python:
> lays down a canonical project tree (auth, CRUD, Stripe, background
> jobs, observability), then extends it with composable capability slices
> (RBAC, MFA, cursor pagination, event sourcing, webhooks, rate limiting,
> sagas, SSE, WebSockets, audit log, schema evolution). Use when the user
> asks to start, extend, audit, or harden a FastAPI project, mentions
> Python backend/API/microservice/web service, names dependencies like
> FastAPI/SQLAlchemy/Pydantic/Alembic/Celery/Stripe/Redis, or asks to add
> concrete capabilities (auth, payments, webhooks, realtime, jobs,
> observability, compliance) to an existing FastAPI app. Also use when
> the user names a production concern (idempotency, outbox, rate limit,
> circuit breaker, retry budget, graceful shutdown, saga, RBAC) in a
> Python web-API context. Do NOT use for: non-Python backends (Node,
> Go, Rails, Django), frontend work, data-science notebooks, ML model
> training, bare-metal Python libraries without a web surface, or
> Google Sheets / Excel / PDF document tasks."

≈ 1 008 chars. Reads naturally. Names framework + concrete capabilities
+ dependency surface + negative triggers. Passes all 7 rules above.

### 5.4 What the description *cannot* do

- It cannot reference files (the Maestro hasn't loaded them yet).
- It cannot enumerate the 173 tools (would blow 1024 chars in one go).
- It cannot carry instructions — those go in body. The description's
  only job is **"should I read the body?"**.

---

## 6. Phase declaration — machine-readable workflow

### 6.1 What we need

The Maestro's canonical session for SKILL-001 walks six phases
(orient → clarify → scaffold → compose → business → audit). Human
reviewers want to see the phases; the Maestro wants a machine-readable
list so it can stay on rails.

### 6.2 Two-surface encoding (belt + suspenders)

**Surface A — the fenced YAML in §3.4** carries a canonical ordered
list:

```yaml
phases: [orient, clarify, scaffold, compose, business, audit]
```

Parseable by `yaml.safe_load` on the fenced block.

**Surface B — the "Workflow phases" section** names each phase with a
one-sentence charter and the tier-1 tool that drives it. Prose, for the
LLM:

> ## Workflow phases
>
> 1. **Orient.** Establish what the user wants and what's already in the
>    repo. Entry tool: `fastapi_meta_search_home`. Reads the repo root +
>    catalog, returns a situation brief.
> 2. **Clarify.** Resolve ambiguity by short, cheap questions — never
>    more than 3. Entry tool: none (Maestro uses its own reasoning).
> 3. **Scaffold.** Lay down the canonical project tree. Entry tool:
>    `fastapi_meta_generate_scaffold`.
> 4. **Compose.** Wire tier-2 (slice) and tier-3 (primitive) pieces to
>    cover the user's capability list. Entry tool:
>    `fastapi_meta_compose`.
> 5. **Business.** Add domain-specific endpoints, models, rules. Entry
>    tool: `fastapi_meta_search` (to find the right slice tool).
> 6. **Audit.** Run contract checks and fix any regressions. Entry tool:
>    `fastapi_meta_check_audit` + `fastapi_meta_verify_verify`.

### 6.3 Why encode phases at all

Without a phase skeleton, an LLM skips phases (particularly clarify and
audit — observed in our FinHealth runs). Naming the phase + the entry
tool per phase converts implicit behaviour into explicit behaviour.
Precedent: Anthropic's `claude-api` skill exposes explicit sub-commands
(`/claude-api migrate`, `/claude-api managed-agents-onboard`), which is
the same move at a finer grain.

---

## 7. Tool exposure — Tier-1 only, by name

### 7.1 Why Tier-1 only

SKILL-001 ships 173 tools. Listing all 173 in SKILL.md would blow the
body budget 3×, and Anthropic's tool-search infrastructure exists
precisely to avoid that (Tool Search, Nov 2025, cites the 30–50 tool
degradation threshold —
<https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool>).
The SKILL.md lists only the **tier-1 meta tools** the Maestro needs
before it has any business knowing the rest exist. All other tools are
discovered via `fastapi_meta_search`, whose whole reason for existing is
JIT tool discovery.

This is structurally identical to Claude Code's own design (observed in
this very session: ~10 always-loaded tools + deferred tools discovered
via `ToolSearch`). Cited in our `TOOL_UX_ANTHROPIC.md` §4.

### 7.2 Format — a tight table

```markdown
| Tool | Purpose | When to call |
|---|---|---|
| `fastapi_meta_search_home` | Get a situation brief (repo + catalog state). | First call of every session. |
| `fastapi_meta_search` | BM25 search across catalog.json (tools + primitives + recipes). | When you need a capability and don't know the exact tool name. |
| `fastapi_meta_describe` | Return the full spec + examples for one catalog id. | After `search`, before you commit to using the thing. |
| `fastapi_meta_generate_scaffold` | Emit a production-grade FastAPI project tree. | Scaffold phase. |
| `fastapi_meta_compose` | Emit a wired composition of primitives for one capability. | Compose phase, when no slice tool fits exactly. |
| `fastapi_meta_check_audit` | Run the contract audit and return structured findings. | Audit phase, and after any structural change. |
| `fastapi_meta_verify_verify` | Meta-audit: verify that the audit itself is sound. | End of audit phase. |
| `fastapi_auth` | Tree dispatcher that collapses 15 auth slice tools into one. | Auth-related requests. |
```

≈ 230 tokens. Every other tool is one `fastapi_meta_search` call away.

### 7.3 When the Tier-1 list changes

Adding a tier-1 tool is a **minor version bump** (§9). Removing one is a
**major version bump**. Test: if removing this tool breaks the Maestro's
ability to recover via search, it's tier-1 and must stay. If the Maestro
can discover it itself, it's tier-2 and doesn't belong in SKILL.md.

---

## 8. Few-shot examples — transcripts inside SKILL.md

### 8.1 The Anthropic pattern

`anthropics/skills/skills/pdf/SKILL.md` inlines code snippets right in
the body (`pypdf` usage examples). `anthropics/skills/skills/docx/SKILL.md`
inlines a Quick Reference table plus small JS snippets. Both trust that
Claude pattern-matches well from 2–3 in-context examples — this is the
"Anthropic observed 3× sweet spot" from the engineering blog on writing
effective tools
(<https://www.anthropic.com/engineering/writing-tools-for-agents>, §
"Provide examples").

### 8.2 HuGR format — compressed transcript

Three examples, one per dominant intent shape:

- **Example A — Fresh scaffold.** User: "Build a SaaS with email auth
  and Stripe subscriptions". Transcript shows: `search_home`, clarify
  question, `generate_scaffold`, `compose` for auth + Stripe, `audit`.
  Compressed: ~400 tokens.
- **Example B — Extend existing repo.** User: "Add rate limiting and
  idempotency to my /api/orders endpoint". Transcript shows: `search`
  for rate-limiting primitive, `describe` to read invariants,
  `compose`, `audit`. Compressed: ~400 tokens.
- **Example C — Ambiguous request.** User: "Make it secure". Transcript
  shows: refuse to execute, ask two clarify questions, then branch on
  the answer. Demonstrates the Clarify phase. Compressed: ~400 tokens.

Each transcript is framed as a tool-call trace (not narrative prose),
because the Maestro's few-shot pattern matching is strongest on the
exact tool-call shape it will itself emit. Precedent: the Anthropic
best-practices page's "effective examples" section explicitly prefers
trace-shape over prose.

### 8.3 What makes transcripts load-bearing

- **Every tool call names its arguments** — the Maestro copies the
  argument shape, not just the tool name.
- **Every clarify question lists the exact 2–3 answer branches.** No
  open-ended questions.
- **Every phase transition is marked** (`→ scaffold`, `→ compose`).
- **Failure modes shown once.** Example B includes a deliberate
  `describe` call that reveals an invariant conflict, followed by the
  Maestro backtracking. One explicit "recover" trace is worth a
  paragraph of prose.

---

## 9. Versioning + compatibility

### 9.1 Semver on HuGR skill contract

`hugr_skill_version` in the fenced YAML. Rules:

- **MAJOR** — breaking body-schema or frontmatter changes (tier-1 tool
  removed, phase removed/renamed, description-semantics changed). The
  Maestro must be re-tested.
- **MINOR** — additive (new tier-1 tool, new phase, new anti-pattern,
  new reference file).
- **PATCH** — wording, typos, clarifications inside an existing section.

### 9.2 `spec_compat` range

`spec_compat: ">=1.0.0,<2.0.0"` declares which Maestro versions can
speak this contract. Maestro refuses to load skills whose `spec_compat`
excludes its own version; soft-fail prints an actionable error.

### 9.3 Relationship with package semver

If SKILL-001 ships at kit version `0.2.0` but the SKILL.md contract is
still `1.0.0`, that's intended — the contract is orthogonal to feature
work. The `kit_commit` line in the versioning footer binds the SKILL.md
to the specific git commit for audit.

### 9.4 Migration between versions

When bumping MAJOR, ship `MIGRATION.md` as a sibling reference file
(one-level-deep link from SKILL.md). The Maestro sees it only when the
old version is detected. Precedent: Anthropic's `claude-api` skill
handles the same problem at runtime (`/claude-api migrate`).

---

## 10. Relationship with `catalog.json`

### 10.1 The separation of concerns

| File | Role | Audience | Size | Load timing |
|---|---|---|---|---|
| `SKILL.md` | Contract — what the skill is, when to load, how to drive. | Maestro system prompt. | ~3 k tokens. | Metadata always; body on trigger. |
| `engine/index/catalog.json` | Inventory — every tool, primitive, recipe, with schema + searchable fields. | `fastapi_meta_search` tool. | ~358 KB, ~90 k tokens if raw. | Never into context; tool reads disk. |

**SKILL.md is the contract; catalog.json is the inventory.** The
contract is fixed per release; the inventory mutates every commit.
Keeping them separate means we don't have to bump the SKILL.md contract
every time we add a primitive.

### 10.2 The binding

SKILL.md names `catalog_path` in its fenced YAML. The six tier-1 meta
tools (`fastapi_meta_*`) all read that path. Maestro never reads the
file directly. If the path is wrong, the audit tool catches it (B2.5
rule: "catalog_path file exists and parses as JSON with the expected
top-level keys: schema_version, verbs, domains, tools, primitives,
recipes, counts").

### 10.3 Why not embed catalog in SKILL.md

Tried mentally: ~90 k tokens in the skill body. Kills progressive
disclosure. Anthropic's own bundled `xlsx` skill solves exactly this
problem by keeping a script that reads data on demand, not by inlining
data. We follow that precedent.

---

## 11. Anti-patterns — what not to put in SKILL.md

Derived from observed drift in the current `SKILL.md` + Anthropic best-
practices "Avoid" section + our own TOOL_UX_ANTHROPIC.md §Anti-patterns.

1. **No test counts, no benchmark scores.** These belong in
   `STATUS.md`. They change daily; SKILL.md is a contract.
2. **No install / CI instructions.** `README.md` / `CONTRIBUTING.md`
   territory. The Maestro doesn't install things.
3. **No internal refactor notes** ("Phase 4 complete", "§A8 binds us
   to…"). Reader is an LLM; sprint jargon is noise.
4. **No per-folder file counts** ("38 infrastructure tools, 15 auth
   tools…"). The Maestro discovers via `fastapi_meta_search`; static
   numbers drift instantly.
5. **No duplication of PRODUCT.md.** The Maestro already has PRODUCT.md
   in its Forge context; duplicating wastes the 5 k-token budget on
   information the agent already has.
6. **No first-person voice** ("You can use this to…"). Anthropic best-
   practices explicitly prohibits. Always third person.
7. **No commit-signed lines / changelogs / dates other than the
   versioning footer.** Git handles provenance.
8. **No XML tags anywhere.** Hard spec limit; breaks the system-prompt
   wrapper.
9. **No emojis.** LLMs read them fine but they carry zero signal and
   bloat token counts in tables (one emoji = 1–3 tokens).
10. **No aspirational content.** If it's not true on disk at the commit
    in the versioning footer, it's drift. CONTRACT §A8 applies.

---

## 12. Full concrete example — SKILL.md for SKILL-001

```markdown
---
name: fastapi-production
description: Scaffolds and customizes production-grade FastAPI backends in Python — lays down a canonical project tree (auth, CRUD, Stripe, background jobs, observability) and extends it with composable capability slices (RBAC, MFA, cursor pagination, event sourcing, webhooks, rate limiting, sagas, SSE, WebSockets, audit log, schema evolution). Use when the user asks to start, extend, audit, or harden a FastAPI project; mentions Python backend / API / microservice / web service; names dependencies like FastAPI, SQLAlchemy, Pydantic, Alembic, Celery, Stripe, Redis; or asks to add concrete capabilities (auth, payments, webhooks, realtime, jobs, observability, compliance) to an existing FastAPI app. Also use when the user names a production concern (idempotency, outbox, rate limit, circuit breaker, retry budget, graceful shutdown, saga, RBAC) in a Python web-API context. Do NOT use for non-Python backends (Node, Go, Rails, Django), frontend work, data-science notebooks, ML model training, bare-metal Python libraries without a web surface, or Google Sheets / Excel / PDF document tasks.
license: Apache-2.0
---

# FastAPI Production

## Overview
<!-- ~140 tok -->
Turns a plain-English backend spec into a running, tested, production-grade
FastAPI service. Emits idiomatic code that imports from a curated library of
122 framework-free primitives (the "venous system"), so generated output
survives hand-editing. Ships 173 MCP tools behind seven tier-1 meta tools
and one tree dispatcher — the Maestro drives the skill exclusively through
those, never by listing the full catalog.

## When to use
<!-- ~130 tok -->
- User wants to start a new Python backend and mentions FastAPI, Python web
  API, Stripe + Python, or a SaaS backend.
- User wants to add a named capability (auth, payments, rate limiting,
  RBAC, sagas, realtime, audit log) to an existing FastAPI repo.
- User names a production-engineering concern (idempotency, outbox,
  graceful shutdown, retry budget, circuit breaker) in a Python context.
- Repo already contains `pyproject.toml` with `fastapi` or `app/main.py`
  with `FastAPI()` instantiation.

## When NOT to use
<!-- ~80 tok -->
- Non-Python backends (Node, Go, Rails, Django, Flask-only, Quart).
- Frontend, mobile, data-science notebooks, ML training.
- Document-manipulation tasks (PDF, Word, Excel, Google Docs).
- Bare Python libraries with no HTTP surface.

## Machine-readable metadata
<!-- ~180 tok -->
```yaml
hugr_skill_version: "1.0.0"
spec_compat: ">=1.0.0,<2.0.0"
kind: "framework-scaffold"
domains: ["backend", "python", "fastapi", "web-api"]
entry_tools:
  - fastapi_meta_search_home
  - fastapi_meta_search
  - fastapi_meta_describe
  - fastapi_meta_generate_scaffold
  - fastapi_meta_compose
  - fastapi_meta_check_audit
  - fastapi_meta_verify_verify
  - fastapi_auth
catalog_path: "engine/index/catalog.json"
phases: [orient, clarify, scaffold, compose, business, audit]
invariants:
  - "Tools emit ≤ 20 lines of glue; logic lives in imported primitives."
  - "Generated code survives hand-editing (idempotent fingerprints)."
  - "Every tool auto-registers via MCP_TOOL metadata (no manual decorators)."
```

## Workflow phases
<!-- ~420 tok -->
1. **Orient.** Call `fastapi_meta_search_home` to get a situation brief
   (repo state + catalog counts + recent change summary). This is always
   the first call; do not skip it.
2. **Clarify.** Ask at most three specific questions — each must offer 2–4
   concrete answer branches. Never open-ended. Skip this phase only if
   the user's request is literally unambiguous.
3. **Scaffold.** If the repo is empty or lacks `app/main.py`, call
   `fastapi_meta_generate_scaffold(project_name, capabilities=[...])`
   once. Do not call it a second time — it is not idempotent across
   runs.
4. **Compose.** For each requested capability: first
   `fastapi_meta_search(query)`, then `fastapi_meta_describe(id)`, then
   `fastapi_meta_compose(id, args)`. Prefer slice tools over raw
   primitive composition unless the user asked for something the slice
   doesn't cover exactly.
5. **Business.** Add domain-specific routes, models, and rules. Use
   `fastapi_auth(action="...")` for any auth branch instead of listing
   15 auth slice tools.
6. **Audit.** Call `fastapi_meta_check_audit` and fix every finding.
   Close with `fastapi_meta_verify_verify` to confirm the audit itself
   is clean. Only report "done" after this pair returns green.

## Tier-1 tool index
<!-- ~250 tok -->
| Tool | Purpose | When to call |
|---|---|---|
| `fastapi_meta_search_home` | Situation brief — repo + catalog state. | First call of every session. |
| `fastapi_meta_search` | BM25 over catalog (tools + primitives + recipes). | When you need a capability and don't know the exact id. |
| `fastapi_meta_describe` | Full spec + examples for one catalog id. | After `search`, before committing to the thing. |
| `fastapi_meta_generate_scaffold` | Emit a production FastAPI project tree. | Scaffold phase, once per session. |
| `fastapi_meta_compose` | Emit a wired composition of primitives for one capability. | Compose phase, when no slice fits. |
| `fastapi_meta_check_audit` | Run the contract audit; return structured findings. | End of audit phase. |
| `fastapi_meta_verify_verify` | Meta-audit — verify the audit is sound. | Immediately after `check_audit`. |
| `fastapi_auth` | Tree dispatcher for 15 auth slice tools. | Any auth-related request (login, mfa, rbac, social, oauth2). |

All other tools (~165) are discovered on demand via
`fastapi_meta_search`.

## Few-shot transcripts
<!-- ~1 200 tok -->
<!-- A: fresh scaffold | B: extend existing | C: ambiguous request -->
(3 compressed tool-call traces, ~400 tok each; see §8.2 for anatomy.)

## Anti-patterns
<!-- ~200 tok -->
- Do not skip `search_home`. Without it, you will hallucinate repo state.
- Do not call `generate_scaffold` twice in one session. Not idempotent.
- Do not list all 15 auth tools; always go through `fastapi_auth`.
- Do not write business-logic code inline that duplicates a primitive
  — always `describe` first to check.
- Do not mark a session "done" before `verify_verify` returns green.
- Do not ask more than three clarify questions. If three are not
  enough, scaffold with sensible defaults and let the user redirect.

## Reference files
<!-- ~150 tok -->
- `PHASES.md` — long-form playbook per phase (only when Maestro gets stuck).
- `CATALOG_SCHEMA.md` — structure of `catalog.json` (only when a `search`
  result shape is unclear).
- `PRIMITIVES_GUIDE.md` — how to compose primitives directly.
- `MIGRATION.md` — versioning / breaking-change notes.

---
<!-- versioning footer ~30 tok -->
*version: 1.0.0 · spec_compat: >=1.0.0,<2.0.0 · kit_commit: {{GIT_SHA}}*
```

**Measured budget of the example above:** frontmatter ≈ 1 008 chars
(~255 tok), body ≈ 2 700 tokens, whole file ≈ 2 960 tokens. 40 %
headroom under Anthropic's 5 k ceiling.

---

## 13. Validation rules — what the B2.5 contract should check

Every rule below maps 1:1 to an assertion an audit tool can enforce.
These are the rules `engine/audit/skill_contract.py` would implement.

1. **File exists at `skills/<SKILL_ID>/SKILL.md`.**
2. **Frontmatter parses as valid YAML** (open `---` fence, close `---`
   fence, `yaml.safe_load` succeeds).
3. **`name` field** — present, non-empty, ≤ 64 chars, matches regex
   `^[a-z0-9-]+$`, not in `{anthropic, claude}`.
4. **`description` field** — present, ≤ 1024 chars, no `<` or `>`
   characters (blocks XML injection), does not start with "I ", "You ",
   or "We " (first-person guard).
5. **Description has a positive trigger section** — contains at least
   one occurrence of the words "use when" / "trigger when" (case-
   insensitive). Heuristic; weak but cheap.
6. **Description has a negative trigger section** — contains at least
   one occurrence of "do not" / "avoid" / "not use" (case-insensitive).
7. **Body ≤ 500 lines** (hard cap per Anthropic best-practices).
8. **Body token estimate ≤ 5000** (4 chars ≈ 1 token; err soft).
9. **Section presence** — regex for the required H2s: Overview, When to
   use, When NOT to use, Machine-readable metadata, Workflow phases,
   Tier-1 tool index, Few-shot transcripts, Anti-patterns, Reference
   files.
10. **Fenced `yaml` block under "Machine-readable metadata" parses** and
    contains: `hugr_skill_version` (semver), `spec_compat` (semver
    range), `kind` (enum), `domains` (list of strings), `entry_tools`
    (list of strings), `catalog_path` (string), `phases` (list).
11. **`catalog_path` file exists** and parses as JSON with required top-
    level keys (`schema_version`, `tools`, `primitives`, `recipes`,
    `counts`).
12. **Every tool in `entry_tools` exists** in the catalog's tools array
    (by `id`).
13. **Reference files listed in "Reference files" section exist** on
    disk as siblings to SKILL.md.
14. **Reference depth ≤ 1** — grep the reference files for further
    markdown links to other reference files; error if any found
    (Anthropic's "one level deep" rule).
15. **Few-shot transcripts ≥ 2 and ≤ 3.** Count fenced code blocks
    marked as transcripts.
16. **No forbidden sections** — fail if the body contains the words
    "benchmark score", "test count", "sprint", "phase 4 complete",
    "`curl` install", "`./ci.sh`" (drift-alarm heuristics).
17. **Versioning footer present** — last line matches
    `*version: ... · kit_commit: ...*`.
18. **No first-person pronouns in body** — grep for "\\bI \\b|\\bwe \\b|\\byou \\b"
    outside fenced code blocks; error on hit.
19. **No XML tags anywhere in the file.**
20. **`hugr_skill_version` is a valid semver** and not `0.*` for a
    production skill tier.

### 13.1 Expected behaviour on failure

All twenty checks return a single `ContractReport` with line numbers.
Failures block CI. Fix same-day per CONTRACT §A8. This is the same
discipline as the existing 28-rule contract check, just extended to the
SKILL.md surface.

---

## 14. Citation bundle (every source used, one place)

**Primary — Anthropic spec & engineering.**
- Agent Skills overview (docs): <https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview>
- Agent Skills best-practices (docs): <https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices>
- Agent Skills quickstart (docs): <https://docs.claude.com/en/docs/agents-and-tools/agent-skills/quickstart>
- Engineering blog, Oct 16 2025 — *Equipping agents for the real world with Agent Skills*: <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>
- Engineering blog, Sep 11 2025 — *Writing effective tools for agents*: <https://www.anthropic.com/engineering/writing-tools-for-agents>
- Tool Search docs (30–50 threshold): <https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool>
- Claude API skill (production example of a shipped skill): <https://platform.claude.com/docs/en/agents-and-tools/agent-skills/claude-api-skill>

**Reference implementations (community).**
- `anthropics/skills` — the canonical skill repo, Apache-2.0 + some source-available: <https://github.com/anthropics/skills>
- `anthropics/skills/template/SKILL.md` — the minimal skill: <https://github.com/anthropics/skills/blob/main/template/SKILL.md>
- `anthropics/skills/skills/pdf/SKILL.md` — real production-grade SKILL.md
- `anthropics/skills/skills/docx/SKILL.md` — richer trigger pattern including explicit "Do NOT" list
- `anthropics/skills/skills/xlsx/SKILL.md` — richest trigger pattern, 800+ char description

**Comparable manifest formats (compared briefly in §1.3).**
- VSCode extension manifest: <https://code.visualstudio.com/api/references/extension-manifest>
- GitHub Actions `action.yml`: <https://docs.github.com/en/actions/creating-actions/metadata-syntax-for-github-actions>
- Yeoman generators: <https://yeoman.io/authoring/>
- Cursor `.cursor/rules`: <https://docs.cursor.com/context/rules-for-ai>

**HuGR internal.**
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/docs/research/TOOL_UX_ANTHROPIC.md` — prior research; §4 (Claude Code as reference impl), §6 (MCP system-prompt injection), §Anti-patterns.
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/PRODUCT.md` — three-layer architecture; §6 (design invariants).
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/SKILL.md` — current file (written for humans; this doc supersedes it for the Maestro contract).
- `/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/engine/index/catalog.json` — 358 KB inventory, loaded via meta tools not SKILL.md.

---

*End of design doc. Next step — implement the example SKILL.md in §12
as the real file, implement the twenty validation rules as
`engine/audit/skill_contract.py`, and wire the audit into CI.*
