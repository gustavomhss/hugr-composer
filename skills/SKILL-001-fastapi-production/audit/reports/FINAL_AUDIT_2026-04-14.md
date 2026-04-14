# SKILL-001 — Final Audit Report

**Timestamp:** 2026-04-14 12:36:31 UTC
**Git SHA:** `10e472c`
**Total elapsed:** 605.9s
**Suites:** 17/18 green

## Grade: 94% — 17/18 suites green

## Suite Results

| # | Suite | Expected | Result | Elapsed |
|---|-------|----------|--------|---------|
| 1 | Unit tests (adapt/) | `1280+` | ✅ PASS — 1279 passed, 4 warnings in 166.91s (0:02:46) | 168.3s |
| 2 | Boot individual | `27/27` | ✅ PASS — Boot test result: 27/27 tools boot cleanly | 53.5s |
| 3 | Boot chains | `5/5` | ✅ PASS — Boot chain result: 5/5 chains pass — all tools compose cleanly. | 169.3s |
| 4 | Property tests | `5/5 properties` | ✅ PASS — RESULT: ALL PASSED — 5/5 properties × 50 tools (250/250 tool-checks passed) | 82.7s |
| 5 | E2E advanced | `4/4` | ✅ PASS — RESULT: ALL PASSED — 4/4 scenarios | 1.6s |
| 6 | Red team | `25/25` | ✅ PASS — Red team: PASS — 25/25 attacks passed (100%) | 3.6s |
| 7 | HTTP smoke | `5/5` | ✅ PASS — 10 passed, 49 warnings in 8.55s | 10.1s |
| 8 | Spec compliance | `79/79` | ✅ PASS — 79 passed in 1.73s | 2.8s |
| 9 | Stress test | `3/3` | ✅ PASS — Result: 3/3 tests passed | 24.6s |
| 10 | Security generated | `15/15` | ✅ PASS — 24 passed, 3 skipped in 1.22s | 3.9s |
| 11 | Consistency | `6/6` | ✅ PASS — Consistency: 6/6 tests pass | 1.0s |
| 12 | Concurrent | `3/3` | ❌ FAIL — Concurrent: 2/3 tests pass  (1 FAILED) | 2.5s |
| 13 | Bandit + deps | `3/3` | ✅ PASS — 11 passed in 2.14s | 3.1s |
| 14 | Determinism | `4/4` | ✅ PASS — Determinism: 4/4 tests pass | 3.4s |
| 15 | Edge cases | `7/7` | ✅ PASS — Alembic migrations: PASS — 3 migration(s) found: ['0001_initial', 'add_audit_log', 'softdel_widgets'] | 19.9s |
| 16 | Generated quality | `13/13` | ✅ PASS — 13 passed in 49.78s | 51.2s |
| 17 | Lint generated | `8/8` | ✅ PASS — 8 passed in 0.80s | 1.8s |
| 18 | Benchmark (100-check) | `100/100` | ✅ PASS — FinHealth benchmark: 100/100 checks passed — Grade S | 2.6s |

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

### Concurrent

- Return code: `1`
- Summary: Concurrent: 2/3 tests pass  (1 FAILED)

```
D after parallel tools — NameError: name 'app' is not defined  (1.93s)

Running Test 2 ...
  [PASS]  TEST 2 [idempotency × 10 parallel]: PASS — 10/10 parallel runs returned no_op, main.py intact  (0.08s)

Running Test 3 ...
  [PASS]  TEST 3 [file-locking stress: 3 tools → main.py]: PASS — add_audit_log=success, add_cache_layer=success, add_circuit_breaker=success; all fingerprints present in main.py  (0.09s)

────────────────────────────────────────────────────────────────────────
  Concurrent: 2/3 tests pass  (1 FAILED)
────────────────────────────────────────────────────────────────────────

```

---

**Final: 17/18 suites green — 1 FAILING**