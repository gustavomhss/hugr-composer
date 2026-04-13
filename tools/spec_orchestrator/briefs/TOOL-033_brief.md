## Tool: `api_spec_compliance`

### Overview parameters
- Tool name: `fastapi_api_spec_compliance`
- Category: VERIFY
- Complexity: Medium
- Dependencies: existing FastAPI project, optional committed `openapi.json` snapshot
- Signature: `api_spec_compliance(project_dir: str, spec_file: str = "openapi.json", fail_on_breaking: bool = True, fail_on_undocumented: bool = True, allow_additions: bool = True) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `spec_file`: path to the committed OpenAPI snapshot
  - `fail_on_breaking`: fail if breaking changes detected (removed endpoints, required params added, type narrowed)
  - `fail_on_undocumented`: fail if any route lacks `summary`, `description`, or `response_model`
  - `allow_additions`: non-breaking additions (new endpoints/optional params) pass

### Purpose
Generate the current OpenAPI schema from the live FastAPI app, diff it against the committed snapshot, and classify every change as `BREAKING`, `NON_BREAKING`, or `METADATA`. Enforces that every route has complete documentation (summary, description, response_model, tags) and that no endpoint silently disappears or changes its contract. Catches the "we renamed a field and forgot to bump the version" class of bugs before they reach consumers. Uses the openapi-diff algorithm from stoplight/spectral-like rules.

### Performance SLOs
- Tool execution time < 2s (schema gen + diff for 100 routes)
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 6 (spec snapshot, diff rules, CI workflow, report template, tests, Makefile targets)
- Diff computation < 500 ms for 200-route API
- Report generation < 200 ms
- Zero runtime impact

### Key technical decisions
1. **Snapshot strategy:** `openapi.json` committed to repo, regenerated via `--update-snapshot`
2. **Breaking change classification:** removed route, removed response field, added required request field, type narrowed, enum value removed
3. **Non-breaking:** new route, added response field, added optional request field, enum value added
4. **Metadata:** tag change, description edit, summary edit
5. **Documentation gate:** every route must have `summary`, `description` >= 20 chars, `response_model`, at least one `tag`
6. **Diff library:** reuse `openapi-diff-python` or implement minimal diff
7. **Report format:** JSON + Markdown + GitHub annotation
8. **CI integration:** runs on every PR, posts diff summary, blocks merge on breaking
9. **Semver suggestion:** tool outputs recommended version bump (major/minor/patch)
10. **Schema normalization:** sort keys, strip server URLs, ignore operation IDs auto-generated

### Key invariants
1. Snapshot is NEVER updated without `--update-snapshot` flag.
2. Breaking changes ALWAYS fail when `fail_on_breaking=True`.
3. Every route ALWAYS checked for documentation completeness.
4. Diff is DETERMINISTIC (schema normalized before comparison).
5. Version bump suggestion is ALWAYS aligned with semver.
6. Report includes ALL changes, not only blocking ones.
7. Snapshot diff NEVER mutates the live app schema.

### User story themes
- 9.1 Breaking detection (US-01..05): removed route, removed field, type narrowed, required added, enum removed
- 9.2 Non-breaking (US-06..10): new route passes, new optional param passes, new response field passes
- 9.3 Documentation gate (US-11..15): missing summary fails, short description fails, missing tag fails, missing response_model fails
- 9.4 CI integration (US-16..20): PR comment with diff, blocks on breaking, semver suggestion, artifact upload
- 9.5 Edge cases (US-21..25): first run creates snapshot, normalization, tool idempotency, partial matches

### Test plan categories
- 10.1 Diff algorithm (T-01..06): removed, added, changed, type narrowing, enum shifts, required toggle
- 10.2 Doc gate (T-07..12): summary, description, response_model, tags, short strings
- 10.3 Snapshot lifecycle (T-13..18): create, update (explicit), no-op update, normalization
- 10.4 CI (T-19..24): exit codes, Markdown output, semver bump
- 10.5 Edge cases (T-25..30): empty app, 500 routes, tool idempotency

### Edge cases (15)
1. First run with no snapshot → creates snapshot, passes
2. Snapshot corrupted → clear error, suggests `--reset-snapshot`
3. Route renamed → detected as remove+add (breaking)
4. Path parameter renamed → breaking (consumers break)
5. Response field renamed → breaking
6. Optional field made required → breaking
7. Required field made optional → non-breaking (consumers still work)
8. Enum value added → non-breaking (unless strict consumers)
9. Enum value removed → breaking
10. Tag renamed → metadata only
11. Operation ID auto-generated → ignored (noise)
12. Server URL changed → ignored
13. Schema uses `oneOf`/`anyOf` → handled via structural comparison
14. 500 routes → still < 2s diff
15. Route added AND route removed same PR → both reported, breaking wins

### Anti-patterns
- DO NOT diff without normalizing (order, whitespace, server URLs)
- DO NOT allow silent snapshot updates
- DO NOT treat all changes as breaking (too noisy)
- DO NOT skip doc gate (undocumented routes become tech debt)
- DO NOT hardcode snapshot path (make configurable)
