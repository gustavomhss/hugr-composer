## Tool: `add_contract_tests`

### Overview parameters
- Tool name: `fastapi_add_contract_tests`
- Category: EXTEND > Testing
- Complexity: High
- Dependencies: existing FastAPI project with OpenAPI + pytest + schemathesis
- Signature: `add_contract_tests(project_dir: str, openapi_path: str = "/openapi.json", max_examples: int = 100, stateful: bool = False, exclude_endpoints: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `openapi_path`: where the API's OpenAPI spec is served
  - `max_examples`: max hypothesis examples generated per endpoint
  - `stateful`: enable stateful testing (state machine that chains calls)
  - `exclude_endpoints`: list of paths to skip (e.g. destructive endpoints)

### Purpose
Generate property-based contract tests using **schemathesis** that automatically validate every endpoint against its OpenAPI schema. For each endpoint, schemathesis generates hundreds of realistic requests (valid and invalid), sends them, and asserts that responses match the declared schema (status codes, response body types, required fields). Catches common bugs: endpoints that return undocumented fields, incorrect status codes, broken serialization, missing error handling. Also supports stateful testing: a state machine that chains calls (create → get → update → delete) to find issues that only appear in sequences. Integrates with existing pytest setup and runs alongside unit tests.

### Performance SLOs
- Tool execution time < 3s
- Files modified ≤ 3
- Files created ≥ 5 (schemathesis config, conftest hooks, test file, CI integration, exclude list)
- Single endpoint contract run < 5s (for max_examples=100)
- Full suite run < 60s for 50 endpoints
- Stateful run < 5 min for typical API
- Zero new production dependencies (pytest-only)

### Key technical decisions
1. **Library:** schemathesis (actively maintained, pytest integration, hypothesis-based)
2. **Pytest integration:** `schemathesis.from_path("/openapi.json")` creates a test function per endpoint
3. **Validation strategy:** `response.status_code in schema` + `body matches schema`
4. **Exclusion:** some endpoints are destructive (DELETE /all) and should be excluded via param
5. **Stateful mode:** generates state machines that chain endpoints (create user → login → access protected)
6. **Auth fixtures:** conftest provides authenticated client (JWT + API key) — schemathesis uses it automatically
7. **CI integration:** example GitHub Actions workflow with schemathesis report upload
8. **Hypothesis settings:** max_examples tunable per endpoint via `@schemathesis.override`
9. **Known failures:** `@schemathesis.skip` annotation for endpoints with known contract bugs
10. **Custom checks:** ability to add project-specific checks (e.g. response has `correlation_id` header)

### Key invariants
1. Contract tests ALWAYS run in CI on every PR.
2. A PR that breaks the schema without updating it is ALWAYS rejected by contract tests.
3. Excluded endpoints are ALWAYS listed explicitly — NEVER silently skipped.
4. Stateful tests NEVER corrupt the production DB (must run against test fixture).
5. Contract tests NEVER modify application source (tests-only).
6. Every endpoint in openapi.json is covered UNLESS explicitly excluded.
7. Failures are reproducible via hypothesis seed (printed on failure).

### User story themes
- 9.1 Basic contract (US-01..05): schema test per endpoint, status codes, body shape
- 9.2 Stateful testing (US-06..10): chain create→get, login flow, pagination chain
- 9.3 Exclusion (US-11..15): skip destructive, skip known broken, custom checks
- 9.4 CI integration (US-16..20): GitHub Actions, report upload, hypothesis seed
- 9.5 Maintenance (US-21..25): update after schema change, handle flaky tests, tool idempotency

### Test plan categories
- 10.1 Contract generation (T-01..06): test per endpoint, config loaded, exclude respected
- 10.2 Validation (T-07..12): status code match, body shape, undocumented field fails
- 10.3 Stateful (T-13..18): chain execution, state machine, deadlock prevention
- 10.4 CI (T-19..24): GH Actions workflow, hypothesis seed reproducibility
- 10.5 Edge cases (T-25..30): flaky test, missing schema, tool idempotency

### Edge cases (15)
1. OpenAPI spec has no schemas → tool errors at install
2. Endpoint accepts file upload → schemathesis uses binary data strategy
3. Endpoint returns 500 for some input → failure captured with hypothesis seed
4. Endpoint response has undocumented field → contract test fails (this is the bug we want to catch)
5. Stateful test creates test data that lingers → teardown deletes at end of run
6. Authentication required → conftest fixture provides token automatically
7. Endpoint is slow (> 5s) → hypothesis deadline adjusted
8. Schema validation rejects valid request because schema is wrong → schema bug, not test bug
9. Hypothesis finds an edge case example not covered by our schema → we fix schema or add check
10. max_examples=100 is too slow for CI → per-endpoint override
11. Stateful state machine stuck in loop → hypothesis timeout aborts run
12. Endpoint returns 200 but body is empty → matches if schema allows
13. Tool re-run idempotent
14. Schema version changes → regenerate test set
15. New endpoint added without test → tool detects via CI diff and flags

### Anti-patterns
- DO NOT run stateful tests against production
- DO NOT skip failures without filing a bug
- DO NOT exclude endpoints silently (must be explicit in exclude_endpoints)
- DO NOT write manual contract tests instead of using schemathesis (property-based is superior)
- DO NOT ignore hypothesis seeds in CI output (they reproduce failures)
