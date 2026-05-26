# Contract Standards — Research Phase

> Inviolable. Every contract used in the research phase declares its
> **Completeness Criteria (CC)**, **Invariants (INV)**, **Quality Standards (QS)**,
> and **Definition of Done (DoD)** in this document. Each item carries an ID,
> a rule, a rationale, and a verification mechanism. Nothing here is aspirational —
> every standard is either schema-enforced or acceptance-gated.

## Legend

| Type | Meaning |
|---|---|
| **CC** | Completeness Criterion — something that MUST be present in the artefact. |
| **INV** | Invariant — rule that ALWAYS holds about the artefact's content. |
| **QS** | Quality Standard — SOTA bar above bare correctness; how "good" is measured. |
| **DoD** | Definition of Done — concrete checkpoint for delivery acceptance. |

Each item uses the format: **`ID | rule | rationale | verified-by`**.

`verified-by` values:
- `schema` — Pydantic field constraint (`min_length`, `pattern`, enum, etc.).
- `validator` — custom `@field_validator` or `@model_validator`.
- `gate` — `validate_deliverable()` cross-check against briefing.
- `manual` — orchestrator spot-check during acceptance.
- `test` — self-test in `test_briefing_contract.py`.

A rule labelled `schema+validator+test` is enforced in all three layers.

---

## 1. SourceCitation

**Purpose.** A traceable provenance record. Every claim in a deliverable roots
in at least one `SourceCitation`. No citation = no admissible claim.

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| SRC-CC-01 | `source` field present, length 5..200 chars | nameable corpus (book/RFC/framework/URL) | schema |
| SRC-CC-02 | `locator` field present, length 5..200 chars | a human can jump to the exact place | schema |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| SRC-INV-01 | `source` MUST NOT contain vague phrases ("official docs", "the framework", "common knowledge", …) | vague citations cannot be verified | validator (`VAGUE_SOURCE_FRAGMENTS`) + test |
| SRC-INV-02 | Two citations on the same primitive MUST differ in at least one of (source, locator) | duplicate citations inflate apparent breadth | validator (`sources_unique`) + test |
| SRC-INV-03 | Normalization for dedup/cross-check MUST be `strip() + lower()` | tolerate harmless typos; catch real duplicates | validator |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| SRC-QS-01 | A reviewer can open the source and find the exact claim in ≤ 60 seconds | citations are for verification, not decoration | manual |
| SRC-QS-02 | Prefer versioned corpora ("Spring Boot 3.x Reference") over unversioned ones ("Spring docs") | versions pin semantics | manual + validator (vague phrases) |

### DoD

Every primitive delivers ≥1 `SourceCitation` that passes all SRC-CC-* and SRC-INV-*.
No deliverable with even one non-compliant citation is accepted.

---

## 2. PrimitiveSpec

**Purpose.** The atomic unit of the venous system. A primitive is a named,
namespaced, citable, verifiable contract that any Arsenal target must expose.

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| PRIM-CC-01 | `name` — PascalCase, 3..40 chars, regex `^[A-Z][a-zA-Z0-9]*$` | identifiers must be unambiguous and Python-safe | schema |
| PRIM-CC-02 | `namespace` — one of the declared `Namespace` enum values | prevents ad-hoc taxonomy drift | schema (enum) |
| PRIM-CC-03 | `purpose` — one sentence, 20..200 chars | says WHAT it does; forces precision | schema + validator |
| PRIM-CC-04 | `api_signature` — 20..2000 chars, valid Python AST | code-shaped contract, not prose | schema + validator + test |
| PRIM-CC-05 | `invariants` — list of 3..10 items | single-rule primitives are undercooked; >10 is noise | schema + validator |
| PRIM-CC-06 | `extension_contract` — 40..600 chars | extension surface cannot be a sentence fragment | schema + validator |
| PRIM-CC-07 | `consumption_example` — 20..800 chars, valid Python AST | shows canonical USE, not theory | schema + validator + test |
| PRIM-CC-08 | `sources` — 1..5 unique `SourceCitation` entries | every claim is traceable | schema + validator |
| PRIM-CC-09 | `why_essential` — 30..400 chars | forces rationale for sharedness | schema + validator |
| PRIM-CC-10 | `alternatives_considered` — ≥1 item, each ≥15 chars | SOTA design always knows the alternatives | schema + validator |
| PRIM-CC-11 | `maturity` — one of `battle_tested` / `emerging` / `experimental` | maturity is orthogonal to correctness | schema (enum) |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| PRIM-INV-01 | `name` MUST NOT end in noise suffixes (`Manager`, `Helper`, `Util`, `Utils`, `Service`, `Handler`) | primitives are named by what they ARE, not by role | validator + test |
| PRIM-INV-02 | Each invariant item MUST contain at least one of `MUST`, `NEVER`, `ALWAYS`, `CANNOT`, `SHALL`, `FORBIDDEN` | invariants are rules, not descriptions | validator + test |
| PRIM-INV-03 | Each invariant item MUST NOT open with weak verbs (`provides`, `allows`, `enables`, `offers`, `gives`, `supports`, `helps`) | weak verbs smuggle descriptions past the imperative gate | validator + test |
| PRIM-INV-04 | No field may contain marketing vocabulary (`robust`, `powerful`, `seamless`, …) | SOTA is measured; adjectives are not measurements | validator + test |
| PRIM-INV-05 | `api_signature` MUST declare `name` as a class / function / assignment / PEP 695 type alias | the contract IS the declared symbol | validator + test |
| PRIM-INV-06 | `consumption_example` MUST USE `name` as an `ast.Name` identifier (annotation / call / reference), not only in a class definition or comment or string | "use" means USE, not redefine | validator + test |
| PRIM-INV-07 | `extension_contract` MUST name at least one concrete mechanism (`subclass`, `register`, `decorator`, `adapter`, `hook`, `middleware`, `plugin`, `filter`, `interceptor`, `provider`, `extend`, `implement`, `bind`, `compose`) | extension without mechanism is hand-waving | validator + test |
| PRIM-INV-08 | `purpose` and `why_essential` MUST NOT overlap heavily (alphanumeric-normalized) | one says WHAT, the other WHY; echo = one of them is filler | validator + test |
| PRIM-INV-09 | All five prose fields (`purpose`, `why_essential`, `extension_contract`, invariants, alternatives) run through the marketing scan | marketing sneaks in via any prose | validator + test |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| PRIM-QS-01 | A senior engineer can read the primitive end-to-end in ≤ 90 seconds and understand its surface | primitives that take longer are over-specified or under-articulated | manual |
| PRIM-QS-02 | Every invariant can be turned into a test case without additional context | invariants that cannot be tested are not invariants | manual |
| PRIM-QS-03 | `alternatives_considered` names approaches that were rejected, with ≥15 chars each justifying the rejection implicitly | "considered" ≠ "listed" | validator (length) + manual (substance) |
| PRIM-QS-04 | `maturity` is not self-declared but evidence-backed by the sources | maturity claims require provenance | manual |
| PRIM-QS-05 | `consumption_example` uses only primitives already declared in this deliverable or standard Python types | examples that require unstated primitives are fragile | manual |
| PRIM-QS-06 | `api_signature` uses `Protocol` / ABCs when declaring interfaces, concrete classes only when identity is essential | interfaces first, implementations second | manual |

### DoD

A primitive is done when every PRIM-CC-* and PRIM-INV-* is satisfied (schema +
validators green) AND a sample of PRIM-QS-* holds on manual review.

---

## 3. ResearchAgentBriefing

**Purpose.** The sealed mission handed to a Sonnet agent. Token-efficient.
Every field is a contract point the agent MUST satisfy.

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| BRIEF-CC-01 | `agent_id` ∈ 1..8 | bounded research cohort | schema |
| BRIEF-CC-02 | `codename` — UPPER_SNAKE, 3..40 chars | stable identity across artefacts | schema |
| BRIEF-CC-03 | `mission` — 40..300 chars, one paragraph | forces a precise purpose statement | schema |
| BRIEF-CC-04 | `sources_required` — 3..15 items, each concrete | research floor set before work begins | schema |
| BRIEF-CC-05 | `scope_in` / `scope_out` — each 2..15 items | preventing drift is as explicit as stating scope | schema |
| BRIEF-CC-06 | `namespaces_owned` — 1..6 from `Namespace` enum | no ownership ambiguity | schema |
| BRIEF-CC-07 | `min_primitives` ∈ 8..40; `min_sources_cited` ≥ 5 | rigor floor raised above schema minimum | schema |
| BRIEF-CC-08 | `deliverable_path` — regex-matched, ending `AGENT_<id>_<codename>.md` | path is unambiguous and checkable | schema + validator |
| BRIEF-CC-09 | `forbidden` — LITERAL phrases (≥4 chars effective), scanned by validator | enforcement has teeth, not decoration | schema + gate |
| BRIEF-CC-10 | `anti_patterns` — behavioral judgment calls, rendered in prompt, NOT scanned | semantic advice is for the agent's judgment, not a regex | schema |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| BRIEF-INV-01 | `deliverable_path` MUST end with `AGENT_<agent_id>_<codename>.md` | codename is part of the filesystem identity | validator + test |
| BRIEF-INV-02 | `codename` MUST be unique across all 8 briefings | collision would break consolidation | briefings.py `_sanity_check` |
| BRIEF-INV-03 | `agent_id` sequence MUST be 1..8 without gaps | cohort cardinality is fixed at 8 | briefings.py `_sanity_check` |
| BRIEF-INV-04 | `deliverable_path` MUST be unique across all 8 briefings | each agent owns one output path | briefings.py `_sanity_check` |
| BRIEF-INV-05 | `forbidden` phrases of length ≥ 4 chars MUST be enforced in `validate_deliverable` (no decorative lists) | briefing promises have teeth | gate + test |
| BRIEF-INV-06 | `forbidden` is for LITERAL phrases only; `anti_patterns` carries behavioral / semantic guidance | two different mechanisms — do not conflate | validator + test |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| BRIEF-QS-01 | Rendered prompt (`render_prompt()`) ≤ 1000 tokens | token discipline matters for batch cost | manual (`wc`) |
| BRIEF-QS-02 | `sources_required` items are pinned to a version or edition when applicable | "Spring Boot 3.x Reference" > "Spring docs" | manual |
| BRIEF-QS-03 | `scope_out` is at least as specific as `scope_in` | drift prevention is concrete, not hand-wavy | manual |
| BRIEF-QS-04 | `mission` names both subject and motivation in one paragraph | the agent reads this once; it must land | manual |
| BRIEF-QS-05 | `forbidden` entries are plausible literal strings an agent might actually emit in drafts (`TODO:`, `lorem ipsum`, `[FIXME]`) — not semantic advice | the scanner only matches verbatim text | manual |
| BRIEF-QS-06 | `anti_patterns` entries are behavioral rules the agent must internalize (e.g. "cite every claim") | semantic judgment belongs in prompt, not regex | manual |

### DoD

All 8 briefings pass schema + BRIEF-INV-* at import time (briefings.py
`_sanity_check`). `render_prompt()` output fits the token budget for every agent.

---

## 4. ResearchDeliverable

**Purpose.** The agent's output. Must be self-consistent (schema), internally
truthful (cross-field), and aligned to its briefing (gate).

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| DEL-CC-01 | `agent_id` ∈ 1..8 | same cohort as briefing | schema |
| DEL-CC-02 | `codename` matches briefing regex | identity echoes briefing | schema |
| DEL-CC-03 | `primitives` — ≥ 8 (briefing may raise floor) | schema minimum; real floor is briefing's `min_primitives` | schema + gate |
| DEL-CC-04 | `cross_cutting_insights` — 3..10, each 30..400 chars | patterns spanning multiple primitives, none trivial, none filler | schema + validator |
| DEL-CC-05 | `source_coverage` — dict with ≥ 3 unique non-phantom keys | proves breadth | validator |
| DEL-CC-06 | `gaps_observed` — optional, ≤ 20 items, each 15..300 chars | gaps are a bonus, never an excuse | schema + validator |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| DEL-INV-01 | Primitive names are unique under Unicode-safe normalization (`.casefold()` + whitespace collapse) | two primitives with the same identity cannot coexist; ß == ss; "Current User" == "CurrentUser" | validator + test |
| DEL-INV-02 | No `source_coverage` key has count ≤ 0 | zero/negative counts are nonsense | validator + test |
| DEL-INV-03 | Every source in `source_coverage` is cited by ≥1 primitive (no phantoms) | coverage mirrors reality | validator + test |
| DEL-INV-04 | Every source cited by a primitive appears in `source_coverage` (bidirectional) | omission hides breadth | validator + test |
| DEL-INV-05 | `source_coverage[src]` ≤ actual citation count for `src` | no inflation | validator + test |
| DEL-INV-06 | No single source > 70% of total citation count | one-source deliverables are shallow | validator + test |
| DEL-INV-07 | `cross_cutting_insights` and `gaps_observed` are deduplicated (normalized) | duplicate insights pad the count | validator + test |
| DEL-INV-08 | All prose fields pass the marketing scan | consistency with PrimitiveSpec's INV-04 | validator + test |
| DEL-INV-09 | `source_coverage` keys are unique under normalization (no casing-collision inflation) | `"RFC 6749"` and `"rfc 6749"` are ONE source — cannot pad diversity by splitting casings | validator + test |
| DEL-INV-10 | Diversity count uses unique NORMALIZED keys, not raw key count | matches DEL-INV-09 — no double-counting | validator + test |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| DEL-QS-01 | Each `cross_cutting_insight` cites or echoes at least two distinct sources (implicitly via primitives) | insights span the research, they don't repeat one primitive | manual |
| DEL-QS-02 | `gaps_observed` (when present) are actionable — a reader knows what SKILL-001 currently lacks | vague gaps are non-gaps | manual |
| DEL-QS-03 | Primitive namespaces distribute proportionally across briefing's `namespaces_owned` — not 100% in one namespace | scope coverage matches scope promise | manual |
| DEL-QS-04 | JSON output round-trips: `loads` → `ResearchDeliverable.model_validate` → `model_dump_json` → identical structure | self-consistent artefact | manual (smoke) |
| DEL-QS-05 | Source coverage diversity ≥ `min_sources_cited` (briefing) | promise kept | gate |
| DEL-QS-06 | Every primitive's `maturity` is supported by at least one of its sources | maturity traceability | manual |

### DoD

`validate_deliverable(raw, briefing)` returns `(True, deliverable, [])`. No warnings,
no soft-accepts. If the function returns `False`, the deliverable is rejected.

---

## 5. `validate_deliverable` — Acceptance Gate

**Purpose.** The single chokepoint between agent submission and acceptance.
No deliverable reaches consolidation without passing this gate.

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| GATE-CC-01 | Input raw dict is schema-validated via `ResearchDeliverable.model_validate` | type + field-level rules run first | function body |
| GATE-CC-02 | `agent_id` matches briefing's | no cross-wiring of submissions | function body |
| GATE-CC-03 | `codename` matches briefing's | same | function body |
| GATE-CC-04 | `len(primitives) ≥ briefing.min_primitives` | quantitative floor | function body + test |
| GATE-CC-05 | `len(source_coverage) ≥ briefing.min_sources_cited` | diversity floor | function body + test |
| GATE-CC-06 | Every primitive's namespace ∈ `briefing.namespaces_owned` | scope floor | function body + test |
| GATE-CC-07 | `briefing.forbidden` phrases (len ≥ 4) are scanned across ALL prose: `purpose`, `extension_contract`, `why_essential`, every `invariant`, every `alternatives_considered`, every `cross_cutting_insight`, every `gaps_observed` | briefing promises have teeth; no prose field escapes | function body + test |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| GATE-INV-01 | Return type is `(bool, ResearchDeliverable \| None, list[str])` | deterministic, structured rejection | function signature |
| GATE-INV-02 | If `ok` is `True`, `errors` list is empty; if `False`, ≥ 1 error | no silent passes | function body |
| GATE-INV-03 | Errors MUST be human-actionable (include the field and reason) | agents need to know what to fix | function body |
| GATE-INV-04 | Schema errors SHORT-CIRCUIT gate errors | no partial validation noise | function body |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| GATE-QS-01 | Running the gate is idempotent and side-effect-free | safe for CI / pre-submission loop | manual |
| GATE-QS-02 | Error messages name the specific field/index that failed | rework should not require archaeology | manual |
| GATE-QS-03 | Gate runs in < 500 ms for a deliverable with 20 primitives | keeps the fix-loop tight | manual |

### DoD

All 60 self-tests pass. The CLI wrapper (`check_deliverable.py`) exits 0 for
accepted deliverables, 1 for rejected (schema / briefing), and 2 for I/O errors
(missing file, invalid JSON, permission denied) — each with structured messages.

---

## 6. Research Phase — Orchestration

**Purpose.** The end-to-end process binding the 8 agents, the contract, and
the consolidated catalog. This is the contract you do NOT violate.

### Completeness Criteria

| ID | Rule | Why | Verified by |
|---|---|---|---|
| ORCH-CC-01 | 8 agents dispatched, each with a distinct briefing | parallelism and ownership are explicit | briefings.py `_sanity_check` |
| ORCH-CC-02 | Each agent delivers `.md` narrative + `.json` structured output | human-readable + machine-verified | manual + gate |
| ORCH-CC-03 | Every deliverable passes the gate before consolidation | no soft-accept path | gate |
| ORCH-CC-04 | Consolidator produces `CATALOG.md`, `GAPS.md`, `SKILL_001_AUDIT.md` | three artefacts, one truth | manual |
| ORCH-CC-05 | Every catalog primitive carries its originating agent's codename | provenance in the consolidated view | manual |

### Invariants

| ID | Rule | Why | Verified by |
|---|---|---|---|
| ORCH-INV-01 | ALWAYS validate before trusting | agents sometimes self-report "PASS" falsely | gate |
| ORCH-INV-02 | NEVER accept a deliverable with schema errors, even partially | partial acceptance corrupts downstream | gate |
| ORCH-INV-03 | MUST de-duplicate primitives across agents (case-insensitive exact name under `_norm`) | two agents writing `CurrentUser` is one primitive; overlap is expected (see `namespace_overlap_report()`) | consolidator (manual) |
| ORCH-INV-04 | MUST retain provenance (agent + sources) when merging | traceability survives consolidation | consolidator |
| ORCH-INV-05 | `scope_out` of every briefing MUST be respected in its deliverable | drift = re-spawn, not patch | manual |

### Quality Standards

| ID | Rule | Why | Verified by |
|---|---|---|---|
| ORCH-QS-01 | Total unique primitives ≥ 90 after consolidation | matches the pre-stated floor (8 × per-agent minimums) | manual |
| ORCH-QS-02 | Total unique sources ≥ 44 | matches the pre-stated floor | manual |
| ORCH-QS-03 | Every namespace has ≥ 1 primitive across the consolidated catalog | no empty organs in the venous system | manual |
| ORCH-QS-04 | Consolidated `GAPS.md` is the diff between catalog and SKILL-001 — not wish-list prose | gaps are a lever for the next phase | manual |

### DoD

1. `briefings.py` imports clean (`_sanity_check` passes).
2. All 8 JSON deliverables pass `check_deliverable.py` with exit 0.
3. `CATALOG.md` + `GAPS.md` + `SKILL_001_AUDIT.md` exist and are internally consistent.
4. Every primitive in the catalog is traceable to at least one (agent, source) pair.
5. All 60 contract self-tests still pass after consolidation tooling is added.

---

## Cross-reference table (rule → enforcement)

| Layer | What it enforces |
|---|---|
| Pydantic `Field(...)` constraints | types, length bounds, regex, enum membership |
| `@field_validator` | vague source detection, marketing scan, imperative keywords, alt-length, source dedup (normalized), insight/gap substance + dedup |
| `@model_validator` | api/example/extension/purpose/why cross-field rules; source coverage truthfulness (bidirectional); unique primitive names (Unicode casefold); unique coverage keys (normalized); diversity on unique-normalized-keys; dominance |
| `validate_deliverable` (gate) | briefing cross-check: agent_id, codename, min_primitives, min_sources_cited, namespace scope, forbidden-phrase scan across ALL prose fields |
| `_sanity_check` in briefings.py | 8-cohort invariants: unique codenames, contiguous ids, unique paths |
| `test_briefing_contract.py` | 60 tests proving every validator accepts valid and rejects each failure mode |
| Unicode normalization | single helper `_norm(s)` = `.casefold() + whitespace collapse` — used consistently by every cross-check |
| Manual review | QS items not mechanically checkable (craft, readability, evidence) |

## Why this document exists

Contracts without published standards are negotiable. Published standards without
verification are aspirational. This document closes both loops — every rule has
an ID, a rationale, and an enforcement mechanism. When a deliverable is rejected,
the rejection cites this document by ID. When a new rule is proposed, it goes
here first with `verified-by`, or it does not go in.
