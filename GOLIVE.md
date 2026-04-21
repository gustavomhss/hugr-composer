# GOLIVE — Stabilization checklist to v1.0.0

> **Purpose:** single ordered track from HEAD to the `v1.0.0` git tag.
> Every item is machine-verifiable. Every commit must leave the tree
> greener than it found it. Partial items don't count — done is binary.
>
> **Cut line:** when all §1-§5 items are ✅, we tag `v1.0.0`, push,
> release. §6 is post-freeze.
>
> **Current HEAD:** `c853a22` (2026-04-22, promotion pipeline
> action-focused verdicts).

---

## §1 — Ratifications & CONTRACT amendments (no code changes)

| # | Item | Done check | Owner |
|---|---|---|---|
| 1.1 | FREEZE.md signed by Gustavo | `grep "Ratified.*by Gustavo" FREEZE.md` returns a real date (non-placeholder) | Gustavo |
| 1.2 | §A12 amended in CONTRACT.md per 0004-tier-lite §3 (triage-pass clause) | `grep -q "triage pass" CONTRACT.md` + diff shows A12 text updated | Gustavo |
| 1.3 | §B1.8 rule `_r_tier_lite_eligibility` wired into `engine/audit/contract_check.py` | `python -m engine.audit.contract_check` reports 34/34 green (already landed pre-ratification; ratification makes §B1.8 binding) | Claude (landed) |
| 1.4 | §E ratification block appended with today's date | `grep -E "Ratified 20[0-9]{2}-[0-9]{2}-[0-9]{2} by Gustavo" CONTRACT.md \| tail -1` shows current date | Gustavo |
| 1.5 | `docs/decisions/0004-tier-lite.md` status flipped from "Proposed" to "Ratified" | `grep "Status: Ratified" docs/decisions/0004-tier-lite.md` | Claude (after 1.4) |

## §2 — Promotion pipeline — execute the in-scope promotions (§1.6 of FREEZE)

| # | Item | Done check | Owner |
|---|---|---|---|
| 2.1 | Promote `BulkheadMiddleware --staged` → `BulkheadAdapter.py` | `test -f core/venous/_adapters/fastapi/BulkheadAdapter.py` | Claude |
| 2.2 | Add basic test `test_BulkheadAdapter.py` to match the 16 sibling adapters' test pattern | `test -f core/venous/_adapters/fastapi/test_BulkheadAdapter.py` + pytest passes | Claude |
| 2.3 | Re-run classifier; verify the staged sibling is now classified differently | `engine.promotion.classify` exits 0; `promote_as_adapter` count dropped by ≥1 | Claude |
| 2.4 | Re-generate LEDGER.md | `engine.promotion.ledger` exits 0; file mtime is recent | Claude |
| 2.5 | Leave all other staged items as classified (§A12 discipline); verify counts didn't drift | Ledger `extract_motor_pair / needs_caller / redundant / needs_review` match FREEZE expectations (delta only from promoted BulkheadMiddleware sibling reclassification) | Claude |

## §3 — Quality gates — full test pass

| # | Item | Done check | Owner |
|---|---|---|---|
| 3.1 | Unit tests all green | `pytest skills/SKILL-001-fastapi-production -q` → 0 failures, 0 errors | Claude |
| 3.2 | Promotion module tests | `pytest skills/SKILL-001-fastapi-production/engine/promotion/tests -q` → 38/38 pass | Claude |
| 3.3 | Boot test (100-tool smoke) | `PYTHONPATH=. .venv/bin/python tests/test_boot.py` exits 0 | Claude |
| 3.4 | Boot chain tests (forward + reverse) | `python tests/test_boot_chains.py` exits 0 | Claude |
| 3.5 | E2E hardcore (SQLite, 12 scenarios) | `python tests/test_e2e_hardcore.py` exits 0 | Claude |
| 3.6 | E2E PostgreSQL (only if Docker available) | `./ci.sh --no-pg` first (if passes, skip 3.6); otherwise `./ci.sh` with Docker exits 0. Missing Docker documented in CHANGELOG as "PostgreSQL E2E suite validated in CI nightly". | Claude |
| 3.7 | Behavior scenarios (12 domain archetypes) | `python tests/test_behavior_scenarios.py` exits 0 (requires PostgreSQL; skip gracefully if unavailable and document) | Claude |
| 3.8 | Cross-composition (200+ scenarios) | `python tests/test_cross_composition.py` exits 0 | Claude |
| 3.9 | Property tests (8 properties × ≥120 tools) | `python tests/property_tests.py` exits 0 | Claude |
| 3.10 | Stress test (100-tool) | `python tests/test_stress.py` exits 0 | Claude |
| 3.11 | Soak test (5 min, 10 concurrent) | `python tests/test_soak.py --duration 300` exits 0 | Claude |
| 3.12 | Mutation runner (sample of ≥ 10 modules) | `python tests/mutation_runner.py --sample 10` exits 0 | Claude |
| 3.13 | All `/examples/` pass pytest | `for d in /Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/examples/*/; do (cd "$d" && pytest -q); done` — 0 failures across 20 examples | Claude |

## §4 — Benchmark gate

| # | Item | Done check | Owner |
|---|---|---|---|
| 4.1 | Plan-level benchmark ≥ 70% | `jq '.overall_average' benchmarks/latest_score.json` ≥ 70 (current: 100.00) | Claude |
| 4.2 | Code-level benchmark ≥ 70% on 20/20 specs | `PYTHONPATH=. .venv/bin/python -m engine.bench.code_level` reports overall ≥ 70 + coverage = 20/20 (current: 100.00) | Claude |
| 4.3 | Freeze-day benchmark artefacts committed | `benchmarks/history/$(date +%Y-%m-%d).json` exists with both plan+code sections | Claude |
| 4.4 | No per-spec regression: every spec scored ≥ 50 | `jq '[.specs[].score] \| min' benchmarks/latest_score.json` ≥ 50 | Claude |
| 4.5 | CHANGELOG [1.0.0] cites both benchmark scores + number of covered specs | `grep -E "plan.*100\|code.*100" CHANGELOG.md` matches | Claude |

## §5 — Release artefacts

| # | Item | Done check | Owner |
|---|---|---|---|
| 5.1 | INVENTORY.md matches disk | `engine.inventory` writes INVENTORY.md; `git diff INVENTORY.md` is empty | Claude |
| 5.2 | catalog.json `stable_hash` persisted + cited | `jq -r .stable_hash engine/index/catalog.json` returns 64-char hex; same value appears in CHANGELOG [1.0.0] block | Claude |
| 5.3 | VERSION bumped to `1.0.0` | `cat VERSION` == `1.0.0` (exact) | Claude |
| 5.4 | CHANGELOG.md `[1.0.0]` block complete | Cites: plan score, code score, 20/20 coverage, `stable_hash`, 122 primitives, 17 adapters, 201 catalog tools, 20 examples, 34/34 contract | Claude |
| 5.5 | README.md current (score line + phase badge) | Score cited (100 plan / 100 code); phase badge shows `v1.0.0` | Claude |
| 5.6 | SKILL.md v2 current (no stale counts) | `python -m engine.audit.skillmd_counts` exits 0 | Claude |
| 5.7 | `docs/decisions/0004-tier-lite.md` status flipped to "Ratified YYYY-MM-DD" | `grep -E "Status: *Ratified 20" docs/decisions/0004-tier-lite.md` matches | Claude |
| 5.8 | CONTRACT.md §E amendment log updated | Last block in §E cites: v1.0 ratification, §A12 amendment, §B1.8 addition, date | Claude (body) + Gustavo (sign) |
| 5.9 | HANDOFF.md + session_handoff memory updated | Reflects v1.0 cut + points next session at post-v1.0 work | Claude |
| 5.10 | `/ROADMAP.md` updated to post-v1.0 state | Phases 0-4 marked ✅; Phase 5 `#25/#29` marked ✅; current phase declared "v1.0 shipped, expansion ahead" | Claude |
| 5.11 | FREEZE.md §4 signed | `grep -E "Ratified 20[0-9]{2}-[0-9]{2}-[0-9]{2} by Gustavo" FREEZE.md` matches | Gustavo |

## §6 — Freeze commit + tag + release (manual steps — Gustavo)

| # | Item | Done check | Owner |
|---|---|---|---|
| 6.1 | Create signed tag `v1.0.0` on the freeze commit | `git tag -s v1.0.0 -m "SKILL-001 v1.0.0 frozen"` | Gustavo |
| 6.2 | Push `main` + tag | `git push origin main v1.0.0` | Gustavo |
| 6.3 | GitHub release draft with body pointing to CHANGELOG `[1.0.0]` | Release appears at `github.com/humangr-labs/HuGR_Skills/releases/tag/v1.0.0` | Gustavo |
| 6.4 | Install.sh validated on release tag in fresh Docker | nightly workflow runs green pinned to `v1.0.0` for 48h | Claude (monitor) |

---

## §7 — Execution order (strict)

Items run sequentially unless marked (parallel). Each commit runs
contract + promotion tests before landing; any failure = rollback,
fix, retry.

1. §1.1 (you ratify FREEZE.md) — **blocks** everything else.
2. §1.3 + §1.4 (write §B1.8 machine-check + CONTRACT amendments) — after 1.1.
3. §2.1 → §2.3 (promote BulkheadMiddleware, re-run classifier) — after 1.3.
4. §3.1 → §3.10 (full test pass) — after §2.
5. §4.1 → §4.4 (benchmark gate) — parallel with §3 where independent.
6. §5.1 → §5.9 (release artefacts) — after §3 + §4 all green.
7. §6.1 → §6.4 (freeze commit, tag, release) — after §5.

---

## §8 — Rollback protocol

If any gate fails mid-run:

1. Stop. Don't land a "partial pass" commit.
2. Identify root cause: classifier regression? test flake? benchmark
   drop? Real bug in promotion?
3. Fix at the level of the bug, not the test. Contract stays 33/33
   (or 34/34 post-§B1.8) green; tests get real assertions, not skips.
4. Re-run the failing gate. Only advance after it passes.
5. If the fix requires deferring a scope item, that's a FREEZE.md
   amendment — goes through ratification, not silent edit.

---

## §9 — ETA honest estimate

| Block | Work | ETA |
|---|---|---|
| §1 ratifications | Gustavo 10 min (sign FREEZE + amend CONTRACT §E); §B1.8 code already landed | 10 min |
| §2 promotion | Claude 20 min (promote + adapter test + reclassify + ledger regen) | 20 min |
| §3 full tests | Most runnable in parallel; slowest is soak (5 min real-time) + PostgreSQL E2E (needs Docker ~2 min) | 25-40 min |
| §4 benchmark | Re-run both benches + publish artefacts | 15 min |
| §5 release artefacts | Write CHANGELOG + update INVENTORY/ROADMAP/SKILL.md + sign-off | 40 min |
| §6 manual freeze | Gustavo ≤ 10 min (tag + push + release draft) | 10 min |
| **Total Claude-side work to pre-freeze green** | | **~1.5-2 hours** |
| **Total Gustavo-side work** | | **~20 min** |

Cut line (§6.4 nightly install.sh validation) extends calendar time to
**+48h after tag** before the release is considered "stable" — but the
tag itself ships immediately when §1-§5 are green.

If §3 surfaces a real regression, add fix time. Rollback protocol §8
forbids landing a partial pass, so a regression blocks the cut until
fixed.

---

## §10 — Post-v1.0 (out of scope here, listed in FREEZE.md §2)

Covered in FREEZE.md §2 and `/ROADMAP.md` (post-v1.0 version).
Don't start §10 work until §1-§6 are all ✅.
