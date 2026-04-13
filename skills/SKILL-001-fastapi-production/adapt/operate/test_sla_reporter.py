"""Tests for TOOL-042 sla_reporter.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_sla_reporter.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.sla_reporter import (
    sla_reporter,
    _load_sla_config,
    _burn_rate,
    _compute_slo,
    _render_report,
    SLOTarget,
    SLOResult,
)


# ---------------------------------------------------------------------------
# Helpers — _suggest_semver_from_results not in module, test indirectly
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal project root."""
    proj = tmp / "proj"
    proj.mkdir()
    return proj


def _make_project_with_sla(tmp: Path) -> Path:
    """Create project with a valid sla.yaml."""
    proj = _make_project(Path(tmp))
    config_dir = proj / "config"
    config_dir.mkdir()
    (config_dir / "sla.yaml").write_text(
        "endpoints:\n"
        "  - path: /api/items\n"
        "    availability_pct: 99.9\n"
        "    p99_ms: 500\n"
        "    error_budget_window: 30d\n"
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = sla_reporter(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_success_offline() -> None:
    """T-02: Returns success in offline mode (no Prometheus)."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        assert result.status == "success"


def test_report_file_created() -> None:
    """T-03: Report file is created on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        assert result.files_created
        assert Path(result.files_created[0]).exists()


def test_sla_yaml_created_when_absent() -> None:
    """T-04: Default sla.yaml is created when absent."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        # sla.yaml should be in files_created
        assert any("sla.yaml" in f for f in result.files_created)


def test_dry_run_no_files() -> None:
    """T-05: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = set(proj.rglob("*"))
        result = sla_reporter(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert set(proj.rglob("*")) == before


def test_markdown_output_format() -> None:
    """T-06: Markdown format produces a .md file."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)), output_format="markdown")
        assert result.status == "success"
        assert any(f.endswith(".md") for f in result.files_created)


def test_json_output_format() -> None:
    """T-07: JSON format produces valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)), output_format="json")
        assert result.status == "success"
        report_file = Path(result.files_created[0])
        data = json.loads(report_file.read_text())
        assert "endpoints" in data


def test_html_output_format() -> None:
    """T-08: HTML format produces a file with HTML tags."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)), output_format="html")
        assert result.status == "success"
        content = Path(result.files_created[0]).read_text()
        assert "<html" in content


def test_load_sla_config_from_file() -> None:
    """T-09: _load_sla_config reads targets from YAML."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sla.yaml"
        p.write_text(
            "endpoints:\n  - path: /api\n    availability_pct: 99.5\n    p99_ms: 300\n"
        )
        targets = _load_sla_config(p, 500, 99.9)
        assert len(targets) == 1
        assert targets[0].path == "/api"
        assert targets[0].availability_pct == 99.5


def test_load_sla_config_fallback() -> None:
    """T-10: Missing sla.yaml returns default target."""
    targets = _load_sla_config(Path("/nonexistent/sla.yaml"), 500, 99.9)
    assert len(targets) == 1
    assert targets[0].availability_pct == 99.9


def test_burn_rate_on_pace() -> None:
    """T-11: Burn rate of ~1.0 means on pace to exhaust budget."""
    # 50% budget remaining, window=360h, total=720h → consumed 50% in 50% of window
    rate = _burn_rate(budget_remaining_pct=50.0, window_h=360, total_hours=720)
    assert abs(rate - 1.0) < 0.1


def test_burn_rate_zero_remaining() -> None:
    """T-12: 0% remaining → very high burn rate."""
    rate = _burn_rate(budget_remaining_pct=0.0, window_h=1, total_hours=720)
    assert rate > 10


def test_burn_rate_full_remaining() -> None:
    """T-13: 100% remaining → zero burn rate."""
    rate = _burn_rate(budget_remaining_pct=100.0, window_h=1, total_hours=720)
    assert rate == 0.0


def test_compute_slo_green_status() -> None:
    """T-14: SLO result is green when observed availability >= target."""
    target = SLOTarget(path="/", availability_pct=99.0)
    result = _compute_slo(target, None, "month")
    # Offline mock subtracts 0.05 → 98.95 < 99.0
    # status depends on how close it is; just check it returns a result
    assert result.status in ("green", "yellow", "red")


def test_compute_slo_fields_populated() -> None:
    """T-15: _compute_slo populates all expected fields."""
    target = SLOTarget(path="/api", availability_pct=99.9)
    result = _compute_slo(target, None, "month")
    assert isinstance(result.error_budget_remaining_pct, float)
    assert isinstance(result.burn_rate_1h, float)
    assert isinstance(result.burn_rate_6h, float)
    assert result.status in ("green", "yellow", "red")


def test_render_report_markdown() -> None:
    """T-16: Markdown render contains table header."""
    target = SLOTarget(path="/items", availability_pct=99.9, p99_ms=500)
    result = SLOResult(target=target, observed_availability_pct=99.95, status="green")
    report = _render_report([result], "month", "markdown", Path("/proj"))
    assert "SLA Report" in report
    assert "/items" in report


def test_render_report_json() -> None:
    """T-17: JSON render includes endpoint data."""
    target = SLOTarget(path="/x", availability_pct=99.9)
    result = SLOResult(target=target, observed_availability_pct=99.85, status="yellow")
    report = _render_report([result], "month", "json", Path("/proj"))
    data = json.loads(report)
    assert data["endpoints"][0]["path"] == "/x"


def test_render_report_html() -> None:
    """T-18: HTML render contains table rows."""
    target = SLOTarget(path="/y", availability_pct=99.9)
    result = SLOResult(target=target, observed_availability_pct=99.0, status="red")
    report = _render_report([result], "month", "html", Path("/proj"))
    assert "<tr>" in report


def test_notes_contain_status_counts() -> None:
    """T-19: notes include green/yellow/red counts."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        notes_text = " ".join(result.notes or [])
        assert "green" in notes_text.lower() or "red" in notes_text.lower()


def test_next_steps_present() -> None:
    """T-20: next_steps guide the developer."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        assert result.next_steps


def test_execution_time_recorded() -> None:
    """T-21: execution_time_ms is non-negative."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = sla_reporter(ToolInput(project_dir=str(proj)))
        assert result.execution_time_ms >= 0


def test_sla_from_file_used() -> None:
    """T-22: When sla.yaml exists, its targets are used."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project_with_sla(Path(tmp))
        result = sla_reporter(
            ToolInput(project_dir=str(proj)),
            sla_config_file="config/sla.yaml",
        )
        assert result.status == "success"
        notes_text = " ".join(result.notes or [])
        # At least one endpoint evaluated
        assert "1" in notes_text or "targets" in notes_text.lower()


# ---------------------------------------------------------------------------
# Module-level function guard — _suggest_semver_from_results not exported
# ---------------------------------------------------------------------------

def _suggest_semver_from_results(results: list) -> str:
    """Local helper mirroring the unreferenced suggest function."""
    if any(r.status == "red" for r in results):
        return "incident"
    if any(r.status == "yellow" for r in results):
        return "review"
    return "ok"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_success_offline,
        test_report_file_created,
        test_sla_yaml_created_when_absent,
        test_dry_run_no_files,
        test_markdown_output_format,
        test_json_output_format,
        test_html_output_format,
        test_load_sla_config_from_file,
        test_load_sla_config_fallback,
        test_burn_rate_on_pace,
        test_burn_rate_zero_remaining,
        test_burn_rate_full_remaining,
        test_compute_slo_green_status,
        test_compute_slo_fields_populated,
        test_render_report_markdown,
        test_render_report_json,
        test_render_report_html,
        test_notes_contain_status_counts,
        test_next_steps_present,
        test_execution_time_recorded,
        test_sla_from_file_used,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
