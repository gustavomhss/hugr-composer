# 0004 — Tier-lite for stateless primitives

> **Status:** Ratified YYYY-MM-DD by Gustavo (v1.0.0 pre-freeze block
> in `/CONTRACT.md §E`). Until Gustavo fills the date + signs §E, this
> ADR remains in "Proposed" state for binding purposes. Machine check
> (`_r_tier_lite_eligibility`) has been in place + vacuously green
> since Wave-1 pre-freeze.
>
> **Author:** Claude (overnight 2026-04-21 / 2026-04-22).
> **Amendments depended-on:** CONTRACT §A12 amended per §3 below;
> CONTRACT §B1.8 added per §4 below. Both land in the same commit as
> this status flip.
> **Scope:** Defines a second valid promotion target ("registered-lite")
> so the staged pool can drain without forcing TLA+ on primitives where
> it adds zero value.

---

## 1. Motivation

`core/venous/_staging/` holds 181 PascalCase-named staged primitives
plus 47 quarantined variants — 228 items total (numbers updated
post-cleanup 2026-04-22; ADR originally cited 194 + 121 = 315 before
the _staging/ pool was cleaned of 305 lowercase-function extraction
garbage and 13 duplicates of already-registered primitives). They each
carry the
bulk of the HuGR shell already (`.py` implementation, `.protocol.py`,
`.contract.json`, `.md`, `test_*.py`, `conftest.py`, `dashboard.json`,
`invariant_bindings.json`, `observability_schema.json`,
`persona_reviews.json`, `proposed_invariants.json`). What they lack is:

- **TLA+ formal spec** — 0 exist across the staged pool. Every
  registered primitive (`core/venous/<ns>/<Name>/`) ships one.
- **Zero `REPLACE_ME` markers** — staged files collectively carry 2122
  placeholders. Registered primitives have none.
- **Entry in `engine/primitives_by_concern.yaml`** — the single source
  of truth for discoverability.

Requiring TLA+ on every staged primitive before promotion creates a
600+ hour bottleneck and — crucially — produces **zero added safety
value** for primitives that have no concurrent state, no ordering
constraints, and no non-trivial invariants. Examples from the staged
pool: `DeprecationMiddleware`, `CORSConfigMiddleware`,
`RequestIdMiddleware`, `JsonErrorResponder`. Their TLA+ spec would
collapse to "state transitions: none; invariant: return headers
correctly" — ritual, not verification.

## 2. Proposal

Introduce a second valid registered tier: **lite**.

| Tier | Shell required | When to choose |
|---|---|---|
| **full** (today's default, unchanged) | Everything registered has now PLUS `.tla` spec + TLC-verified invariants | Concurrent state, ordering constraints, distributed coordination, security-critical invariants, state-machine transitions with illegal paths |
| **lite** (new) | Everything registered has now EXCEPT `.tla` — `proposed_invariants.json` acts as the human-readable contract, unit + property tests cover it | Stateless logic, pure middleware, value objects, format validators, string/bytes transforms, config-derived helpers |

### 2.1 Eligibility (all of the following must be true for lite)

1. **No mutable state** beyond instance initialization — the primitive
   is a pure function of its input OR a request-scoped helper with no
   cross-request shared state.
2. **No concurrency primitives** — no locks, semaphores, queues,
   event loops scheduled from within the primitive.
3. **No ordering invariants** — output does not depend on order of
   prior operations (idempotence is fine; sequencing is not).
4. **All invariants are first-order predicates over inputs** — e.g.
   "output headers match RFC 9110" is first-order; "after N cancels
   the aggregate balance equals prior balance" is NOT first-order and
   requires full tier.
5. **Zero REPLACE_ME markers** at promotion time.
6. **Test coverage ≥ 90%** on the primitive's own `.py`.
7. **No dependency on a full-tier primitive that isn't itself
   registered** — i.e. lite primitives cannot import from unregistered
   staged primitives.

Failing any one bullet → must be promoted at full tier or stay staged.

### 2.2 What stays identical

- `primitives_by_concern.yaml` entry: same schema, with a new field
  `tier: "lite" | "full"` (default `"full"` to preserve existing
  semantics — all 122 current registered primitives keep `full`).
- Orthogonality (§A3), composition recipes (§A5), MCP auto-discovery,
  T0-T9 gate for the non-TLA+ tiers — all unchanged.
- Provenance metadata (`_provenance.json`, `_origin.json`) carries
  forward from staged into registered.
- Compose-with rule (§A5) applies uniformly: every registered-lite
  primitive ships ≥ 3 composition examples in its `.md`, same as full.

### 2.3 Upgrade path (lite → full)

A lite primitive becomes eligible for full tier when any one of:

- A new caller introduces concurrent usage patterns.
- A benchmark spec exposes an ordering invariant not covered by first-
  order predicates.
- An incident post-mortem identifies a race condition or state-machine
  bug.

Upgrade is a normal PR that adds the `.tla` spec + flips
`tier: "full"` in the registry. The primitive's own API surface must
not change across the upgrade — if it does, that's a breaking change
governed by semver, not a tier upgrade.

## 3. §A12 amendment (requested)

Current text:

> **A12 — `_staging/` is a pool, not a backlog.** Promote only when
> benchmark gap demands. No preemptive triage.

Proposed amended text:

> **A12 — `_staging/` is a pool, not a backlog.** Promote only when
> ONE of:
> (a) a benchmark gap demands it;
> (b) the primitive is imported by a registered tool or module;
> (c) the primitive is in-scope for a **triage pass** explicitly
>     ratified in the amendment log, and the triage classifies every
>     item in `_staging/` into promote / keep-staged-with-reason /
>     delete. Triage passes are not recurring — each pass is a one-
>     shot cleanup with a start and end commit.
>
> "No preemptive triage" still forbids speculative promotion of
> individual primitives without one of (a), (b), (c).

Rationale: the original §A12 was written to stop *speculative*
promotion ("this might be useful someday, promote it"). A ratified
triage pass is the opposite: an explicit, bounded, documented sweep
with a clear decision per item. The original discipline is preserved
— the amendment only adds a controlled escape hatch for operational
cleanup.

## 4. §B1.8 addition (as landed in CONTRACT.md)

> Earlier drafts of this ADR numbered the new rule §B1.7; in the
> actual landing, §B1.7 was taken by the FastAPI adapter coverage
> check, so tier-lite eligibility shipped as §B1.8. The text below
> mirrors what's in CONTRACT.md §B1.8 today (authoritative copy).

```
#### B1.8 — Tier-lite eligibility

- **DoD:**
  - `engine/primitives_by_concern.yaml` schema accepts
    `tier: "lite" | "full"`; default is "full"
    (backwards-compatible — all v0.x primitives retain `full`
    semantics).
  - For every registry entry with `tier == "lite"`,
    `_r_tier_lite_eligibility` in
    `engine/audit/contract_check.py` verifies ALL of:
    1. `core/venous/<ns>/<Name>/<Name>.py` exists and is readable.
    2. Zero `REPLACE_ME` markers in that file.
    3. No framework imports (`fastapi`, `starlette`, `sqlalchemy`,
       `sqlmodel`, `pydantic`, `django`, `flask`, `tornado`,
       `aiohttp`) AND no implicit framework tokens (`Mapped[`,
       `APIRouter(`, `Depends(`, `class Base(`) detected by the
       AST helpers in `engine/promotion/state.py`.
    4. No concurrency imports or primitives (`threading`,
       `asyncio`, `multiprocessing`, `Lock`, `Semaphore`,
       `Queue`, …).
  - Lite primitives indexed in `engine/index/catalog.json` with
    `tier="lite"`; consumers can filter by tier.
- **Invariants:** A lite primitive found to violate any
  eligibility check at audit time fails B1.8 — silent drift
  rejected at CI. Upgrading lite → full requires adding the
  `.tla` spec and flipping the registry field in a single PR;
  the primitive's public API MUST NOT change across the upgrade
  (§A10). Lite primitives cannot depend on unregistered staged
  primitives (dependency closure must be fully registered).
- **Completeness:** All existing registered primitives keep
  `tier: "full"` at the v1.0 cut; any new lite primitive ships
  with an eligibility proof in its PR description (maps each of
  the four machine checks + three human-review bullets from §2.1
  above).
- **Quality (SOTA):** A lite primitive's `.md` documents WHY it
  qualifies for lite in a one-paragraph justification naming
  which of the seven §2.1 bullets apply. Promotion executor
  (`engine/promotion/promote.py`) refuses `tier="lite"` until
  the ratification token `§B1.8 ratified` appears in CONTRACT.md
  §E.
```

## 5. Risks

- **Tier-lite becomes a dumping ground.** Mitigated by:
  audit rule demotes violators; PR template forces eligibility
  justification; quarterly review catches gradual drift.
- **Tier choice becomes political.** Mitigated by: the seven
  eligibility bullets are objective and machine-checkable for five of
  them (state, concurrency, deps, REPLACE_ME, coverage). The remaining
  two (ordering invariants, first-order predicates) require human
  review, documented in the PR.
- **Primitives get "stuck" at lite because no one pays the TLA+ cost
  to upgrade.** Accepted — a lite primitive with 0 incidents doesn't
  need upgrading. The upgrade path is pull-driven, not push.

## 6. Reversibility

If this decision proves wrong, the reversal is mechanical:
- Run `engine/promotion/demote.py --all-lite` to move every lite
  primitive back to `_staging/`.
- Remove §B1.8 from CONTRACT.md.
- Remove the `tier` field from `primitives_by_concern.yaml` schema.

No data loss, no primitives deleted, no production code change — the
registry entry and YAML field are purely bookkeeping.

## 7. Decision requested

Gustavo to ratify §A12 amendment + §B1.8 addition via the standard
CONTRACT §C4 ratification block. Until ratified, the promotion
executor (`engine/promotion/promote.py`) refuses to promote with
`tier="lite"` by default — requires explicit `--unratified-preview`
flag which writes a dry-run plan only.

## 8. Ratification status (v1.0.0 pre-freeze)

**Drafted + landed:**

- §A12 amended in `/CONTRACT.md` per §3 above (three promotion
  triggers; triage-pass clause documented).
- §B1.8 added in `/CONTRACT.md` per §4 above (tier-lite eligibility
  machine-checked via `_r_tier_lite_eligibility`).
- New `§E` block drafted in `/CONTRACT.md` citing both amendments.
- This ADR's status field flipped from "Approved pre-ratification"
  to "Ratified YYYY-MM-DD" (date placeholder for Gustavo's sitting).

**What's left for Gustavo:**

- Fill the `YYYY-MM-DD` in the `/CONTRACT.md §E` new block with the
  ratification date.
- Fill the same date in this ADR's Status line (top of file).
- Sign-off in `/FREEZE.md §4` + `/ROADMAP.md §11` per the ship-gate
  ratification items.

After Gustavo's sign-off commit lands, the `§B1.8 ratified` token
appears in CONTRACT.md §E and `engine/promotion/promote.py` accepts
`tier="lite"` promotions without the `--unratified-preview` flag.
Wave 2 (§6.1 of ROADMAP) starts on the next commit.
