# SKILL-001 — Final Audit Report

**Timestamp:** 2026-04-14 20:13:57 UTC
**Git SHA:** `fb5810b`
**Total elapsed:** 422.9s
**Suites:** 17/18 green

## Grade: 94% — 17/18 suites green

## Suite Results

| # | Suite | Expected | Result | Elapsed |
|---|-------|----------|--------|---------|
| 1 | Unit tests (adapt/) | `1280+` | ✅ PASS — 1279 passed, 4 warnings in 90.07s (0:01:30) | 91.7s |
| 2 | Boot individual | `27/27` | ✅ PASS — Boot test result: 27/27 tools boot cleanly | 67.6s |
| 3 | Boot chains | `5/5` | ✅ PASS — Boot chain result: 5/5 chains pass — all tools compose cleanly. | 142.3s |
| 4 | Property tests | `5/5 properties` | ✅ PASS — RESULT: ALL PASSED — 5/5 properties × 50 tools (250/250 tool-checks passed) | 18.1s |
| 5 | E2E advanced | `4/4` | ✅ PASS — RESULT: ALL PASSED — 4/4 scenarios | 1.1s |
| 6 | Red team | `25/25` | ✅ PASS — Red team: PASS — 25/25 attacks passed (100%) | 2.4s |
| 7 | HTTP smoke | `5/5` | ✅ PASS — 10 passed, 49 warnings in 5.48s | 6.6s |
| 8 | Spec compliance | `79/79` | ✅ PASS — 79 passed in 1.51s | 2.4s |
| 9 | Stress test | `3/3` | ✅ PASS — Result: 3/3 tests passed | 20.1s |
| 10 | Security generated | `15/15` | ✅ PASS — 24 passed, 3 skipped in 1.26s | 3.6s |
| 11 | Consistency | `6/6` | ✅ PASS — Consistency: 6/6 tests pass | 0.8s |
| 12 | Concurrent | `3/3` | ✅ PASS — Concurrent: 3/3 tests pass | 2.6s |
| 13 | Bandit + deps | `3/3` | ✅ PASS — 11 passed in 1.57s | 2.3s |
| 14 | Determinism | `4/4` | ❌ FAIL — Determinism: 3/4 tests pass | 2.8s |
| 15 | Edge cases | `7/7` | ✅ PASS — Alembic migrations: PASS — 3 migration(s) found: ['0001_initial', 'add_audit_log', 'softdel_widgets'] | 15.9s |
| 16 | Generated quality | `13/13` | ✅ PASS — 13 passed in 37.74s | 38.9s |
| 17 | Lint generated | `8/8` | ✅ PASS — 8 passed in 0.74s | 1.5s |
| 18 | Benchmark (100-check) | `100/100` | ✅ PASS — FinHealth benchmark: 100/100 checks passed — Grade S | 2.0s |

## Check Counts

| Category | Count |
|----------|-------|
| Unit tests (adapt/) | 1280+ |
| Boot individual tools | 27 |
| Boot chains | 5 |
| Property checks | 5 properties × 51 tools |
| E2E advanced scenarios | 4 |
| Red team attacks | 25 |
| HTTP smoke tests | 5 |
| Spec compliance | 79 |
| Stress tests | 3 |
| Security generated | 15 |
| Consistency checks | 6 |
| Concurrent tests | 3 |
| Bandit + deps | 3 |
| Determinism tests | 4 |
| Edge case tests | 7 |
| Generated quality | 13 |
| Lint generated | 8 |
| Benchmark checks | 100 |

## Known Issues

### Determinism

- Return code: `1`
- Summary: Determinism: 3/4 tests pass

```
 from /var/folders/lt/z11pyzhj0m17vn798jkk69hh0000gn/T/tmpg9gljn22/relocated/app_relocated; no absolute paths found in project files

[TEST 4/4] Regression snapshot (golden file comparison)
  [FAIL] Regression detected (1 divergence(s)) vs /Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/tests/fixtures/golden_snapshot.json:
    total_loc: expected 4856, got 4860

======================================================================
RESULT: 3/4 tests passed
======================================================================

Determinism: 3/4 tests pass

```

```
/var/folders/lt/z11pyzhj0m17vn798jkk69hh0000gn/T/tmpg9gljn22/relocated/app_relocated/app/core/config.py:127: UserWarning: SECRET_KEY is too short (< 32 chars). Generate a proper key with: openssl rand -hex 32
  warnings.warn(

```

---

**Final: 17/18 suites green — 1 FAILING**