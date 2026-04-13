## Tool: `schema_coverage`

### Overview parameters
- Tool name: `fastapi_schema_coverage`
- Category: VERIFY
- Complexity: Medium
- Dependencies: existing FastAPI project with Pydantic schemas
- Signature: `schema_coverage(project_dir: str, threshold_pct: float = 80.0, fail_on_orphan_fields: bool = True, exclude_schemas: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `threshold_pct`: minimum schema coverage (fields tested / fields total)
  - `fail_on_orphan_fields`: fail if a schema has fields never tested
  - `exclude_schemas`: schemas to skip

### Purpose
Measure how much of the Pydantic schema surface is actually tested. Parses all `BaseModel` subclasses, lists their fields, and cross-references with test files to see which fields appear in assertions. Orphan fields (defined but never tested) are the main target — they usually indicate dead code or missing test coverage. Produces a report with per-schema coverage, orphan field list, and CI gate. Catches "we added a field but forgot to test it" and "this field was removed but tests still reference it".

### Performance SLOs
- Tool execution time < 3s
- Files modified ≤ 2
- Files created ≥ 5 (coverage module, AST parser, report template, CI gate, tests)
- Analysis time < 30s for 100 schemas
- Report generation < 500 ms
- No runtime impact

### Key technical decisions
1. **AST parsing:** walk `BaseModel` subclasses, collect field names
2. **Test parsing:** AST walk tests/ to find schema field references (`.field_name`)
3. **Coverage formula:** `tested_fields / total_fields` per schema
4. **Orphan detection:** fields never referenced in tests/
5. **Exclusion:** private fields (prefix `_`), computed properties
6. **Threshold gate:** fails if any schema below threshold
7. **Report:** table per schema with coverage percentage + orphan list
8. **CI integration:** GitHub Actions workflow
9. **Incremental mode:** only analyze changed schemas on PR
10. **Suggestions:** for each orphan, suggest test file where to add coverage

### Key invariants
1. Only public schemas counted (exclude `_private`).
2. Computed properties NEVER counted as fields.
3. Coverage ALWAYS between 0 and 1.
4. Orphan field list is DETERMINISTIC (sorted).
5. Exclusion list is EXPLICIT.
6. Report is REPRODUCIBLE (same source → same report).

### User story themes
- 9.1 Basic coverage (US-01..05): schema with 5 fields, 3 tested → 60%
- 9.2 Orphans (US-06..10): orphan detected, warning, fail mode
- 9.3 Threshold (US-11..15): pass/fail at 80%, per-schema enforcement
- 9.4 CI (US-16..20): GH Actions, PR comment, incremental
- 9.5 Edge cases (US-21..25): inherited schema, nested, tool idempotency

### Test plan categories
- 10.1 Coverage calc (T-01..06): 0/5, 3/5, 5/5 cases
- 10.2 Orphans (T-07..12): detect, fail gate, exclude
- 10.3 Threshold (T-13..18): pass 80, fail 79, per-schema
- 10.4 CI (T-19..24): exit code, report upload
- 10.5 Edge cases (T-25..30): inheritance, nested, tool idempotency

### Edge cases (15)
1. Schema with 0 fields → 100% coverage (vacuously true)
2. Schema inherits from parent → parent fields counted
3. Nested BaseModel field → both parent and nested counted
4. Field defined then removed → orphan in tests, tool flags
5. Field used via getattr() dynamically → not counted
6. Computed property → excluded
7. Private field `_token` → excluded
8. Schema only used in tests/conftest → not counted as orphan
9. Large schema (100 fields) → still fast
10. Tool re-run idempotent
11. Test file imports but doesn't use → not counted
12. Field renamed → old name becomes orphan
13. Threshold 0% → never fails
14. Threshold 100% → fails unless perfect
15. Pydantic v1 vs v2 → both supported

### Anti-patterns
- DO NOT count private fields
- DO NOT skip orphan detection (main value)
- DO NOT run only on master (should run on PR)
- DO NOT fail on dynamically accessed fields (false positive)
