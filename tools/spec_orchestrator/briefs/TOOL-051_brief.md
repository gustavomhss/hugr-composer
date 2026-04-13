## Tool: `fastapi_doctor`

### Overview parameters
- Tool name: `fastapi_doctor`
- Category: PROACTIVE (the crown jewel — synthesizes all 50 other tools)
- Complexity: Very High
- Dependencies: all other SKILL-001 tools available + Git + Pydantic + SQLAlchemy introspection
- Signature: `fastapi_doctor(project_dir: str, mode: str = "full", emit_fix_plan: bool = True, include_extend: bool = True, fail_on_critical: bool = True, report_format: str = "markdown") -> dict`
- Parameters:
  - `project_dir`: project root
  - `mode`: `quick` (top 10 issues), `full` (all checks), `targeted` (specific category)
  - `emit_fix_plan`: generate an ordered fix plan referencing the specific tool to invoke for each issue
  - `include_extend`: also recommend EXTEND tools (feature gaps), not only issues
  - `fail_on_critical`: fail the gate if any CRITICAL finding exists
  - `report_format`: `markdown`, `html`, `json`, `pdf`

### Purpose
A holistic health check for a FastAPI project. Runs every VERIFY tool (security_scan, dep_audit, n+1 detector, schema_coverage, test_coverage_gaps, api_compliance, perf_baseline), audits architecture (layer violations, dead code, cycles), inspects operational readiness (SLAs, pool config, observability), and — critically — **suggests which EXTEND tools would improve the project** (e.g., "your auth uses only JWT, consider `add_mfa` and `add_rbac`"; "you have 30 models but no audit log, consider `add_audit_log`"). The output is a prioritized, executable fix plan that references exact tools from the SKILL-001 catalogue by number. This is the tool that turns SKILL-001 from a toolbox into a consultant: one command produces a Staff-Engineer-quality review of the project.

### Performance SLOs
- Tool execution time < 60s for full scan (50k LOC, 100 routes)
- Files modified ≤ 2 (pyproject.toml, CI workflow)
- Files created ≥ 12 (doctor engine, checker registry, severity rules, fix plan templates, CI workflow, report templates, tests, docs, recommendations catalog, config, Makefile, example reports)
- Quick mode < 10s
- Report rendering < 5s
- Zero runtime impact on the target app

### Key technical decisions
1. **Orchestration:** invokes other SKILL-001 tools programmatically, aggregates results
2. **Severity levels:** CRITICAL (security, data loss risk), HIGH (performance, reliability), MEDIUM (quality, tech debt), LOW (nitpicks)
3. **Fix plan:** ordered list where each item references a specific tool: "RUN: `security_scan` → fixes: 3 CRITICAL"
4. **EXTEND recommendations:** pattern matches on model/route shape to suggest missing features
5. **Baseline comparison:** compares against a committed `.fastapi_doctor.baseline.json` so only new issues fail
6. **Report format:** Markdown (default), HTML for dashboards, JSON for programs, PDF for executives
7. **Custom rules:** user can disable/enable specific checks via `.fastapi_doctor.yaml`
8. **Quick mode:** top 10 highest-severity findings only
9. **Targeted mode:** `--only=security` runs just security checks
10. **CI integration:** runs on every PR, posts Markdown summary, blocks on CRITICAL delta

### Key invariants
1. All findings ALWAYS carry a severity level.
2. Every finding ALWAYS includes a tool reference ("fix via `tool_name`").
3. Fix plan is ALWAYS ordered by severity, then dependency.
4. EXTEND recommendations NEVER duplicate existing features (detected via code scan).
5. Report is DETERMINISTIC (same project state → same report).
6. Baseline comparison is ALWAYS relative (new findings only).
7. Quick mode NEVER misses CRITICAL findings.

### User story themes
- 9.1 Full scan (US-01..05): clean project, dirty project, CRITICAL found, HIGH found, MEDIUM/LOW
- 9.2 Fix plan (US-06..10): ordered by severity, tool refs, multi-tool chain, partial apply
- 9.3 EXTEND recommendations (US-11..15): missing audit, missing RBAC, missing MFA, missing cache, missing tests
- 9.4 Modes (US-16..20): quick, full, targeted, baseline delta, CI
- 9.5 Edge cases (US-21..25): empty project, tool idempotency, custom config, PDF render

### Test plan categories
- 10.1 Orchestration (T-01..06): run each checker, aggregate, dedup
- 10.2 Severity (T-07..12): CRITICAL, HIGH, MEDIUM, LOW, sort, filter
- 10.3 Fix plan (T-13..18): order, tool ref, chain, partial
- 10.4 Recommendations (T-19..24): missing features detected, not duplicated
- 10.5 Edge cases (T-25..30): baseline, quick, tool idempotency

### Edge cases (15)
1. Empty project → no findings, recommends bootstrap tools
2. Perfect project → passes clean with no findings
3. New CRITICAL introduced in PR → fails gate via baseline delta
4. Same CRITICAL present in baseline → passes (no regression)
5. Fix plan has 50 items → grouped by tool invocation
6. EXTEND recommendation for `add_i18n` on a single-locale app → conditional on actual user demand hint
7. Custom config disables security checks → honored with warning
8. Quick mode → top 10 findings only
9. PDF render with no chart lib → falls back to HTML
10. Tool re-run idempotent
11. Multiple CRITICAL in same file → grouped
12. VERIFY tool missing dependency → skipped with warning
13. Project with 1000 routes → still < 60s
14. Report > 100 pages → chunked
15. Baseline corrupted → error with `--reset-baseline` hint

### Anti-patterns
- DO NOT re-implement checks that existing tools already do (delegate)
- DO NOT list findings without a fix path (actionable only)
- DO NOT recommend features the project already has
- DO NOT fail on pre-existing issues (only regressions)
- DO NOT produce reports without severity levels
