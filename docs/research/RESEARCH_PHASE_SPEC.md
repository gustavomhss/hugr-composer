# Research Phase — SPEC

> Sealed specification for the venous-system research phase.
> 8 Sonnet agents · Pydantic contracts · deterministic validation.

## Goal

Produce a SOTA catalog of primitives that will anchor the HuGR Arsenal venous
system. Each primitive is backed by concrete sources (books, RFCs, framework
references), carries verifiable invariants, and declares its maturity.

Downstream consumers: `VENOUS_SYSTEM_CATALOG.md`, `VENOUS_SYSTEM_GAPS.md`,
SKILL-001 normalization, SkillEngine design.

## Non-goals (this phase)

- No code changes to SKILL-001 tools.
- No Terraform / K8s / frontend primitives (separate chapter).
- No vendor product comparisons.

## Artifacts (all under `docs/research/`)

| File | Role |
|---|---|
| `CONTRACT_STANDARDS.md` | CCs / INVs / QSs / DoD for every contract, with rationale and enforcement map. |
| `contracts/briefing_contract.py` | Pydantic contracts for briefing + deliverable + validator function. |
| `contracts/test_briefing_contract.py` | 60 self-tests proving the contract accepts valid / rejects broken. |
| `contracts/check_deliverable.py` | Pre-submission CLI for agents. |
| `briefings/briefings.py` | 8 `ResearchAgentBriefing` instances, sanity-checked at import. |
| `outputs/AGENT_N_CODENAME.md` | Agent deliverables (markdown narrative). |
| `outputs/AGENT_N_CODENAME.json` | Agent deliverables (structured, validator input). |
| `VENOUS_SYSTEM_CATALOG.md` | Consolidated catalog (produced by orchestrator). |
| `VENOUS_SYSTEM_GAPS.md` | Diff between ideal catalog and current SKILL-001. |
| `SKILL_001_AUDIT.md` | Inventory of current primitives in SKILL-001 (produced by orchestrator). |

## The 8 agents

| # | Codename | Namespaces owned | Min primitives | Min sources |
|---|---|---|---|---|
| 1 | FRAMEWORKS | auth, data, api, obs, flags | 12 | 6 |
| 2 | DISTRIBUTED | events, jobs, data, cache, extras | 12 | 6 |
| 3 | PATTERNS | data, events, api | 12 | 5 |
| 4 | RESILIENCY | resiliency, extras | 10 | 5 |
| 5 | SECURITY | security, auth, policy | 12 | 6 |
| 6 | COMPLIANCE | compliance, obs, data, policy | 10 | 5 |
| 7 | OBSERVABILITY | obs, compliance | 10 | 5 |
| 8 | LLM_ERA | llm, cost, obs | 12 | 6 |
| | **Total floor** | | **≥ 90 primitives** | **≥ 44 unique sources** |

## Contract surface (summary)

### PrimitiveSpec (atomic unit)

- `name` — PascalCase, no noise suffix (`Manager`, `Helper`, …).
- `namespace` — one of the declared `Namespace` enum values.
- `purpose` — 20-200 chars, no marketing vocabulary.
- `api_signature` — valid Python (`ast.parse`), MUST declare `name` as a class / function / assignment.
- `invariants` — 3-10 rules; each MUST contain `MUST` / `NEVER` / `ALWAYS` / `CANNOT` / `SHALL`; no marketing.
- `extension_contract` — 40-600 chars; MUST name a concrete mechanism (`subclass`, `register`, `decorator`, `adapter`, …).
- `consumption_example` — valid Python; `name` MUST appear as an AST identifier (not only in comments / strings).
- `sources` — 1-5 unique `SourceCitation` entries, non-vague.
- `why_essential` — 30-400 chars; must diverge from `purpose`.
- `alternatives_considered` — ≥ 1 item, each ≥ 15 chars.
- `maturity` — `battle_tested` / `emerging` / `experimental`.

### ResearchDeliverable (agent output)

- `agent_id` + `codename` — must match briefing.
- `primitives` — ≥ 8 (briefing may raise floor); case-insensitive unique names.
- `cross_cutting_insights` — 3-10 items, 30-400 chars each, deduplicated, no marketing.
- `source_coverage` — truthful (no phantoms, no inflation, no zero counts).
- `gaps_observed` — optional; each 15-300 chars, deduplicated, no marketing.

### ResearchAgentBriefing (mission handed to agent)

- `mission` — 40-300 chars.
- `sources_required` — ≥ 3 concrete names.
- `scope_in` / `scope_out` — ≥ 2 bullets each.
- `namespaces_owned` — ≥ 1 from `Namespace`.
- `min_primitives` ∈ [8, 40]; `min_sources_cited` ≥ 5.
- `deliverable_path` — regex-enforced; MUST end in `AGENT_<id>_<codename>.md`.
- `forbidden` — phrases that will be scanned for in the deliverable (non-decorative).

## Agent workflow

```
1. Read briefing (rendered from ResearchAgentBriefing).
2. Research the listed sources — every claim needs a citation.
3. Draft primitives — one PrimitiveSpec per primitive.
4. Compile cross_cutting_insights (patterns spanning multiple primitives/sources).
5. Compute source_coverage from the primitives (NOT guessed).
6. Optional: list gaps_observed (things SKILL-001 likely lacks).
7. Write BOTH:
     outputs/AGENT_N_CODENAME.md     (human-readable narrative)
     outputs/AGENT_N_CODENAME.json   (structured, contract-shaped)
8. Self-check:
     python3 docs/research/contracts/check_deliverable.py \
         --agent N --deliverable outputs/AGENT_N_CODENAME.json
9. Fix errors until the CLI exits 0.
10. Submit.
```

## Validation gates

Every deliverable passes through:

1. **Schema load** — Pydantic `ResearchDeliverable.model_validate()`.
   Fails on: field types, length bounds, regex patterns, imperative keywords,
   marketing vocabulary, ast.parse errors, name declaration, primitive name uniqueness,
   duplicate insights/gaps, source dedup, source_coverage truthfulness.
2. **Briefing cross-check** — `validate_deliverable(raw, briefing)`.
   Fails on: agent_id / codename mismatch, namespace off-scope, min_primitives floor,
   min_sources_cited floor, forbidden phrases.

If ANY gate fails, the deliverable is returned to the agent with a structured
error list. No soft-accepts.

## Orchestrator responsibilities (post-research)

1. Load all 8 deliverables, re-validate each.
2. De-duplicate primitives across agents (case-insensitive exact name; semantic dedup is manual).
3. Produce `VENOUS_SYSTEM_CATALOG.md` — canonical catalog with per-primitive proveniência.
4. Audit SKILL-001: map each catalog primitive to existing implementations (or declare missing).
5. Produce `VENOUS_SYSTEM_GAPS.md` — prioritized diff.
6. Produce `SKILL_001_AUDIT.md` — where the skill currently stands.

## Why this is worth the rigor

Template + LLM hybrid beats pure LLM by 10-25×. The quality of the template
library IS the moat. A venous system built on vibes becomes an inconsistent
mess within three additions. A venous system built on this contract stays
coherent through SKILL-002 (Rust), SKILL-003 (NestJS), and beyond.

Contract now → zero rework later.
