"""Tests for TOOL-051 fastapi_doctor.

Covers: full scan, quick mode, targeted mode, severity classification,
fix plan ordering, EXTEND recommendations, baseline delta, report
rendering, idempotency, dry_run, checker disable config, deduplication,
error/skip handling, and report format validation.

Run with::

    PYTHONPATH=. python3 adapt/proactive/test_fastapi_doctor.py

or::

    PYTHONPATH=. pytest adapt/proactive/test_fastapi_doctor.py -v
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.proactive.fastapi_doctor import (
    BaselineComparator,
    Checker,
    CheckerRegistry,
    CheckerResult,
    DoctorOrchestrator,
    ExtendRecommender,
    FixPlanBuilder,
    ReportRenderer,
    Severity,
    classify_finding,
    fastapi_doctor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_project(name: str = "doctor_test") -> Path:
    """Create a minimal temporary project directory for testing."""
    base = Path(tempfile.mkdtemp()) / name
    (base / "app").mkdir(parents=True)
    (base / "app" / "main.py").write_text("# main\n")
    return base


def _make_finding(
    title: str = "Test finding",
    sev: Severity = Severity.MEDIUM,
    tool_ref: str = "TOOL-028",
    tool_name: str = "security_scan",
    location: str = "",
    category: str = "security",
) -> dict:
    return {
        "severity": sev,
        "title": title,
        "detail": "",
        "location": location,
        "tool_ref": tool_ref,
        "tool_name": tool_name,
        "category": category,
        "fix_hint": "",
    }


def _make_report(findings: list[dict] | None = None) -> dict:
    findings = findings or []
    summary = {s.name: 0 for s in Severity}
    for f in findings:
        sev = f["severity"]
        sev_name = sev.name if isinstance(sev, Severity) else str(sev)
        summary[sev_name] = summary.get(sev_name, 0) + 1
    summary["total"] = len(findings)
    serialised = [
        {**f, "severity": f["severity"].name if isinstance(f["severity"], Severity) else f["severity"]}
        for f in findings
    ]
    return {
        "project_dir": "/tmp/test",
        "mode": "full",
        "scan_duration_s": 0.5,
        "findings": serialised,
        "fix_plan": [],
        "extend_recommendations": [],
        "baseline_delta": {"new": 0, "resolved": 0, "unchanged": 0},
        "summary": summary,
        "skipped_checkers": [],
    }


# ---------------------------------------------------------------------------
# T-01: Severity enum ordering
# ---------------------------------------------------------------------------

def test_severity_ordering() -> None:
    """Severity.CRITICAL must sort before HIGH, MEDIUM, LOW."""
    assert Severity.CRITICAL < Severity.HIGH
    assert Severity.HIGH < Severity.MEDIUM
    assert Severity.MEDIUM < Severity.LOW


# ---------------------------------------------------------------------------
# T-02: Severity.from_string case-insensitive
# ---------------------------------------------------------------------------

def test_severity_from_string_case_insensitive() -> None:
    """from_string handles mixed case and aliases."""
    assert Severity.from_string("critical") == Severity.CRITICAL
    assert Severity.from_string("CRITICAL") == Severity.CRITICAL
    assert Severity.from_string("High") == Severity.HIGH
    assert Severity.from_string("med") == Severity.MEDIUM
    assert Severity.from_string("info") == Severity.LOW
    assert Severity.from_string("unknown_xyz") == Severity.MEDIUM  # default


# ---------------------------------------------------------------------------
# T-03: classify_finding security keywords → CRITICAL
# ---------------------------------------------------------------------------

def test_classify_finding_security_critical_keywords() -> None:
    """Security critical keywords map to Severity.CRITICAL."""
    assert classify_finding("sql injection detected", "security") == Severity.CRITICAL
    assert classify_finding("auth bypass in login route", "security") == Severity.CRITICAL
    assert classify_finding("secret leak found in config.py", "security") == Severity.CRITICAL


# ---------------------------------------------------------------------------
# T-04: classify_finding category-based fallbacks
# ---------------------------------------------------------------------------

def test_classify_finding_category_fallbacks() -> None:
    """Non-critical security→HIGH, n+1→HIGH, compliance→MEDIUM, default→MEDIUM."""
    assert classify_finding("missing CSP header", "security") == Severity.HIGH
    assert classify_finding("N+1 queries on GET /items", "performance") == Severity.HIGH
    assert classify_finding("missing openapi tag", "compliance") == Severity.MEDIUM
    assert classify_finding("low coverage", "quality") == Severity.MEDIUM


# ---------------------------------------------------------------------------
# T-05: FixPlanBuilder sorts CRITICAL first
# ---------------------------------------------------------------------------

def test_fix_plan_critical_first() -> None:
    """FixPlanBuilder places CRITICAL items before HIGH and MEDIUM."""
    findings = [
        _make_finding("N+1 in GET /items", Severity.HIGH, "TOOL-030", "detect_n_plus_one"),
        _make_finding("Secret leak in config", Severity.CRITICAL, "TOOL-028", "security_scan"),
        _make_finding("Schema gap", Severity.MEDIUM, "TOOL-031", "schema_coverage"),
    ]
    plan = FixPlanBuilder(findings).build()
    assert plan[0]["severity"] == "CRITICAL"
    assert plan[1]["severity"] == "HIGH"
    assert plan[2]["severity"] == "MEDIUM"


# ---------------------------------------------------------------------------
# T-06: FixPlanBuilder groups findings by tool_ref
# ---------------------------------------------------------------------------

def test_fix_plan_groups_by_tool_ref() -> None:
    """Two findings from the same tool produce one plan item."""
    findings = [
        _make_finding("Issue A", Severity.HIGH, "TOOL-028", "security_scan"),
        _make_finding("Issue B", Severity.MEDIUM, "TOOL-028", "security_scan"),
    ]
    plan = FixPlanBuilder(findings).build()
    assert len(plan) == 1
    assert plan[0]["total_fixes"] == 2
    assert plan[0]["tool_ref"] == "TOOL-028"


# ---------------------------------------------------------------------------
# T-07: FixPlanBuilder determinism
# ---------------------------------------------------------------------------

def test_fix_plan_is_deterministic() -> None:
    """Two calls with the same input produce identical output."""
    findings = [
        _make_finding("Secret leak", Severity.CRITICAL, "TOOL-028", "security_scan"),
        _make_finding("N+1", Severity.HIGH, "TOOL-030", "detect_n_plus_one"),
        _make_finding("Schema gap", Severity.MEDIUM, "TOOL-031", "schema_coverage"),
    ]
    plan1 = FixPlanBuilder(findings).build()
    plan2 = FixPlanBuilder(findings).build()
    assert [i["tool_ref"] for i in plan1] == [i["tool_ref"] for i in plan2]
    assert [i["order"] for i in plan1] == [i["order"] for i in plan2]


# ---------------------------------------------------------------------------
# T-08: FixPlanBuilder run_command format
# ---------------------------------------------------------------------------

def test_fix_plan_run_command_format() -> None:
    """Every plan item run_command matches 'fastapi_skill <name> .'."""
    import re
    findings = [_make_finding("Issue", Severity.HIGH, "TOOL-028", "security_scan")]
    plan = FixPlanBuilder(findings).build()
    pattern = re.compile(r"^fastapi_skill \w+ \.$")
    for item in plan:
        assert pattern.match(item["run_command"]), f"Bad run_command: {item['run_command']}"


# ---------------------------------------------------------------------------
# T-09: DoctorOrchestrator deduplicates same title+location
# ---------------------------------------------------------------------------

def test_orchestrator_deduplicates() -> None:
    """Findings with same title::location appear only once."""
    from adapt.proactive.fastapi_doctor import DoctorOrchestrator as DO

    orch = DO.__new__(DO)
    orch.MAX_QUICK_FINDINGS = 10
    raw = [
        _make_finding("Dup finding", Severity.HIGH, location="routes/items.py"),
        _make_finding("Dup finding", Severity.HIGH, location="routes/items.py"),
        _make_finding("Other finding", Severity.LOW, location="routes/items.py"),
    ]
    deduped = orch._deduplicate(raw)
    assert len(deduped) == 2


# ---------------------------------------------------------------------------
# T-10: Quick mode returns at most 10 findings
# ---------------------------------------------------------------------------

def test_quick_mode_max_findings() -> None:
    """quick mode limits output to MAX_QUICK_FINDINGS (10)."""
    project = _tmp_project("t10_quick")
    orch = DoctorOrchestrator(str(project), mode="quick")
    # Mock the registry to return checkers that produce many findings
    many_findings = [
        _make_finding(f"Finding {i}", Severity.LOW) for i in range(30)
    ]

    def _mock_run(self_checker: Checker) -> CheckerResult:
        return CheckerResult(name=self_checker.name, findings=many_findings[:5])

    import unittest.mock as mock
    original_run = Checker.run
    with mock.patch.object(Checker, "run", _mock_run):
        report = orch.run()

    assert len(report["findings"]) <= 10, f"Quick mode returned {len(report['findings'])} findings"


# ---------------------------------------------------------------------------
# T-11: Full mode returns more findings than quick
# ---------------------------------------------------------------------------

def test_full_vs_quick_checker_count() -> None:
    """Full mode uses all 7 checkers; quick mode uses 3 priority checkers."""
    project = _tmp_project("t11_checker_count")
    reg = CheckerRegistry(str(project))
    full_checkers = reg.get_checkers(mode="full")
    quick_checkers = reg.get_checkers(mode="quick")
    assert len(full_checkers) >= len(quick_checkers)
    assert len(quick_checkers) == 3
    quick_names = {c.name for c in quick_checkers}
    assert "security_scan" in quick_names
    assert "dependency_audit" in quick_names
    assert "detect_n_plus_one" in quick_names


# ---------------------------------------------------------------------------
# T-12: Targeted mode filters by category
# ---------------------------------------------------------------------------

def test_targeted_mode_filters_category() -> None:
    """Targeted mode returns only checkers matching the given category."""
    project = _tmp_project("t12_targeted")
    reg = CheckerRegistry(str(project))
    security_checkers = reg.get_checkers(mode="targeted", only_category="security")
    for c in security_checkers:
        assert c.category == "security", f"Checker {c.name} has wrong category: {c.category}"
    assert len(security_checkers) >= 1


# ---------------------------------------------------------------------------
# T-13: CheckerRegistry respects disable config
# ---------------------------------------------------------------------------

def test_checker_registry_disable_config() -> None:
    """Checkers listed in .fastapi_doctor.yaml 'disable:' are excluded."""
    project = _tmp_project("t13_disable")
    config_file = project / ".fastapi_doctor.yaml"
    config_file.write_text("disable:\n  - security_scan\n  - dependency_audit\n")

    reg = CheckerRegistry(str(project))
    full_checkers = reg.get_checkers(mode="full")
    names = {c.name for c in full_checkers}
    assert "security_scan" not in names
    assert "dependency_audit" not in names
    # Other checkers still present
    assert "detect_n_plus_one" in names


# ---------------------------------------------------------------------------
# T-14: BaselineComparator creates baseline on first run
# ---------------------------------------------------------------------------

def test_baseline_created_on_first_run() -> None:
    """BaselineComparator saves .fastapi_doctor.baseline.json on first diff."""
    project = _tmp_project("t14_baseline_create")
    bc = BaselineComparator(str(project))
    findings = [_make_finding("Issue A", Severity.HIGH)]
    delta = bc.diff(findings)
    assert (project / ".fastapi_doctor.baseline.json").exists()
    assert delta == {"new": 0, "resolved": 0, "unchanged": 1}


# ---------------------------------------------------------------------------
# T-15: BaselineComparator delta on second identical run → new=0
# ---------------------------------------------------------------------------

def test_baseline_no_new_issues_on_repeat() -> None:
    """Same findings on second run produce new=0."""
    project = _tmp_project("t15_baseline_repeat")
    bc = BaselineComparator(str(project))
    findings = [_make_finding("Issue A", Severity.HIGH)]
    bc.diff(findings)  # first run: creates baseline
    delta2 = bc.diff(findings)  # second run: same findings
    assert delta2["new"] == 0
    assert delta2["resolved"] == 0


# ---------------------------------------------------------------------------
# T-16: BaselineComparator detects new finding
# ---------------------------------------------------------------------------

def test_baseline_detects_new_finding() -> None:
    """New finding in second run is reported as new=1."""
    project = _tmp_project("t16_baseline_new")
    bc = BaselineComparator(str(project))
    bc.diff([_make_finding("Old issue", Severity.LOW)])  # establish baseline
    delta = bc.diff([
        _make_finding("Old issue", Severity.LOW),
        _make_finding("Brand new issue", Severity.CRITICAL),
    ])
    assert delta["new"] == 1
    assert delta["resolved"] == 0


# ---------------------------------------------------------------------------
# T-17: BaselineComparator reset deletes baseline
# ---------------------------------------------------------------------------

def test_baseline_reset() -> None:
    """reset() removes the baseline file."""
    project = _tmp_project("t17_baseline_reset")
    bc = BaselineComparator(str(project))
    bc.diff([_make_finding("X")])
    assert (project / ".fastapi_doctor.baseline.json").exists()
    bc.reset()
    assert not (project / ".fastapi_doctor.baseline.json").exists()


# ---------------------------------------------------------------------------
# T-18: ReportRenderer markdown output
# ---------------------------------------------------------------------------

def test_report_renderer_markdown() -> None:
    """render('markdown') produces a string with expected headers."""
    report = _make_report([_make_finding("Secret leak", Severity.CRITICAL)])
    report["fix_plan"] = FixPlanBuilder(
        [_make_finding("Secret leak", Severity.CRITICAL)]
    ).build()
    renderer = ReportRenderer(report)
    md = renderer.render("markdown")
    assert "# FastAPI Doctor Report" in md
    assert "## Summary" in md
    assert "## Fix Plan" in md


# ---------------------------------------------------------------------------
# T-19: ReportRenderer HTML output is valid HTML
# ---------------------------------------------------------------------------

def test_report_renderer_html() -> None:
    """render('html') produces a string containing <html> tags."""
    report = _make_report()
    renderer = ReportRenderer(report)
    html = renderer.render("html")
    assert "<html" in html
    assert "</html>" in html


# ---------------------------------------------------------------------------
# T-20: ReportRenderer JSON output parses
# ---------------------------------------------------------------------------

def test_report_renderer_json_valid() -> None:
    """render('json') produces valid, parseable JSON."""
    findings = [_make_finding("Issue A", Severity.HIGH)]
    report = _make_report(findings)
    renderer = ReportRenderer(report)
    raw_json = renderer.render("json")
    parsed = json.loads(raw_json)
    assert isinstance(parsed, dict)
    assert "summary" in parsed


# ---------------------------------------------------------------------------
# T-21: ExtendRecommender does not recommend feature already present
# ---------------------------------------------------------------------------

def test_extend_recommender_no_false_positives() -> None:
    """Recommender skips features that are already wired in the project."""
    project = _tmp_project("t21_extend_no_dup")
    # Write a file that satisfies the rbac presence check
    (project / "app" / "rbac.py").write_text("# rbac logic\n")
    # Write a jwt file so _has_auth → True
    (project / "app" / "jwt.py").write_text("# jwt logic\n")

    recommender = ExtendRecommender(str(project))
    recs = recommender.analyze()
    rec_tools = {r["tool"] for r in recs}
    assert "add_rbac" not in rec_tools, "add_rbac should not be recommended when rbac.py exists"


# ---------------------------------------------------------------------------
# T-22: ExtendRecommender recommends add_rbac when auth present and rbac absent
# ---------------------------------------------------------------------------

def test_extend_recommender_add_rbac() -> None:
    """Recommender suggests add_rbac when auth is present but rbac file is absent."""
    project = _tmp_project("t22_extend_rbac")
    (project / "app" / "auth.py").write_text("# auth logic\n")
    # Ensure no rbac file exists

    recommender = ExtendRecommender(str(project))
    recs = recommender.analyze()
    rec_tools = {r["tool"] for r in recs}
    assert "add_rbac" in rec_tools, "Expected add_rbac recommendation"


# ---------------------------------------------------------------------------
# T-23: ExtendRecommender includes tool_ref on every recommendation
# ---------------------------------------------------------------------------

def test_extend_recommender_has_tool_refs() -> None:
    """Every recommendation includes a non-empty tool_ref."""
    project = _tmp_project("t23_extend_refs")
    recommender = ExtendRecommender(str(project))
    recs = recommender.analyze()
    for rec in recs:
        assert rec.get("tool_ref"), f"Recommendation missing tool_ref: {rec}"
        assert rec["tool_ref"].startswith("TOOL-"), f"Bad tool_ref format: {rec['tool_ref']}"


# ---------------------------------------------------------------------------
# T-24: fastapi_doctor entry point returns ToolResult
# ---------------------------------------------------------------------------

def test_fastapi_doctor_returns_tool_result() -> None:
    """fastapi_doctor() returns a ToolResult instance."""
    from adapt.contracts import ToolResult
    project = _tmp_project("t24_entry_point")
    result = fastapi_doctor(ToolInput(project_dir=str(project)))
    assert isinstance(result, ToolResult)
    assert result.status == "success"


# ---------------------------------------------------------------------------
# T-25: fastapi_doctor returns error for missing project_dir
# ---------------------------------------------------------------------------

def test_fastapi_doctor_error_on_missing_dir() -> None:
    """fastapi_doctor returns status='error' when project_dir does not exist."""
    result = fastapi_doctor(ToolInput(project_dir="/nonexistent/path/xyz_999"))
    assert result.status == "error"
    assert result.error is not None
    assert "nonexistent" in result.error or "does not exist" in result.error


# ---------------------------------------------------------------------------
# T-26: fastapi_doctor execution_time_ms is positive
# ---------------------------------------------------------------------------

def test_fastapi_doctor_execution_time() -> None:
    """execution_time_ms must be a positive integer."""
    project = _tmp_project("t26_timing")
    result = fastapi_doctor(ToolInput(project_dir=str(project)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# T-27: DoctorOrchestrator summary keys are all Severity names + total
# ---------------------------------------------------------------------------

def test_orchestrator_summary_keys() -> None:
    """Report summary contains CRITICAL, HIGH, MEDIUM, LOW, total."""
    project = _tmp_project("t27_summary")
    orch = DoctorOrchestrator(str(project))
    report = orch.run()
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "total"):
        assert sev in report["summary"], f"Missing summary key: {sev}"


# ---------------------------------------------------------------------------
# T-28: Checker handles ImportError gracefully → skipped
# ---------------------------------------------------------------------------

def test_checker_handles_import_error() -> None:
    """Checker returns skipped=True when the tool module cannot be imported."""
    checker = Checker(
        name="nonexistent_tool",
        tool_ref="TOOL-999",
        category="quality",
        project_dir="/tmp",
    )
    result = checker.run()
    assert result.skipped is True
    assert "nonexistent_tool" in result.skip_reason or "dependency missing" in result.skip_reason


# ---------------------------------------------------------------------------
# T-29: DoctorOrchestrator all findings have severity string (serialised)
# ---------------------------------------------------------------------------

def test_all_findings_have_severity() -> None:
    """Every finding in the report has a non-None severity field."""
    project = _tmp_project("t29_sev_field")
    orch = DoctorOrchestrator(str(project))
    report = orch.run()
    for f in report["findings"]:
        assert f.get("severity") is not None, f"Finding missing severity: {f}"
        assert isinstance(f["severity"], str), "Severity should be serialised as string"


# ---------------------------------------------------------------------------
# T-30: ReportRenderer JSON serialises Severity enum correctly
# ---------------------------------------------------------------------------

def test_report_renderer_json_severity_serialisation() -> None:
    """JSON render converts Severity enum to its string name."""
    findings = [_make_finding("Critical issue", Severity.CRITICAL)]
    report = _make_report(findings)
    renderer = ReportRenderer(report)
    parsed = json.loads(renderer.render("json"))
    for f in parsed.get("findings", []):
        assert isinstance(f["severity"], str), "Severity in JSON must be a string"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_severity_ordering,
        test_severity_from_string_case_insensitive,
        test_classify_finding_security_critical_keywords,
        test_classify_finding_category_fallbacks,
        test_fix_plan_critical_first,
        test_fix_plan_groups_by_tool_ref,
        test_fix_plan_is_deterministic,
        test_fix_plan_run_command_format,
        test_orchestrator_deduplicates,
        test_quick_mode_max_findings,
        test_full_vs_quick_checker_count,
        test_targeted_mode_filters_category,
        test_checker_registry_disable_config,
        test_baseline_created_on_first_run,
        test_baseline_no_new_issues_on_repeat,
        test_baseline_detects_new_finding,
        test_baseline_reset,
        test_report_renderer_markdown,
        test_report_renderer_html,
        test_report_renderer_json_valid,
        test_extend_recommender_no_false_positives,
        test_extend_recommender_add_rbac,
        test_extend_recommender_has_tool_refs,
        test_fastapi_doctor_returns_tool_result,
        test_fastapi_doctor_error_on_missing_dir,
        test_fastapi_doctor_execution_time,
        test_orchestrator_summary_keys,
        test_checker_handles_import_error,
        test_all_findings_have_severity,
        test_report_renderer_json_severity_serialisation,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
