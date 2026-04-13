## Tool: `dependency_audit`

### Overview parameters
- Tool name: `fastapi_dependency_audit`
- Category: VERIFY
- Complexity: Medium
- Dependencies: existing FastAPI project (pip/poetry/uv), pip-audit, deptry
- Signature: `dependency_audit(project_dir: str, fail_on_cve: bool = True, fail_on_unused: bool = False, check_licenses: bool = True, allowed_licenses: list[str] | None = None) -> dict`
- Parameters:
  - `project_dir`: project root path
  - `fail_on_cve`: fail if any known CVE found
  - `fail_on_unused`: fail if any dependency is imported but unused (strict mode)
  - `check_licenses`: verify all deps use approved licenses
  - `allowed_licenses`: list of OSI-approved licenses (default: MIT, BSD, Apache-2.0, MPL-2.0)

### Purpose
Audit the project's dependencies for three classes of issues: (1) known vulnerabilities via **pip-audit** against the PyPI Advisory Database, (2) unused/missing imports via **deptry** (catches "I added this dep but forgot to use it" and vice versa), and (3) license compliance (reject GPL/AGPL if project is proprietary). Generates a report with severity, fix suggestion (upgrade path), and CI gate. Essential for supply-chain security and license hygiene.

### Performance SLOs
- Tool execution time < 4s (config only)
- Files modified ≤ 2
- Files created ≥ 5 (audit config, allowed licenses, CI workflow, report template, tests)
- Actual audit run < 30s for 100 deps
- Report format: JSON + HTML
- Zero production overhead

### Key technical decisions
1. **pip-audit:** scans against PyPI Advisory DB, runs per lockfile
2. **deptry:** scans imports vs. declared dependencies
3. **License check:** uses `pip-licenses` or parses package metadata
4. **Allowed list:** default MIT/BSD/Apache-2.0/MPL-2.0; configurable
5. **Fix suggestions:** pip-audit outputs minimum safe version
6. **CI integration:** GitHub Actions with artifact upload
7. **Tool compatibility:** detects pip, poetry, uv, pdm — runs appropriate command
8. **Suppression:** `.audit-ignore` file for acknowledged risks with justification
9. **Severity:** CRITICAL/HIGH/MEDIUM/LOW mapped from CVSS
10. **Transitive deps:** included in scan

### Key invariants
1. Every CVE finding ALWAYS includes a fix version.
2. Unused deps NEVER fail by default (opt-in strict mode).
3. License check ALWAYS runs against the allowed list.
4. Scan NEVER modifies the lockfile.
5. Suppressions are ALWAYS tracked with justification + expiry.
6. Report includes ALL findings even when no fail gates triggered.

### User story themes
- 9.1 CVE detection (US-01..05): find known CVE, fix version suggested, suppress with justification
- 9.2 Unused deps (US-06..10): deptry finds unused, missing import, strict mode
- 9.3 License (US-11..15): GPL rejected, Apache-2.0 allowed, unknown license flagged
- 9.4 CI integration (US-16..20): GH Actions, report upload, PR comment
- 9.5 Multiple package managers (US-21..25): pip, poetry, uv, tool idempotency

### Test plan categories
- 10.1 CVE (T-01..06): known CVE detected, severity, fix suggestion
- 10.2 Unused (T-07..12): unused dep flagged, missing import
- 10.3 License (T-13..18): GPL rejected, allowlist, unknown
- 10.4 Suppression (T-19..24): justified, expired, CI gate bypass
- 10.5 Integration (T-25..30): pip, poetry, tool idempotency

### Edge cases (15)
1. Project with 0 deps → scan exits 0
2. Private PyPI mirror → configurable URL
3. Transitive dep CVE → fix path shows grandparent update
4. License unknown → flagged, not failed by default
5. Dep pinned to vulnerable version → fix suggests unpin + upgrade
6. pip-audit offline → fallback DB
7. Multiple lockfiles (pip + poetry) → tool errors, asks to pick one
8. Suppression expired → scan fails if CVE still present
9. Deptry finds test-only import misflagged → config excludes tests/
10. CI has no network → use cached DB
11. Tool re-run idempotent
12. License field missing from metadata → flagged unknown
13. Custom allowlist overrides default → honored
14. Vulnerability without fix version yet → reported + flagged
15. New dep added without scan → pre-commit hook catches

### Anti-patterns
- DO NOT suppress CVEs without justification + expiry
- DO NOT allow unknown licenses by default
- DO NOT skip transitive dep checking
- DO NOT hardcode allowed versions (use upper bounds)
- DO NOT run audit only in CI — run in pre-commit too
