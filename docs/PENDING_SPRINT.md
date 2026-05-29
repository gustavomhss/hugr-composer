# Pending — Current Sprint Ledger

> Single-page inventory of everything discussed in the Phase-6 design
> thread (agent/Forge architecture + dual-index + tree dispatcher +
> compose tool + SKILL.md contract). Tracks what's **active**,
> **deferred-still-pertinent**, and **killed/invalidated** so nothing
> slips silently.
>
> Last updated: 2026-04-20. Authoritative until folded into ROADMAP.md.

---

## 🟢 ACTIVE — being designed / executed right now

| Item | Status | Where | Commit gate |
|---|---|---|---|
| **Design doc: `SKILL.md` contract format** | ✅ written | `docs/research/SKILL_META_FORMAT.md` | awaiting user approval |
| **Design doc: `fastapi_meta_compose` tool** | ✅ written | `docs/research/COMPOSE_TOOL_DESIGN.md` | awaiting user approval |
| **Execute `SKILL.md` per the design** | ⏳ pending approval | will land in `skills/SKILL-001-fastapi-production/SKILL.md` | after approval |
| **Execute `fastapi_meta_compose` per the design** | ⏳ pending approval | will land in `mcp_tools/tier1.py` or `mcp_tools/compose.py` | after approval |
| **New contract rule B2.5** (SKILL.md schema + compose-tool invariants) | ⏳ pending | `engine/audit/contract_check.py` | lands with the two above |

---

## 🟡 DEFERRED — pertinent, not blocking current sprint

Documented here so they don't disappear. Pickup order TBD after the
🟢 items land.

| Item | Why still pertinent | Why deferred now | When |
|---|---|---|---|
| **9 remaining tree dispatchers** (`fastapi_data`, `fastapi_api`, `fastapi_realtime`, `fastapi_resiliency`, `fastapi_observability`, `fastapi_compliance`, `fastapi_deployment`, `fastapi_testing`, `fastapi_meta`) | Completes the tree pattern started with `fastapi_auth`; each domain deserves one dispatcher. | After `SKILL.md` + `compose` land, we'll know if compose + tier-1 meta makes dispatchers partially redundant. | v0.3.1 |
| **Rename 180 legacy tools to `fastapi_<domain>_<verb>_<noun>`** | kubectl-style convention, better discoverability, prompt-cache friendlier. | Cosmetic only; legacy names still work via `catalog.json` mapping. Deferable without functional impact. | v0.4.0 (MINOR bump, breaking) |
| **Catalog.html minimal human page** | User asked for "a single searchable page listing tools/primitives/recipes". | Human consumers are low-priority per user direction; agent is the real consumer. | After SKILL.md lands (uses same catalog.json). |
| **`legacy_name` compat shim in MCP discovery** | Maintains backward compat during the rename above. | Couples with rename; deferred together. | With rename (v0.4.0). |
| **Live benchmark multi-seed full run** | Pre-registered protocol says 3 seeds × 15 specs × 2 conditions = 90 runs. Until that runs, H1 hypothesis not validated. | Expensive (~$30-80 Anthropic API credits + 2-4h wall clock); only meaningful AFTER SKILL.md + compose actually change agent behaviour. | After 🟢 lands + 1 smoke run validates new behaviour; then full matrix. |
| **`fastapi_meta_audit` runs through agent** (real end-to-end test) | Validates the 6th tier-1 tool actually closes the loop. | Depends on agent existing; agent is in another repo. | When HuGR Forge/agent code exists. |
| **SKILL.md body: few-shot transcripts** (3-5 real examples) | Best-practice per research — LLMs imitate examples more than instructions. | Will land with SKILL.md execution; just flagging so we don't skip. | With SKILL.md commit. |
| **Examples expansion 20 → 30** | Broader coverage of the spec surface. | 20 is already enough for statistical validity. | Post-v0.3.0 stretch. |
| **HTML dashboard for blind benchmark results** | Already shipped (`engine/bench/blind/dashboard.py`), but under-tested. Could gain filter/diff views. | Works; polishing isn't critical. | v0.4.0 polish sprint. |

---

## 🔴 KILLED — invalidated by subsequent design decisions

These were on the table but explicitly retired. Logged here so
we don't accidentally resurrect them.

| Item | Why killed | Decision date |
|---|---|---|
| **`/build-fastapi` slash command via MCP Prompts** | User clarified: agent orchestrates, user never types stack-specific slashes. Generic `/build` handled by the agent's intent router is correct. | 2026-04-20 |
| **MCP Resources (`skill://` URIs)** | Anthropic-specific; agent (HuGR's own) doesn't need them. Pythonic import + catalog.json read is enough. | 2026-04-20 |
| **Agent Skills YAML-frontmatter auto-injection via Anthropic Oct-2025 spec** | Same reason — agent-side loading is under our control. We adopt the SKILL.md format (per research), but not the Anthropic runtime hooks. | 2026-04-20 |
| **`defer_loading: true` on 180 tier-2 tools** | Was meant to reduce Claude Code's default tool list. agent constructs its own context; flag becomes moot. | 2026-04-20 |
| **1400-token kit-block in benchmark prompt** | Recognized as anti-pattern ("skill that needs a 1400-token tutorial is lixo"). Will strip from adapter.py once agent enforcement replaces it. | 2026-04-20 |
| **Chain-of-execution protocol (`chain_context`, `pull_block`)** | Overengineering — LLM already maintains chain state in its own context window; filesystem is the real state. Classic LangGraph-planner trap that research (Semantic Kernel deprecation) already warned against. | 2026-04-20 |
| **Unified compose+business-rule tool** | Business rules are open-set custom code (Aggregate + Specification); plumbing is closed-set primitive composition. Different natures → different tools. Compose = plumbing only. Domain rules remain the agent's responsibility. | 2026-04-20 |

---

## 🧭 Architecture pivot (context)

One big reframe shifted a lot of items above:

- **Before**: SKILL-001 is a Claude-Code-MCP skill; we kept trying to make Claude Code itself use it naturally.
- **After**: SKILL-001 is a capability library consumed by **agent**, a HuGR-authored agent that runs inside **HuGR Forge** (our own CLI editor). agent is powered by Claude Opus (or GPT / Gemini interchangeably) and can load skills from its own registry, inject its own system prompt, gate tools per phase — all without depending on Anthropic-specific mechanisms.

Implications:
- Orchestration responsibility moves to agent (state machine, tool gating, few-shot injection). Skill just offers well-shaped capabilities.
- Skill's job = predictable interface + rich descriptions + breadcrumbs. NOT prompt-engineering the user's own Claude Code session.
- Many prior workarounds (1400-token kit-block, MCP Prompts, etc.) become unnecessary because agent handles those concerns upstream.
- `SKILL.md` (the contract file being designed now) is THE interface between skill and agent.

---

## Decision log (chronological)

- 2026-04-20 09:00 — Four research reports commissioned (Anthropic/MCP, academic, production, cognition).
- 2026-04-20 10:30 — Dual-index design (LLM + human) synthesized. User scope-cut: human index = 1 page.
- 2026-04-20 12:00 — `catalog.json` manifest + 6 tier-1 meta tools shipped (commits a826082, 3fb7002).
- 2026-04-20 14:30 — `fastapi_auth` tree dispatcher shipped as POC (commit 9d84ae8).
- 2026-04-20 15:30 — Four live runs analyzed; all zero-margin. Diagnosed as prompt-engineering artefact, not skill defect.
- 2026-04-20 17:00 — User reframe: HuGR Forge + agent architecture revealed. Discarded Claude-Code-specific workarounds.
- 2026-04-20 18:00 — Chain-of-execution proposal killed as overengineering (LangGraph-planner trap).
- 2026-04-20 19:00 — User confirmed compose-tool + SKILL.md-contract as the two missing pieces. This design sprint commissioned.

---

Anything else I've missed? This file is the ledger — add to it or
strike through here, don't scatter.
