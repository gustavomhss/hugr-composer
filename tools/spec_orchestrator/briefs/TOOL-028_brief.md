## Tool: `detect_n_plus_one`

### Overview parameters
- Tool name: `fastapi_detect_n_plus_one`
- Category: VERIFY
- Complexity: High
- Dependencies: existing FastAPI project with SQLAlchemy
- Signature: `detect_n_plus_one(project_dir: str, threshold: int = 10, mode: Literal["fail_fast", "warn"] = "warn", exclude_routes: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `threshold`: max queries per request before flagging (default 10)
  - `mode`: `fail_fast` raises exception; `warn` logs warning
  - `exclude_routes`: routes exempt from detection

### Purpose
Detect N+1 query patterns at runtime and fail tests when they occur. Attaches a SQLAlchemy event listener that counts queries per request. If any request issues more queries than `threshold`, the detector either fails (strict) or warns (dev mode). This catches the most common performance bug in ORM-based APIs: developers iterating over parent objects and lazy-loading children one-by-one. The tool generates middleware, a query counter, pytest fixtures that assert no N+1, and a CI gate that fails the build on new N+1s.

### Performance SLOs
- Tool execution time < 3s
- Files modified ≤ 3
- Files created ≥ 6 (detector middleware, event listener, pytest fixture, CI config, report, tests)
- Detection overhead per request < 0.5 ms
- Query counting via SQLAlchemy event (no production perf hit)
- Report generation < 100 ms
- Works with both sync and async sessions

### Key technical decisions
1. **Event listener:** `after_cursor_execute` counts every SQL statement
2. **Per-request context:** uses contextvars to track count per request
3. **Middleware:** resets counter at request start, reads at request end
4. **Threshold:** configurable per route via decorator `@max_queries(5)`
5. **Exclusion:** routes that intentionally issue many queries (reports, migrations) excluded
6. **Fail mode:** raises `NPlusOneDetected` → FastAPI returns 500 in dev
7. **Warn mode:** logs `WARNING N+1 detected: GET /items/ issued 47 queries`
8. **Pytest integration:** `@pytest.mark.no_n_plus_one` asserts count < threshold for that test
9. **CI gate:** separate test run with `mode=fail_fast` + all tests; any failure blocks merge
10. **Trace capture:** on detection, log the last 20 queries with stack traces for debugging

### Key invariants
1. Detection is OFF by default in production (opt-in via env var).
2. Excluded routes NEVER trigger detection.
3. Query count ALWAYS resets at request start (no leakage between requests).
4. Threshold is PER-REQUEST, not global.
5. Detection NEVER changes query results (observer only).
6. Middleware order MATTERS: must run inside auth but outside logging.
7. Async sessions are supported via `event.listens_for(AsyncSession, "after_cursor_execute")`.

### User story themes
- 9.1 Basic detection (US-01..05): route with N+1 fails, counter accurate
- 9.2 Exclusion (US-06..10): report endpoint excluded, decorator override
- 9.3 CI integration (US-11..15): test gate, failure blocks merge, report
- 9.4 Debugging (US-16..20): stack trace capture, last-20 queries log
- 9.5 Edge cases (US-21..25): async session, legit multi-query, tool idempotency

### Test plan categories
- 10.1 Detection (T-01..06): N+1 detected, count correct, threshold applied
- 10.2 Exclusion (T-07..12): route excluded, decorator override
- 10.3 Fail vs warn (T-13..18): fail_fast raises, warn logs
- 10.4 Context isolation (T-19..24): concurrent requests counted separately
- 10.5 Integration (T-25..30): async session, pytest marker, tool idempotency

### Edge cases (15)
1. Route genuinely needs 20 queries → exclude or decorator override
2. Async session → same event listener works
3. N+1 inside a background task → not counted (request-scoped)
4. Query counter reset fails → contextvar rebuilds on next request
5. Production env var enables detection → accidental perf hit, tool warns
6. Decorator threshold < global threshold → local wins
7. Route with subqueries (1 query) → counted as 1
8. Savepoints counted → configurable
9. Multiple middlewares in chain → detector MUST be last after auth
10. Stack trace capture slows dev → optional, off by default
11. N+1 in startup/migration → excluded via "pre-request" check
12. Concurrent requests in async → each has its own contextvar
13. Test mode doesn't reset context → pytest fixture ensures reset
14. Tool re-run idempotent
15. Detection disabled by feature flag → zero overhead

### Anti-patterns
- DO NOT enable detection in production by default
- DO NOT patch SQLAlchemy core (use events)
- DO NOT persist query logs to DB (too expensive)
- DO NOT let detection modify query behavior
- DO NOT use global counter (must be per-request)
