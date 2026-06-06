## Tool: `test_coverage_gaps`

### Overview parameters
- Tool name: `fastapi_test_coverage_gaps`
- Category: VERIFY
- Complexity: Medium
- Dependencies: existing FastAPI project with pytest + coverage.py installed
- Signature: `test_coverage_gaps(project_dir: str, min_line_pct: float = 85.0, min_branch_pct: float = 75.0, fail_on_regressions: bool = True, baseline_file: str = ".coverage.baseline.json") -> dict`
- Parameters:
  - `project_dir`: project root path
  - `min_line_pct`: minimum line coverage threshold
  - `min_branch_pct`: minimum branch coverage threshold
  - `fail_on_regressions`: fail if coverage drops vs baseline
  - `baseline_file`: where to persist the last known-good snapshot

### Purpose
Run the pytest suite with branch coverage enabled, parse the `coverage.xml` output, and produce a prioritized list of files/functions with uncovered branches. Goes beyond the raw percentage — ranks gaps by risk (files touching auth, money, DB writes rank higher than pure getters). Compares against a committed baseline so regressions fail the gate even if the absolute percentage is still above threshold. Designed to answer "which untested lines should I actually care about?" rather than "did we hit 85%?".

### Performance SLOs
- Tool execution time < 3s (excluding pytest run)
- Files modified ≤ 2 (pyproject.toml, .gitignore)
- Files created ≥ 7 (coverage config, risk weights, CI workflow, baseline, report template, tests, Makefile targets)
- Report generation < 500 ms for 5k lines
- Zero runtime impact on application code
- Baseline diff computation < 100 ms

### Key technical decisions
1. **Branch coverage** always on (`--cov-branch`) — line coverage alone hides `if/else` gaps
2. **Risk weighting:** files matching `auth`, `payment`, `admin`, `write`, `delete` get 2x weight
3. **Baseline:** JSON snapshot committed to repo, updated on explicit approval only
4. **Regression detection:** any file whose coverage dropped > 2% vs baseline flagged
5. **Gap ranking:** `risk_weight * uncovered_branches` descending
6. **Exclusions:** `__init__.py`, generated code, migrations — via `coverage:exclude` comments
7. **Report:** JSON + Markdown table + GitHub-annotation output for PR comments
8. **CI integration:** fails PR if gaps introduced, posts inline review comments on uncovered lines
9. **Incremental mode:** `--changed-only` analyzes only files touched in current diff
10. **Per-module thresholds:** `[tool.coverage_gaps.thresholds]` overrides for strict modules

### Key invariants
1. Branch coverage is ALWAYS computed, never line-only.
2. Risk-weighted ranking is DETERMINISTIC (sorted by weight desc, then path asc).
3. Baseline file is NEVER modified silently — requires `--update-baseline` flag.
4. Regressions ALWAYS fail the gate when `fail_on_regressions=True`.
5. Excluded lines NEVER count toward either numerator or denominator.
6. Report is REPRODUCIBLE (same tests + same code → identical output).
7. Thresholds NEVER apply to excluded files.

### User story themes
- 9.1 Basic coverage (US-01..05): run, pass 85%, fail 84%, branch gap detected, report generated
- 9.2 Risk ranking (US-06..10): auth file weighted 2x, admin route prioritized, money file at top
- 9.3 Baseline regressions (US-11..15): regression caught, baseline update requires flag, diff report
- 9.4 CI integration (US-16..20): PR annotations, fail PR, Markdown summary, artifact upload
- 9.5 Edge cases (US-21..25): generated code excluded, incremental mode, module thresholds, tool idempotency

### Test plan categories
- 10.1 Branch coverage calc (T-01..06): 85/100 branches, missing else, exception paths
- 10.2 Risk weighting (T-07..12): auth 2x, weight stable, tie-breaker
- 10.3 Baseline (T-13..18): regression fails, update-baseline works, first run creates
- 10.4 CI (T-19..24): annotations, Markdown, incremental mode
- 10.5 Edge cases (T-25..30): excluded files, idempotency, per-module thresholds

### Edge cases (15)
1. First run with no baseline → creates baseline, passes
2. Baseline corrupted → tool errors with clear message, suggests `--reset-baseline`
3. Coverage at exactly 85.0% → passes (inclusive threshold)
4. File deleted between runs → drops from baseline on update
5. New file with 0% coverage → fails even if overall % still above threshold
6. Test file itself has 0% coverage → excluded from stats
7. Conditional import (`try: import X`) → branches counted correctly
8. `# pragma: no cover` → respected
9. 100% line coverage but 60% branch → flagged
10. Tool run twice with no changes → identical output, zero churn
11. Risk weight customized to 5x for specific file → honored
12. File with 0 branches → 100% coverage (vacuously true)
13. PR touches 1 file → `--changed-only` returns only that file
14. Generated code in `build/` → excluded via config
15. Migrations auto-excluded by directory pattern

### Anti-patterns
- DO NOT report only overall percentage — gaps are the value
- DO NOT allow silent baseline updates (explicit flag required)
- DO NOT skip branch coverage (line-only hides `if/else`)
- DO NOT weight all files equally (risk matters)
- DO NOT exclude files implicitly — require explicit exclusion
