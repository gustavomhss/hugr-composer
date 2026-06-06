## Tool: `add_load_profile`

### Overview parameters
- Tool name: `fastapi_add_load_profile`
- Category: EXTEND > Testing
- Complexity: Medium
- Dependencies: existing FastAPI project + Locust
- Signature: `add_load_profile(project_dir: str, endpoints: list[str] | None = None, users: int = 100, spawn_rate: int = 10, duration_seconds: int = 60, targets_p99_ms: dict[str, int] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `endpoints`: which endpoints to load-test (None = all authenticated endpoints)
  - `users`: simulated concurrent users
  - `spawn_rate`: users/second ramp-up
  - `duration_seconds`: test duration
  - `targets_p99_ms`: per-endpoint p99 latency SLOs (fails test if exceeded)

### Purpose
Generate Locust load test profiles that exercise the API under realistic concurrent load. Each endpoint becomes a `@task` with representative request data (from factories), weighted by estimated production traffic (e.g. GET /items 10x more frequent than POST /items/). The tool also generates SLO assertions: if p99 latency for any endpoint exceeds the target, the test fails with clear output. Includes authentication setup (JWT login at user spawn), a scenario script for common flows (register → login → browse → purchase), and CI integration for load regression testing. Critical for catching performance regressions before they hit production.

### Performance SLOs
- Tool execution time < 3s
- Files modified ≤ 2
- Files created ≥ 5 (locustfile.py, scenarios, SLO assertions, CI config, tests)
- Locust startup < 5s
- Per-endpoint task latency ~= server latency (no measurable overhead from Locust)
- SLO assertion check < 100 ms after test ends
- Supports 10K concurrent users per Locust worker (standard)

### Key technical decisions
1. **Library:** Locust (Python, code-first, distributable)
2. **Task weights:** from a sensible default (GET=10, POST=1, PATCH=2, DELETE=1) unless overridden
3. **User class per scenario:** `BrowsingUser` (read-only), `ActiveUser` (create/update), `AdminUser` (all)
4. **Auth:** `on_start` method logs in and stores JWT for all subsequent requests
5. **Data factories:** use the factories from TOOL-025 to generate realistic request bodies
6. **SLO assertions:** at test end, compare stats.response_times['GET /items/']['p99'] against targets, raise AssertionError if exceeded
7. **Scenario script:** Python script that defines a user journey (register → browse → add to cart → checkout)
8. **Headless mode:** `--headless` for CI runs, `--web-host` for interactive exploration
9. **Report output:** HTML report + JSON summary for CI consumption
10. **Target integration:** tool writes SLOs to a `load_slos.yaml` that CI reads

### Key invariants
1. SLO violations ALWAYS fail the load test (exit code != 0).
2. Load tests NEVER run against production (config validates target URL).
3. Authentication is done ONCE per user (JWT reused for duration).
4. Factory data is realistic (matches schema, passes validation).
5. Tool NEVER modifies application source.
6. Stats file is ALWAYS written even on failure (for debugging).
7. Locust workers are ALWAYS gracefully shut down on timeout.

### User story themes
- 9.1 Basic load test (US-01..05): run 100 users, measure throughput, p99, p50
- 9.2 Scenarios (US-06..10): BrowsingUser, ActiveUser, AdminUser, mixed
- 9.3 SLO enforcement (US-11..15): SLO pass, SLO fail, per-endpoint targets, reporting
- 9.4 CI integration (US-16..20): headless, JSON output, GitHub Actions, comparison to baseline
- 9.5 Edge cases & tool idempotency (US-21..25): auth failure, server crash, Locust crash, tool re-run

### Test plan categories
- 10.1 Generation (T-01..06): locustfile exists, tasks weighted, auth on_start
- 10.2 Execution (T-07..12): run 100 users, stats collected, p99 calculated
- 10.3 SLO (T-13..18): SLO pass, SLO fail, per-endpoint, reporting format
- 10.4 CI (T-19..24): headless mode, JSON output, exit code
- 10.5 Robustness (T-25..30): auth fail, server down, tool idempotency

### Edge cases (15)
1. Server down at test start → Locust fails fast, all requests error
2. All requests fail auth → Locust reports 100% failure, SLO irrelevant
3. Target URL points to prod → tool errors at install (safety check)
4. SLO target too strict (< 1 ms) → every test fails, unlikely to be correct
5. Test duration = 0 → immediate completion, no stats
6. Endpoint returns 500 under load → marked failed, SLO comparison skipped
7. Locust worker crashes mid-test → stats partial, reported
8. Spawn rate > users → all spawn immediately
9. Two users share auth token → token reused, Locust doesn't care
10. Factory data generates invalid body → endpoint rejects, marked failed
11. Custom scenario file missing → tool uses default locustfile.py
12. Report output path not writable → tool errors before run
13. Load test triggers rate limiter → report shows 429s, SLO may adjust
14. Tool re-run idempotent
15. CI has no Locust binary → test skipped, not failed

### Anti-patterns
- DO NOT run against production without explicit flag
- DO NOT ignore SLO violations in CI (fail the build)
- DO NOT use random data that doesn't match schemas (use factories)
- DO NOT run without authentication (unrealistic)
- DO NOT skip report generation on failure
