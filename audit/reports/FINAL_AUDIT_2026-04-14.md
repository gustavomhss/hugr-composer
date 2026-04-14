# SKILL-001 — Final Audit Report

**Timestamp:** 2026-04-14 02:57:55 UTC
**Git SHA:** `5e1439e`
**Total elapsed:** 691.1s
**Suites:** 14/18 green

## Grade: 77% — 14/18 suites green

## Suite Results

| # | Suite | Expected | Result | Elapsed |
|---|-------|----------|--------|---------|
| 1 | Unit tests (adapt/) | `1280+` | ❌ FAIL — 1279 passed, 4 warnings, 1 error in 181.28s (0:03:01) | 183.4s |
| 2 | Boot individual | `27/27` | ✅ PASS — Boot test result: 27/27 tools boot cleanly | 98.7s |
| 3 | Boot chains | `5/5` | ✅ PASS — Boot chain result: 5/5 chains pass — all tools compose cleanly. | 218.0s |
| 4 | Property tests | `5/5 properties` | ✅ PASS — RESULT: ALL PASSED — 5/5 properties × 50 tools (250/250 tool-checks passed) | 33.0s |
| 5 | E2E advanced | `4/4` | ✅ PASS — RESULT: ALL PASSED — 4/4 scenarios | 2.2s |
| 6 | Red team | `25/25` | ✅ PASS — Red team: PASS — 25/25 attacks passed (100%) | 4.3s |
| 7 | HTTP smoke | `5/5` | ✅ PASS — 10 passed, 49 warnings in 10.82s | 12.8s |
| 8 | Spec compliance | `79/79` | ✅ PASS — 79 passed in 2.87s | 4.1s |
| 9 | Stress test | `3/3` | ❌ FAIL — Result: 2/3 tests passed  (1 FAILED) | 29.1s |
| 10 | Security generated | `15/15` | ✅ PASS — 24 passed, 3 skipped in 2.07s | 3.7s |
| 11 | Consistency | `6/6` | ✅ PASS — Consistency: 6/6 tests pass | 1.6s |
| 12 | Concurrent | `3/3` | ✅ PASS — Concurrent: 3/3 tests pass | 4.6s |
| 13 | Bandit + deps | `3/3` | ✅ PASS — 11 passed in 3.22s | 4.7s |
| 14 | Determinism | `4/4` | ✅ PASS — Determinism: 4/4 tests pass | 5.0s |
| 15 | Edge cases | `7/7` | ❌ FAIL — Alembic migrations: FAIL — - CHAIN GAP: revision 'softdel_widgets' references down_revision='0001_initial' which does no | 28.1s |
| 16 | Generated quality | `13/13` | ❌ FAIL — 3 failed, 10 passed in 51.13s | 53.0s |
| 17 | Lint generated | `8/8` | ✅ PASS — 8 passed in 0.96s | 2.0s |
| 18 | Benchmark (100-check) | `100/100` | ✅ PASS — FinHealth benchmark: 100/100 checks passed — Grade S | 2.9s |

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

### Unit tests (adapt/)

- Return code: `1`
- Summary: 1279 passed, 4 warnings, 1 error in 181.28s (0:03:01)

```
rs/gustavoschneiter/Documents/HuGR/HuGR_Skills/skills/SKILL-001-fastapi-production/.venv/lib/python3.14/site-packages/slowapi/extension.py:717: DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead
    if asyncio.iscoroutinefunction(func):

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR adapt/verify/test_coverage_gaps.py::test_coverage_gaps
1279 passed, 4 warnings, 1 error in 181.28s (0:03:01)

```

### Stress test

- Return code: `1`
- Summary: Result: 2/3 tests passed  (1 FAILED)

```
nvalidRequestError: No such event 'before_flush' for target '<class 'app.models.session.Session'>'  (13.10s)

Running Test 2 …
  [PASS]  TEST 2 [generated tests after 5 tools]: PASS — 18 passed, 1 failed, 0 errors (of ~19 generated tests)  (10.93s)

Running Test 3 …
  [PASS]  TEST 3 [OpenAPI consistency after 5 tools]: PASS — 46 endpoints, 0 dup operationIds, 0 missing descriptions, 0 body-schema gaps  (4.48s)

────────────────────────────────────────────────────────────────────────
  Result: 2/3 tests passed  (1 FAILED)
────────────────────────────────────────────────────────────────────────

```

### Edge cases

- Return code: `1`
- Summary: Alembic migrations: FAIL — - CHAIN GAP: revision 'softdel_widgets' references down_revision='0001_initial' which does no

```
=OK, downgrade=OK
    [softdel_widgets] -> down_revision='0001_initial', upgrade=OK, downgrade=OK
  ISSUES:
    - CHAIN GAP: revision 'softdel_widgets' references down_revision='0001_initial' which does not exist in versions/

Alembic migrations: FAIL

======================================================================
SUMMARY
======================================================================
Edge case models: 7/7 scenarios boot (+1 known-failing)
Alembic migrations: FAIL — - CHAIN GAP: revision 'softdel_widgets' references down_revision='0001_initial' which does not exist in versions/

```

### Generated quality

- Return code: `1`
- Summary: 3 failed, 10 passed in 51.13s

```
state.
E   assert set() == {'cryptography', 'msgpack'}
E     
E     Extra items in the right set:
E     'msgpack'
E     'cryptography'
E     Use -v to get more diff
=========================== short test summary info ============================
FAILED tests/test_generated_quality.py::TestRequirementsCompleteness::test_cryptography_missing_from_requirements
FAILED tests/test_generated_quality.py::TestRequirementsCompleteness::test_msgpack_missing_from_requirements
FAILED tests/test_generated_quality.py::TestRequirementsCompleteness::test_requirements_import_count
3 failed, 10 passed in 51.13s

```

---

**Final: 14/18 suites green — 4 FAILING**