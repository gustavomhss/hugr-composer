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
| 1.1 | FREEZE.md signed by Gustavo | `grep "Ratified.*by Gustavo" FREEZE.md` returns a real date | Gustavo |
| 1.2 | §A12 amended in CONTRACT.md (triage-pass clause from 0004-tier-lite §3) | `grep "§A12 amendment" CONTRACT.md` | Gustavo |
| 1.3 | §B1.7 added to CONTRACT.md + machine-check rule in `engine/audit/contract_check.py` | `python -m engine.audit.contract_check` reports 34/34 green | Claude |
| 1.4 | §E ratification block appended with 2026-XX-XX date | `grep "Ratified 2026" CONTRACT.md` | Gustavo |

## §2 — Promotion pipeline — execute the in-scope promotions (§1.6 of FREEZE)

| # | Item | Done check | Owner |
|---|---|---|---|
| 2.1 | Promote `BulkheadMiddleware` → `BulkheadAdapter.py` | `test -f core/venous/_adapters/fastapi/BulkheadAdapter.py` + classifier re-run drops PROMOTE_AS_ADAPTER count to 0 | Claude |
| 2.2 | Re-run classifier, verify ledger reflects post-promotion state | `engine.promotion.classify` exits 0 with `promote_as_adapter=0` | Claude |
| 2.3 | Leave all other staged items as classified (§A12 discipline) | Ledger shows `extract_motor_pair=118, needs_caller=104, redundant=2, needs_review=3` | Claude |

## §3 — Quality gates — full test pass

| # | Item | Done check | Owner |
|---|---|---|---|
| 3.1 | Unit tests all green | `pytest skills/SKILL-001-fastapi-production -q` → 0 failures | Claude |
| 3.2 | Promotion module tests | `pytest engine/promotion/tests -q` → 32/32 | Claude |
| 3.3 | E2E hardcore (SQLite) | `python tests/test_e2e_hardcore.py` exits 0 | Claude |
| 3.4 | E2E PostgreSQL | `docker-compose up -d postgres && python tests/test_e2e_postgres.py` exits 0 | Claude |
| 3.5 | Behavior scenarios (12 domain archetypes) | `python tests/test_behavior_scenarios.py` exits 0 | Claude |
| 3.6 | Cross-composition (200+ scenarios) | `python tests/test_cross_composition.py` exits 0 | Claude |
| 3.7 | Property tests (8 properties × N tools) | `python tests/property_tests.py` exits 0 | Claude |
| 3.8 | Soak test (5 min, 10 concurrent) | `python tests/test_soak.py --duration 300` exits 0 | Claude |
| 3.9 | Mutation runner (sample of ≥ 10 modules) | `python tests/mutation_runner.py --sample 10` exits 0 | Claude |
| 3.10 | All `/examples/` pass pytest | `for d in examples/*/; do pytest $d; done` 0 failures | Claude |

## §4 — Benchmark gate

| # | Item | Done check | Owner |
|---|---|---|---|
| 4.1 | Plan-level benchmark ≥ 70% | `jq '.overall_average' benchmarks/latest_score.json` ≥ 70 (currently 100.00) | Claude |
| 4.2 | Code-level benchmark ≥ 70% | `engine.bench.code_level --publish` reports ≥ 70 (currently 100.00) | Claude |
| 4.3 | Benchmark artefacts committed to `benchmarks/history/YYYY-MM-DD.json` | File exists under `benchmarks/history/` | Claude |
| 4.4 | Benchmark regression alarm: no red spec | Every spec scored ≥ 50 individually | Claude |

## §5 — Release artefacts

| # | Item | Done check | Owner |
|---|---|---|---|
| 5.1 | INVENTORY.md matches disk | `engine.inventory` output diff against INVENTORY.md is empty | Claude |
| 5.2 | catalog.json stable hash documented | `engine.index.manifest build` produces known hash; value written in CHANGELOG | Claude |
| 5.3 | VERSION bumped to `1.0.0` | `cat VERSION` == `1.0.0` | Claude |
| 5.4 | CHANGELOG.md `[1.0.0]` block present + complete | Entry cites plan+code scores, primitive/tool/adapter/example counts, stable_hash | Claude |
| 5.5 | README.md current (score line + phase badge) | Score cited; badge shows `phase: v1.0` | Claude |
| 5.6 | SKILL.md v2 current (no stale counts) | `python -m engine.audit.skillmd_counts` exits 0 | Claude |
| 5.7 | `docs/decisions/0004-tier-lite.md` status flipped to "ratified YYYY-MM-DD" | `grep "Status: Ratified" docs/decisions/0004-tier-lite.md` | Claude |
| 5.8 | CONTRACT.md §E amendment log updated | `tail CONTRACT.md` shows the v1.0 ratification block | Claude |
| 5.9 | HANDOFF.md + session_handoff memory updated | Reflects v1.0 cut + points next session at post-v1.0 work | Claude |

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
2. §1.3 + §1.4 (write §B1.7 machine-check + CONTRACT amendments) — after 1.1.
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
   (or 34/34 post-§B1.7) green; tests get real assertions, not skips.
4. Re-run the failing gate. Only advance after it passes.
5. If the fix requires deferring a scope item, that's a FREEZE.md
   amendment — goes through ratification, not silent edit.

---

## §9 — ETA honest estimate

| Block | Work | ETA |
|---|---|---|
| §1 ratifications | Gustavo 10 min + Claude 30 min (writing B1.7 rule) | 40 min |
| §2 promotion | Claude 20 min (promote + verify + reclassify) | 20 min |
| §3 full tests | Most runnable in parallel; slowest is soak (5 min) | 20-30 min |
| §4 benchmark | Re-run both benches + publish | 15 min |
| §5 release artefacts | Write CHANGELOG + update pointers | 30 min |
| §6 manual freeze | Gustavo ≤ 10 min | 10 min |
| **Total to v1.0.0 tag** | | **~2-2.5 hours of focused work** |

Provided nothing fails mid-run. If §3 surfaces a real regression,
add fix time.

---

## §10 — Post-v1.0 (out of scope here, listed in FREEZE.md §2)

Covered in FREEZE.md §2 and `/ROADMAP.md` (post-v1.0 version).
Don't start §10 work until §1-§6 are all ✅.
