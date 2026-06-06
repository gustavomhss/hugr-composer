## Tool: `security_scan`

### Overview parameters
- Tool name: `fastapi_security_scan`
- Category: VERIFY
- Complexity: High
- Dependencies: existing FastAPI project + bandit + semgrep + pip-audit
- Signature: `security_scan(project_dir: str, fail_on: Literal["high", "medium", "low"] = "high", checks: list[str] | None = None, exclude_paths: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `fail_on`: minimum severity that fails the build
  - `checks`: specific check families to run (None = all)
  - `exclude_paths`: paths to skip

### Purpose
Run static security analysis on the codebase to catch common vulnerabilities. Combines **bandit** (Python security linting), **semgrep** (pattern-based checks with FastAPI-specific rules), **pip-audit** (known CVEs in dependencies), and custom rules for project-specific patterns (hardcoded secrets, unsafe SQL construction, missing auth on routes). Produces a SARIF report compatible with GitHub Security tab and fails the build if any finding exceeds `fail_on` threshold. The tool generates config files for each scanner, a unified runner script, CI integration, and exclusion rules for false positives.

### Performance SLOs
- Tool execution time < 4s (install config, not the actual scan)
- Files modified ≤ 2
- Files created ≥ 8 (bandit config, semgrep rules, pip-audit config, unified runner, SARIF aggregator, exclusions, CI config, tests)
- Full scan runtime < 60s for 50K LOC codebase
- Report generation < 500 ms
- No runtime production overhead (scan-time only)

### Key technical decisions
1. **Tools:** bandit (Python AST), semgrep (pattern matching), pip-audit (CVE check)
2. **Custom rules:** FastAPI-specific semgrep rules (missing Depends on sensitive routes, hardcoded JWT secret, raw SQL in raw string)
3. **Output format:** SARIF (standard) + JSON + HTML for human readers
4. **Severity levels:** low, medium, high, critical
5. **Exclusions:** file-level via `.bandit` + `.semgrepignore`, rule-level via comments
6. **CI integration:** GitHub Actions workflow that uploads SARIF to Security tab
7. **Fail gates:** `fail_on=high` means any high or critical finding fails
8. **False positive suppression:** inline comments `# nosec`, `# semgrep: ignore`
9. **Custom rules directory:** `.semgrep/fastapi/*.yml` for project-specific patterns
10. **Dependency scan:** pip-audit runs against requirements.txt/pyproject.toml

### Key invariants
1. Scan NEVER modifies source code.
2. All findings are PERSISTED in SARIF regardless of fail threshold.
3. Exclusions are ALWAYS explicit (comment or config).
4. Scan exits non-zero if any finding >= fail_on severity.
5. Reports include finding location (file:line), severity, rule ID, and fix suggestion.
6. pip-audit ALWAYS checks current lockfile, not freeze.
7. Custom rules are VERSIONED in repo.

### User story themes
- 9.1 Basic scan (US-01..05): find hardcoded secret, SQL injection, eval, unsafe yaml
- 9.2 Fail gates (US-06..10): fail_on=high blocks, medium warns, low ignored
- 9.3 Exclusions (US-11..15): file exclusion, inline suppression, rule disable
- 9.4 CI integration (US-16..20): SARIF upload, GitHub Security tab, PR comment
- 9.5 Custom rules (US-21..25): FastAPI-specific, false positive, tool idempotency

### Test plan categories
- 10.1 Detection (T-01..06): bandit finds eval, semgrep finds hardcoded jwt
- 10.2 Custom rules (T-07..12): missing Depends on /admin, raw SQL
- 10.3 Exclusions (T-13..18): file excluded, inline nosec, rule disabled
- 10.4 CI (T-19..24): exit code, SARIF format, PR annotation
- 10.5 Edge cases (T-25..30): empty project, no findings, tool idempotency

### Edge cases (15)
1. Project with 0 Python files → scan exits 0 (nothing to scan)
2. Semgrep not installed → tool warns and skips semgrep
3. pip-audit offline → fallback to vendored CVE DB
4. Finding inside generated code (alembic/versions/) → suppressed by exclude
5. Custom rule has syntax error → semgrep fails, tool reports rule bug
6. Finding severity not mapped to fail_on → uses default mapping
7. False positive flagged as # nosec → suppressed, still reported in full log
8. CI has no SARIF upload permission → report still generated locally
9. Dependency CVE not fixed yet → finding persists, admin tracks
10. Project uses poetry, not pip → pip-audit works on poetry.lock
11. Scan interrupted mid-run → partial report, exit code != 0
12. Multiple rules flag same line → deduplicated in report
13. Tool re-run idempotent
14. Findings in vendored third-party code → excluded via path
15. New rule added after baseline → baseline updated

### Anti-patterns
- DO NOT suppress findings without written justification
- DO NOT skip pip-audit (dependency CVEs are the #1 attack vector)
- DO NOT hardcode secrets to "fix" bandit
- DO NOT disable semgrep rules to pass CI (fix or explicitly suppress)
- DO NOT ignore low-severity findings in critical paths (auth, crypto)
