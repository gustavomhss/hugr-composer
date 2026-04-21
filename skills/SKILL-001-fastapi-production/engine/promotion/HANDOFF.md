# Promotion pipeline — overnight handoff

**Date:** 2026-04-21 → 2026-04-22
**Author:** Claude Opus 4.7 (1M context)
**Status:** Tooling complete, ledger written, zero primitives promoted.
           §A12 discipline intact throughout.

---

## What this is

The mission: prepare the 315-primitive staged+quarantined pool for
individual approve/reject decisions. Zero primitives were promoted
overnight; the §A12 rule ("promote only when benchmark gap demands")
was not silently amended. Everything is ready for your review.

## What was built

| Artefact | Location | Lines | Purpose |
|---|---|---:|---|
| Decision doc | `docs/decisions/0004-tier-lite.md` | 150 | Proposes §A12 amendment + new §B1.7 tier-lite. Awaits ratification. |
| Schemas | `engine/promotion/schemas.py` | 195 | Pydantic contracts (Verdict, Signal, StateFlags, LedgerEntry, Ledger). |
| State inspector | `engine/promotion/state.py` | 230 | Deterministic file-based state: REPLACE_ME count, TLA+ presence, concurrency, mutable state, framework coupling, duplicate detection. |
| Signal detector | `engine/promotion/signals.py` | 160 | §A12(b) signals: TOOL_IMPORT, MODULE_REF, BENCHMARK_REF, GENERATOR_REF. |
| Classifier | `engine/promotion/classify.py` | 260 | 8-rule decision tree, first-match-wins. Emits `ledger.json`. |
| Executor | `engine/promotion/promote.py` | 260 | Atomic promote/delete with rollback; refuses non-ready entries; lite gated on §B1.7 ratification. |
| Ledger renderer | `engine/promotion/ledger.py` | 175 | `ledger.json` → `LEDGER.md` with approve/reject checkboxes. |
| Tests | `engine/promotion/tests/` | 240 | 23 unit tests, all pass. |

## Current ledger (242 primitives)

```
delete         13   (duplicates of already-registered primitives)
keep_staged   229   (no signal yet, OR framework-coupled, OR quarantined)
needs_review    0
promote_full    0
promote_lite    0   (blocked anyway — §B1.7 not yet ratified)
```

**Zero primitives are currently promotable.** This is the honest output,
not an implementation gap. Every staged primitive falls into:

1. **Duplicate of a registered primitive** (13 items) — ready for safe delete.
2. **Framework-coupled** (123 items) — SQLAlchemy models, FastAPI
   middleware, etc. CONTRACT §B1.0.1 forbids framework imports in
   `core/venous/<ns>/`. These need re-extraction as adapter pattern.
3. **No caller signal** (106 items) — extracted speculatively; no
   registered tool, module, or benchmark currently references them.
   §A12(b) gate not met.

## What you do in the morning

### Step 1 — Review the ledger

```bash
cd skills/SKILL-001-fastapi-production
less engine/promotion/LEDGER.md     # 1751 lines, grouped by verdict
```

Or open in your editor of choice. Every entry is a proposed verdict
with:
- `[ ]` approval checkbox
- Rationale (≤2 sentences)
- State flags (REPLACE_ME, loc, concurrency, framework imports, etc.)
- Signals (if any)
- Blockers (what must be resolved before execution)
- Copy-paste `Run:` command

### Step 2 — Approve or reject each DELETE verdict

The 13 deletes are the only immediately executable bucket. They're all
duplicates of already-registered primitives — removing the staged copy
loses nothing, cleans the pool. For each approved entry:

```bash
PYTHONPATH=. .venv/bin/python -m engine.promotion.promote --delete NAME
```

The executor will:
- Back up the tree to a temp dir.
- Remove `core/venous/_extracted/<ns>/NAME/`.
- Rebuild catalog.
- Run contract_check.
- On ANY failure: rollback automatically.

### Step 3 — Decide on §B1.7 ratification (optional)

If you agree with the tier-lite proposal, append a block to
`/CONTRACT.md` §E:

```
### Ratified 2026-04-22 by Gustavo
- §B1.7 tier-lite added. §A12 amended to allow triage-pass promotion.
- tier-lite ratified.
```

That flips the `_lite_ratified()` check in `promote.py` from False to
True. But it doesn't unlock any promotions by itself — you'd still need
primitives with PROMOTE_LITE verdicts + zero blockers, and today there
are none (all candidates are either framework-coupled or without signal).

### Step 4 — Strategic decisions for Phase 5 #30 closeout

The 229 KEEP_STAGED entries split into two buckets that need different
strategies:

**Bucket A: framework-coupled (123 items).** These can't be promoted
as-is. Options:
- (a) Accept they'll live in `_extracted/` forever → batch-delete with a
      ratified waiver saying "extraction produced framework-coupled
      output; not salvageable".
- (b) Invest in a re-extraction pass that splits each into (framework-
      free primitive + FastAPI adapter) per CONTRACT §B1.0.1. Large
      effort — 123 primitives × ~2h each = ~250h.
- (c) Leave untouched until a benchmark demands one specifically; then
      re-extract that one. This is what §A12 already dictates.

**Bucket B: no caller signal (106 items).** These wait for a caller to
emerge. Options:
- (a) Accept as pool — §A12 compliant, nothing to do.
- (b) Wire Phase-5 #26 (benchmark → promotion trigger) so red specs
      auto-flag which of these 106 to promote. Already on the roadmap.

### Step 5 — Cut v1.0 (independent from this work)

Ship gate remains MET (code-level 100/100, 20 examples, §B1.3 floor
22). Nothing in the promotion pipeline blocks v1.0; it's all pre-release
cleanup.

## Guarantees

- **33/33 contract items green** at every commit in this sprint.
- **Tree clean** at handoff (HEAD=f20b254).
- **23 promotion-module unit tests pass.**
- **Zero primitives promoted.** §A12 intact.
- **Rollback proven** via dry-run tests against `Event`, `DeprecationMiddleware`,
  and `Bulkhead` — executor refuses non-ready verdicts.
- **Every commit atomic** — each can be reverted independently.

## Known limitations

1. **`primitive_score` is informational only.** High scores don't
   promote; only §A12(b) signals do.
2. **`compose_with` is seeded empty** for any future promotion. The
   primitive's real composition recipes must be added when it enters
   a real pattern (future PR, not this pipeline).
3. **Lite-tier eligibility heuristics** (stateless, no concurrency, no
   mutable state) are five-of-seven objective; the two subjective bullets
   (ordering invariants, first-order predicates) require human review
   even after ratification.
4. **Quarantined primitives lack their quarantine reason** in most cases
   (no `_quarantined.json` for items physically in `_quarantine/`). The
   classifier falls back to "physical location in `_quarantine/`" as
   the reason; a better pipeline would record extraction-gate rejection
   codes.

## Files changed this sprint (3 commits)

```
aa4526b  feat(promotion): tier-lite decision doc + classifier + per-primitive ledger
9162e21  feat(promotion): executor + markdown ledger + 23 unit tests
f20b254  feat(promotion): detect implicit framework coupling via AST + textual tokens
```

No primitives moved. No §A12 violations. 100% reversible.

---

Sleep well — everything is where you left it, just with a clean ledger
and the tooling to act on it at your pace.
