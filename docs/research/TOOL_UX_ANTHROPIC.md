# Research Findings — Anthropic & MCP Design (v1, 2026-04-20)

Scope: how Anthropic officially recommends surfacing many tools to Claude, with specific implications for the HuGR Arsenal 201-tool catalog problem.

## TLDR (5 bullets, actionable)

- **Anthropic publishes a hard threshold**: "Claude's ability to correctly pick the right tool degrades significantly once you exceed 30–50 available tools" (Tool Search docs). A flat 201-tool catalog is officially above this line; the ignore-behavior HuGR is seeing is the documented failure mode, not a prompt bug.
- **The officially sanctioned fix is Tool Search + `defer_loading: true`**, not bigger prompts. Anthropic ships a server-side `tool_search_tool_bm25_20251119` / `_regex_20251119` that lets you register all 201 tools but only expose 3–5 by default; Claude searches the rest on demand. Claimed "~85% reduction in context" while keeping selection accuracy high.
- **Agent Skills are the higher-level packaging primitive Anthropic is pushing** (Oct 2025 launch). A Skill = folder with `SKILL.md` frontmatter (name + description) that loads progressively: metadata always, body on trigger, bundled files only when referenced. This is exactly the shape HuGR Arsenal already claims to be — but HuGR is currently exposing the *atomic tools* to the agent instead of a Skill-shaped entry point.
- **Consolidate tools, don't multiply them.** The canonical Anthropic guidance ("Writing effective tools for agents", Sep 2025) says "More tools don't always lead to better outcomes"; recommends replacing `get_customer_by_id` + `list_transactions` + `list_notes` with a single `get_customer_context`. HuGR's 100 EXTEND tools almost certainly collapse into ~15–25 workflow tools.
- **Namespacing is mandatory past ~dozens of tools.** Anthropic recommends `service_resource_action` prefixes (e.g. `asana_projects_search`). HuGR's current flat `add_*` naming gives Claude no grouping signal.

## 1. MCP surfaces: tools vs resources vs prompts

The MCP 2025-06-18 spec defines three server-side surfaces with deliberately different *user-interaction models*:

- **Tools** are "model-controlled": the LLM decides when to invoke them, they can have side effects, and they're the most autonomous surface. Source: [Server Features / Tools](https://modelcontextprotocol.io/docs/concepts/tools).
- **Resources** are "application-driven": "host applications determine how to incorporate context based on their needs… Expose resources through UI elements for explicit selection, in a tree or list view… Implement automatic context inclusion, based on heuristics or the AI model's selection." Each resource is identified by a URI and retrieved via `resources/read`. Source: [Resources](https://modelcontextprotocol.io/docs/concepts/resources).
- **Prompts** are **"user-controlled"**: "they are exposed from servers to clients with the intention of the user being able to explicitly select them for use… Typically, prompts would be triggered through user-initiated commands in the user interface, which allows users to naturally discover and invoke available prompts. For example, as slash commands." Source: [Prompts](https://modelcontextprotocol.io/docs/concepts/prompts).

**Picking between them** (per spec):
- Action with side effects, agent chooses when → **tool**.
- Read-only reference material the agent may or may not pull in (schemas, docs, examples) → **resource**. Supports `resources/templates/list` with URI templates like `file:///{path}` for parameterized reads.
- Reusable workflow the *user* explicitly invokes (slash commands) → **prompt**. Prompts return a full `messages` array with `role: user/assistant` content, i.e. they are canned conversations, not tools.

Implication for HuGR: a generator like `generate_fastapi_project` that the user types on purpose is a **prompt**, not a tool. Specs/briefings/anti-pattern checklists are **resources**, not tools. Side-effectful mutations (`add_stripe_webhook`) are tools.

## 2. Anthropic's tool-count guidance

The most explicit statement comes from the Tool Search docs (part of the Claude Developer Platform):

> "Claude's ability to correctly pick the right tool degrades significantly once you exceed 30–50 available tools. By surfacing a focused set of relevant tools on demand, tool search keeps selection accuracy high even across thousands of tools."
> — [Tool search tool](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool)

The same doc quantifies the context cost: a typical multi-server setup (GitHub, Slack, Sentry, Grafana, Splunk) "can consume ~55k tokens in definitions before Claude does any actual work. Tool search typically reduces this by over 85%."

The engineering blog "Writing effective tools for agents" (Sep 11, 2025) reinforces the *qualitative* side: "Too many tools or overlapping tools can also distract agents from pursuing efficient strategies. Careful, selective planning of the tools you build (or don't build) can really pay off." — [source](https://www.anthropic.com/engineering/writing-tools-for-agents).

"Code execution with MCP" (Nov 4, 2025) generalizes further: "loading all tool definitions upfront and passing intermediate results through the context window slows down agents and increases costs. […] agents can load only the tools they need" — [source](https://www.anthropic.com/engineering/code-execution-with-mcp).

**Verdict**: Anthropic's official position is that a flat catalog >30–50 tools is broken by design. 180 is well past the cliff.

## 3. Tool description conventions

From [Define tools](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use) (Claude API Docs) and the engineering blog:

1. **Extremely detailed descriptions — "the most important factor"**. Minimum 3–4 sentences. Cover: what it does, when to use it, **when NOT to use it**, what each param means, caveats/limitations, what it does *not* return.
2. **Consolidate related operations.** "Rather than creating a separate tool for every action (`create_pr`, `review_pr`, `merge_pr`), group them into a single tool with an `action` parameter." (Define tools doc)
3. **Meaningful namespacing.** "Prefix names with the service (e.g., `github_list_prs`, `slack_send_message`)… especially important when using tool search."
4. **High-signal responses.** Return semantic IDs over UUIDs; resolve cryptic identifiers to natural language where possible; offer a `response_format: CONCISE | DETAILED` enum for agent-controlled verbosity (Slack example in engineering blog: ~⅓ tokens with CONCISE).
5. **Helpful error messages, not tracebacks.** Error strings should tell Claude how to recover.
6. **Unambiguous parameter names.** `user_id`, not `user`.
7. **`input_examples`** field (API-native) for format-sensitive tools: Anthropic recommends concrete valid-input examples for complex/nested params. Note: `input_examples` is **incompatible with Tool Search**.
8. **Token budget**: "For Claude Code, we restrict tool responses to 25,000 tokens by default."

## 4. Claude Code as reference implementation

Claude Code's own tool surface (observable from the environment the user is running right now — see the tool list at conversation top):

**Always-loaded tools (~10)**: Bash, Edit, Write, Read, Grep, Glob, Skill, ScheduleWakeup, ToolSearch, Task (Agent).

**Deferred / on-demand tools** (named in a `<system-reminder>` but with schemas fetched via `ToolSearch`): CronCreate, CronDelete, CronList, EnterWorktree, ExitWorktree, LSP, Monitor, NotebookEdit, PushNotification, RemoteTrigger, WebFetch, WebSearch, `mcp__figma__*`.

**Design observations:**
- Claude Code ships **~10 always-loaded core tools**, not 180. Everything else is deferred.
- Skills (`Skill` tool + `update-config`, `review`, `security-review`, `loop`, `schedule`, `claude-api`, `init`, `simplify`, etc.) are surfaced as a *catalog* the model dispatches into — same mental model as MCP prompts, one level of indirection above tools.
- Names are **verb-first for actions** (`Read`, `Edit`, `Write`, `Bash`), **noun-based for services** (`WebFetch`, `NotebookEdit`), and **CamelCase** (distinguishing built-ins from MCP tools which get `mcp__server__tool` double-underscore namespacing — visible in `mcp__figma__authenticate`).
- Descriptions in this very prompt average ~200–2000 tokens per tool (see the Bash tool description alone: ~1.5k tokens of when-to-call / examples / anti-patterns / git protocol). This is consistent with "3-4 sentences minimum, more for complex tools."
- Tools are grouped by *purpose*: filesystem (Read/Write/Edit), search (Grep/Glob), shell (Bash), automation (Cron*, Schedule, Monitor), notebooks, web, MCP-namespaced third-party.

**Why Claude Code doesn't ship 201 tools**: it uses `Skill` and `ToolSearch` as the scaling primitive. The 180-equivalent lives as skills + deferred tools, not as a flat tool list.

## 5. Hierarchical / JIT tool exposure patterns

Three official patterns, in increasing sophistication:

**A. Tool Search (server-side, Nov 2025).** `tool_search_tool_regex_20251119` or `tool_search_tool_bm25_20251119` added to the `tools` array, plus `"defer_loading": true` on every tool not in the "hot" set. Claude sees only the search tool + the ~3–5 non-deferred tools initially; searches by regex or BM25 across *names, descriptions, argument names, argument descriptions* when it needs more. Tool definitions are appended as `tool_reference` blocks inline; prompt cache is preserved. Source: [Tool search tool](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool).

**B. Agent Skills (filesystem-based, Oct 2025).** Progressive disclosure in three levels:
1. Metadata (YAML frontmatter, always loaded, ~100 tokens per skill).
2. `SKILL.md` body (loaded on trigger, <5k tokens).
3. Bundled files + scripts (loaded only if referenced; "effectively unlimited").

Scripts run via Bash, so their source code never hits context — only stdout does. Source: [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) + [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills).

**C. Code Execution with MCP (Nov 2025).** Present MCP servers as a TypeScript filesystem (`./servers/google-drive/getDocument.ts`) and let the agent write code that imports only what it needs. Claimed 98.7% token reduction in the Google Drive → Salesforce example. Cloudflare calls this "Code Mode." Source: [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp).

All three are officially endorsed; they're not alternatives so much as different scaling regimes.

## 6. System-prompt injection via MCP

Can an MCP server auto-inject workflow guidance? **Partially, with caveats.**

- **Prompts surface is user-controlled by design**, not automatic. Spec: "prompts would be triggered through user-initiated commands in the user interface… as slash commands" — [Prompts spec](https://modelcontextprotocol.io/docs/concepts/prompts). They do not fire automatically on session start.
- **Resources can be auto-included** by the host application: "Implement automatic context inclusion, based on heuristics or the AI model's selection" (Resources spec). But the *host* (e.g., Claude Desktop, Claude Code) decides policy; the server only exposes.
- **Sampling** (`sampling/createMessage`) lets a *server* request the LLM to generate, optionally with `systemPrompt`. This is the inverse direction — server tells client to do an LLM call — not a way to inject into the user's session. Source: [Sampling](https://modelcontextprotocol.io/docs/concepts/sampling).
- **Tool descriptions themselves** *are* injected into the system prompt automatically. Quote from [Define tools](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use): "When you call the Claude API with the tools parameter, the API constructs a special system prompt from the tool definitions…". This is the *only* automatic injection path from an MCP server to the system prompt.
- **Agent Skills *do* auto-inject metadata**: "Claude loads this metadata at startup and includes it in the system prompt" — [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview). Skills are thus the correct primitive for "teach Claude a workflow without relying on user prompt."

**Verdict**: there is no MCP-native "auto-load system prompt fragment on session start" feature. The two legitimate workarounds are (a) pack the workflow instructions into tool *descriptions*, and (b) ship as an Agent Skill rather than raw MCP tools. UNKNOWN from public docs: whether Claude Code's MCP client auto-reads a `README.md` resource from connected servers (not documented as of 2026-04-20).

## 7. Recommendations for HuGR Arsenal

Prioritized, each cited.

**P0 — Stop exposing 180 flat tools. Re-surface as an Agent Skill.**
Cite: [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview). Build `skills/fastapi-production/SKILL.md` with a tight YAML frontmatter (name + 1–2 sentence description that explicitly says "use when the user asks to scaffold, extend, deploy, or audit a FastAPI backend"). The 180 current tools become *scripts* in the skill directory, invoked via Bash, not tools in the MCP sense. This matches what Claude Code itself does.

**P1 — If you keep the MCP tool surface, adopt Tool Search with `defer_loading: true`.**
Cite: [Tool search tool](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool). Mark 170+ tools deferred; keep ~5 "hot" entry tools non-deferred (e.g., `fastapi_search_capability`, `fastapi_generate_project`, `fastapi_extend`, `fastapi_audit`, `fastapi_deploy`). Use BM25 variant for natural-language discovery. This alone should move benchmark numbers without a rewrite.

**P2 — Consolidate the 100 EXTEND tools into ~15–25 workflow tools with `action` params.**
Cite: [Define tools](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use) — "Consolidate related operations into fewer tools… Fewer, more capable tools reduce selection ambiguity." Example: `add_stripe_subscription`, `add_stripe_webhook`, `add_stripe_invoice` → one `fastapi_payments` tool with `provider: stripe` + `action: add_subscription|add_webhook|add_invoice`. Also matches the `get_customer_context` archetype from "Writing effective tools for agents."

**P3 — Namespace everything with a service prefix and drop `add_`.**
Cite: engineering blog "Namespacing your tools" — Anthropic tested prefix vs suffix and found non-trivial effects. Use `fastapi_*` or `hugr_fastapi_*` at minimum; sub-namespace by domain: `fastapi_auth_*`, `fastapi_payments_*`, `fastapi_infra_*`, `fastapi_realtime_*`.

**P4 — Rewrite tool descriptions to the 3–4 sentence + when/when-not/caveats template.**
Cite: [Define tools](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use). Every tool description must answer: what, when, when-NOT, each param, returns, caveats. Current HuGR tools have Pydantic specs but not agent-facing descriptions; these are different audiences.

**P5 — Expose specs and briefings as MCP *resources*, not tools.**
Cite: [Resources](https://modelcontextprotocol.io/docs/concepts/resources). The 64 formal specs + AGENT_BRIEFING_TEMPLATE belong at URIs like `hugr://spec/TOOL-042` / `hugr://briefing/anti-patterns`, retrievable via `resources/read`. They're reference material, not actions — putting them as tools wastes the tool budget.

**P6 — Add `response_format: CONCISE|DETAILED` enum to any tool that returns rich output.**
Cite: engineering blog; Slack example shows ~3x token reduction.

**P7 — Consider Code Execution pattern for FinHealth-style benchmarks.**
Cite: [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp). If the agent has a code sandbox, generate a `./tools/fastapi/*.ts` filetree instead of a flat MCP catalog; the agent imports the 3 it needs. 98.7% token reduction in Anthropic's example.

**Inspirations to copy:**
- **Claude Code's own tool list** (visible in this session): ~10 always-loaded + deferred via ToolSearch + Skill dispatch. That's the reference architecture.
- **Anthropic's Slack/Asana internal tools** (cited in "Writing effective tools for agents"): evaluation-driven tool redesign, specifically collapsing `get_customer_by_id` + `list_transactions` + `list_notes` into `get_customer_context`.
- **Agent Skills progressive disclosure**: metadata→body→bundled files, exactly what HuGR already has latent in its spec/generator/tool split but doesn't expose in that shape.

**Anti-patterns to avoid:**
- **Wrapping every internal API 1:1 as a tool.** Engineering blog: "A common error… tools that merely wrap existing software functionality or API endpoints." The 100 EXTEND tools are exactly this shape.
- **Flat catalog with no namespacing and >50 tools.** Directly contradicted by Tool Search docs.
- **Treating tool descriptions as API docs.** They are *prompts to Claude*; write for a non-deterministic consumer, not a human dev.
- **Returning UUIDs / MIME types / 256px_image_url as primary response fields.** Engineering blog flags this: resolve to natural-language identifiers where possible.

## Sources

- [MCP Tools spec](https://modelcontextprotocol.io/docs/concepts/tools) — tools are model-controlled; canonical `tools/list` + `tools/call`.
- [MCP Resources spec](https://modelcontextprotocol.io/docs/concepts/resources) — application-driven, URI-addressed, supports templates + subscriptions.
- [MCP Prompts spec](https://modelcontextprotocol.io/docs/concepts/prompts) — user-controlled slash commands, return full message arrays.
- [MCP Sampling spec](https://modelcontextprotocol.io/docs/concepts/sampling) — server→client LLM calls, not system-prompt injection.
- [Anthropic — Writing effective tools for agents (Sep 11, 2025)](https://www.anthropic.com/engineering/writing-tools-for-agents) — the canonical tool-design playbook: consolidation, namespacing, response shaping, description prompt-engineering.
- [Anthropic — Code execution with MCP (Nov 4, 2025)](https://www.anthropic.com/engineering/code-execution-with-mcp) — filesystem-as-tools pattern, 98.7% token reduction.
- [Anthropic — Equipping agents for the real world with Agent Skills (Oct 2025)](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) — three-level progressive disclosure.
- [Anthropic — Building effective agents (Dec 2024)](https://www.anthropic.com/engineering/building-effective-agents) — Appendix 2 on tool prompt-engineering; ACI principle.
- [Tool search tool docs](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool) — **the 30–50 tool threshold**, BM25/regex variants, `defer_loading`.
- [Tool use overview](https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview) — client vs server tools, tool-use system prompt mechanics, token cost per model.
- [Define tools](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use) — best practices: detailed descriptions, consolidation, namespacing, `input_examples`.
- [Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) — three loading levels, filesystem architecture, SKILL.md format.
- [Claude Code best practices](https://www.anthropic.com/engineering/claude-code-best-practices) — context management, CLAUDE.md discipline, verification loops.
- Claude Code's own tool inventory — observable directly in this session (tool list in system prompt + `<system-reminder>` enumerating deferred tools via ToolSearch).
