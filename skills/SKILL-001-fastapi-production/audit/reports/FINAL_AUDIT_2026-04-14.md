# SKILL-001 — Final Audit Report

**Timestamp:** 2026-04-14 23:33:57 UTC
**Git SHA:** `d71c69d`
**Total elapsed:** 1899.8s
**Suites:** 15/18 green

## Grade: 83% — 15/18 suites green

## Suite Results

| # | Suite | Expected | Result | Elapsed |
|---|-------|----------|--------|---------|
| 1 | Unit tests (adapt/) | `1280+` | ✅ PASS — 1279 passed, 4 warnings in 230.45s (0:03:50) | 234.1s |
| 2 | Boot individual | `27/27` | ✅ PASS — Boot test result: 27/27 tools boot cleanly | 319.8s |
| 3 | Boot chains | `5/5` | ❌ FAIL — TIMEOUT (>600s) | 600.0s |
| 4 | Property tests | `5/5 properties` | ✅ PASS — RESULT: ALL PASSED — 5/5 properties × 50 tools (250/250 tool-checks passed) | 121.6s |
| 5 | E2E advanced | `4/4` | ✅ PASS — RESULT: ALL PASSED — 4/4 scenarios | 8.9s |
| 6 | Red team | `25/25` | ✅ PASS — Red team: PASS — 25/25 attacks passed (100%) | 9.9s |
| 7 | HTTP smoke | `5/5` | ✅ PASS — 10 passed, 49 warnings in 21.21s | 25.7s |
| 8 | Spec compliance | `79/79` | ✅ PASS — 79 passed in 4.33s | 8.0s |
| 9 | Stress test | `3/3` | ❌ FAIL — Result: 2/3 tests passed  (1 FAILED) | 165.1s |
| 10 | Security generated | `15/15` | ✅ PASS — 24 passed, 3 skipped in 16.17s | 33.0s |
| 11 | Consistency | `6/6` | ✅ PASS — Consistency: 6/6 tests pass | 8.1s |
| 12 | Concurrent | `3/3` | ✅ PASS — Concurrent: 3/3 tests pass | 22.3s |
| 13 | Bandit + deps | `3/3` | ✅ PASS — 11 passed in 19.20s | 25.2s |
| 14 | Determinism | `4/4` | ✅ PASS — Determinism: 4/4 tests pass | 24.1s |
| 15 | Edge cases | `7/7` | ❌ FAIL — File "/usr/local/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/subprocess.py", li | 34.7s |
| 16 | Generated quality | `13/13` | ✅ PASS — 13 passed in 235.46s (0:03:55) | 240.7s |
| 17 | Lint generated | `8/8` | ✅ PASS — 8 passed in 2.91s | 6.7s |
| 18 | Benchmark (100-check) | `100/100` | ✅ PASS — FinHealth benchmark: 100/100 checks passed — Grade S | 11.9s |

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

### Boot chains

- Return code: `-1`
- Summary: TIMEOUT (>600s)

### Stress test

- Return code: `1`
- Summary: Result: 2/3 tests passed  (1 FAILED)

```
venv/bin/python', '-c', "from app.main import app; print('BOOT OK')"]' timed out after 60 seconds  (64.20s)

Running Test 2 …
  [PASS]  TEST 2 [generated tests after 5 tools]: PASS — 18 passed, 1 failed, 0 errors (of ~19 generated tests)  (74.21s)

Running Test 3 …
  [PASS]  TEST 3 [OpenAPI consistency after 5 tools]: PASS — 54 endpoints, 0 dup operationIds, 0 missing descriptions, 0 body-schema gaps  (25.55s)

────────────────────────────────────────────────────────────────────────
  Result: 2/3 tests passed  (1 FAILED)
────────────────────────────────────────────────────────────────────────

```

### Edge cases

- Return code: `1`
- Summary: File "/usr/local/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/lib/python3.14/subprocess.py", li

```
======================================================================
BLIND SPOT A: Edge case model names
======================================================================

```

```
(stderr_seq) if stderr_seq else None)
subprocess.TimeoutExpired: Command '['/Users/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/.venv/bin/python3', '-c', "import sys; sys.path.insert(0, '.'); from app.main import app; print('BOOT_OK')"]' timed out after 15 seconds

```

---

**Final: 15/18 suites green — 3 FAILING**