# 0004 — Tier-lite for stateless primitives

> **Status:** Approved pre-ratification — machine check (§B1.8) already
> landed and green; awaits Gustavo's formal signature in CONTRACT.md §E
> on freeze day (see GOLIVE.md §1.2 / §1.4).
> **Author:** Claude (overnight 2026-04-21 / 2026-04-22).
> **Depends on:** Amendment to CONTRACT §A12 and addition of §B1.8.
> **Scope:** Defines a second valid promotion target ("registered-lite")
> so the staged pool can drain without forcing TLA+ on primitives where
> it adds zero value.

---

## 1. Motivation

`core/venous/_extracted/` holds 194 PascalCase-named staged primitives
plus 121 quarantined variants — 315 items total. They each carry the
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

> **A12 — `_extracted/` is a pool, not a backlog.** Promote only when
> benchmark gap demands. No preemptive triage.

Proposed amended text:

> **A12 — `_extracted/` is a pool, not a backlog.** Promote only when
> ONE of:
> (a) a benchmark gap demands it;
> (b) the primitive is imported by a registered tool or module;
> (c) the primitive is in-scope for a **triage pass** explicitly
>     ratified in the amendment log, and the triage classifies every
>     item in `_extracted/` into promote / keep-staged-with-reason /
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

## 4. §B1.8 proposal (new contract item)

```
#### B1.7 — Registered-lite tier

- **DoD:**
  - `engine/primitives_by_concern.yaml` schema accepts
    `tier: "lite" | "full"`; default "full".
  - `engine/audit/contract_check.py` rule `_r_lite_eligibility`:
    for every `tier: "lite"` entry, verify: zero REPLACE_ME in
    `core/venous/<ns>/<Name>/`, no concurrency imports, test
    coverage ≥ 90%, no unregistered primitive imports.
  - Lite primitives indexed in catalog.json with `tier="lite"`.
- **Invariants:** A lite primitive found to violate any eligibility
  rule at audit time is demoted back to staged (tooling:
  `engine/promotion/demote.py`). Silent drift rejected at CI.
- **Completeness:** All existing registered primitives keep
  `tier: "full"`; any new lite primitive ships with eligibility
  proof in its PR description.
- **Quality (SOTA):** A lite primitive's `.md` MUST document why it
  qualifies for lite — one-paragraph justification naming which of
  the seven eligibility bullets apply.
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
  primitive back to `_extracted/`.
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
