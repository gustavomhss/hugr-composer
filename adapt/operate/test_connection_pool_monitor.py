"""Tests for TOOL-040 connection_pool_monitor.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_connection_pool_monitor.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.connection_pool_monitor import (
    _render_alerts,
    _render_dashboard,
    connection_pool_monitor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project structure."""
    proj = tmp / "proj"
    app = proj / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings): pass\nsettings = Settings()\n"
    )
    (app / "api" / "routes").mkdir(parents=True)
    (app / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "from app.core.logging import configure_logging\n"
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = connection_pool_monitor(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_success_creates_files() -> None:
    """T-02: Returns success and creates expected files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert result.status == "success"
        assert result.files_created


def test_monitor_file_created() -> None:
    """T-03: app/core/pool_monitor.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert (proj / "app" / "core" / "pool_monitor.py").exists()


def test_monitor_file_contains_pool_monitor_class() -> None:
    """T-04: pool_monitor.py contains PoolMonitor class."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "pool_monitor.py").read_text()
        assert "class PoolMonitor" in content


def test_health_route_created() -> None:
    """T-05: app/api/routes/pool_health.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert (proj / "app" / "api" / "routes" / "pool_health.py").exists()


def test_health_route_has_endpoint() -> None:
    """T-06: pool_health.py has /pool/health GET endpoint."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "api" / "routes" / "pool_health.py").read_text()
        assert "/pool/health" in content or "get_pool_health" in content


def test_grafana_dashboard_created() -> None:
    """T-07: Grafana dashboard JSON file is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        dashboard = proj / "infra" / "grafana" / "pool_dashboard.json"
        assert dashboard.exists()


def test_grafana_dashboard_valid_json() -> None:
    """T-08: Grafana dashboard is valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "infra" / "grafana" / "pool_dashboard.json").read_text()
        data = json.loads(content)
        assert "panels" in data


def test_alert_rules_created() -> None:
    """T-09: Prometheus alert rules YAML is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        alert = proj / "infra" / "prometheus" / "pool_alerts.yaml"
        assert alert.exists()


def test_alert_rules_contain_threshold() -> None:
    """T-10: Alert rules reference the configured threshold."""
    alerts = _render_alerts(80.0)
    assert "80" in alerts
    assert "warning" in alerts.lower()


def test_idempotent_returns_no_op() -> None:
    """T-11: Running twice returns no_op on second run."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        r1 = connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert r1.status == "success"
        r2 = connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert r2.status == "no_op"


def test_dry_run_no_files() -> None:
    """T-12: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = set(proj.rglob("*"))
        result = connection_pool_monitor(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert set(proj.rglob("*")) == before


def test_main_py_patched() -> None:
    """T-13: main.py is patched to import pool_monitor."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        main = (proj / "app" / "main.py").read_text()
        assert "pool_monitor" in main


def test_pool_size_in_monitor_file() -> None:
    """T-14: Configured pool_size appears in generated monitor."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)), pool_size=42)
        content = (proj / "app" / "core" / "pool_monitor.py").read_text()
        assert "42" in content


def test_render_dashboard_has_six_panels() -> None:
    """T-15: Grafana dashboard has 6 panels."""
    data = json.loads(_render_dashboard(80.0))
    assert len(data["panels"]) == 6


def test_render_alerts_contains_critical() -> None:
    """T-16: Alert rules contain a critical alert."""
    alerts = _render_alerts(80.0)
    assert "critical" in alerts.lower()


def test_render_alerts_divisor_is_pool_capacity_not_literal_one() -> None:
    """R6-S10-F5 regression: divisor must be pool_size+max_overflow, not 1.

    Prior bug: f-string emitted ``/ ({1}) * 100`` which Python rendered as
    the literal ``1``, so every alert fired from the first active connection
    on every deploy. The expression must divide by an integer >= 2 (a real
    pool capacity). Default capacity is pool_size=20 + max_overflow=10 = 30.

    Juror: ad597adfde81405df (R6-S10-F5).
    """
    import re

    alerts = _render_alerts(80.0, pool_size=20, max_overflow=10)

    # Must NOT contain the literal-1 divisor anywhere.
    assert "/ (1)" not in alerts, (
        "Divisor is literal 1 — every deploy fires critical from connection #1.\n"
        f"Generated:\n{alerts}"
    )

    # Must contain an integer divisor >= 2.
    divisors = [int(m) for m in re.findall(r"/ \((\d+)\) \* 100", alerts)]
    assert divisors, f"No ``/ (<int>) * 100`` divisor found in:\n{alerts}"
    for d in divisors:
        assert d >= 2, f"Divisor {d} is too small (must be pool capacity, not 1)"

    # And the default capacity should be exactly 30 (20 + 10).
    assert 30 in divisors, (
        f"Expected capacity 30 (pool_size=20 + max_overflow=10), got {divisors}"
    )


def test_render_alerts_divisor_reflects_custom_capacity() -> None:
    """R6-S10-F5 regression: divisor follows custom pool_size/max_overflow."""
    import re

    alerts = _render_alerts(80.0, pool_size=50, max_overflow=25)
    divisors = [int(m) for m in re.findall(r"/ \((\d+)\) \* 100", alerts)]
    assert 75 in divisors, (
        f"Expected capacity 75 (pool_size=50 + max_overflow=25), got {divisors}"
    )


def test_render_alerts_emits_promql_divisor_for_default_call() -> None:
    """R6-S10-F5 regression: the tool entry point (default args) renders a real divisor."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        alert_yaml = (proj / "infra" / "prometheus" / "pool_alerts.yaml").read_text()
        assert "/ (1)" not in alert_yaml, (
            "Generated pool_alerts.yaml has literal-1 divisor:\n" + alert_yaml
        )
        # Defaults: pool_size=20, max_overflow=10 → 30.
        assert "/ (30)" in alert_yaml, (
            "Expected '/ (30)' divisor in generated YAML, got:\n" + alert_yaml
        )


def test_notes_contain_pool_params() -> None:
    """T-17: Notes mention pool_size and max_overflow."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = connection_pool_monitor(
            ToolInput(project_dir=str(proj)),
            pool_size=20,
            max_overflow=5,
        )
        notes_text = " ".join(result.notes or [])
        assert "20" in notes_text


def test_next_steps_present() -> None:
    """T-18: next_steps guide the developer."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert result.next_steps


def test_execution_time_recorded() -> None:
    """T-19: execution_time_ms is non-negative."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = connection_pool_monitor(ToolInput(project_dir=str(proj)))
        assert result.execution_time_ms >= 0


def test_monitor_has_attach_method() -> None:
    """T-20: pool_monitor.py defines attach_pool_monitor function."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "pool_monitor.py").read_text()
        assert "def attach_pool_monitor" in content


def test_monitor_has_get_monitor() -> None:
    """T-21: pool_monitor.py defines get_monitor function."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "pool_monitor.py").read_text()
        assert "def get_monitor" in content


def test_monitor_has_health_method() -> None:
    """T-22: PoolMonitor class has health() method."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        connection_pool_monitor(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "pool_monitor.py").read_text()
        assert "def health" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_success_creates_files,
        test_monitor_file_created,
        test_monitor_file_contains_pool_monitor_class,
        test_health_route_created,
        test_health_route_has_endpoint,
        test_grafana_dashboard_created,
        test_grafana_dashboard_valid_json,
        test_alert_rules_created,
        test_alert_rules_contain_threshold,
        test_idempotent_returns_no_op,
        test_dry_run_no_files,
        test_main_py_patched,
        test_pool_size_in_monitor_file,
        test_render_dashboard_has_six_panels,
        test_render_alerts_contains_critical,
        test_render_alerts_divisor_is_pool_capacity_not_literal_one,
        test_render_alerts_divisor_reflects_custom_capacity,
        test_render_alerts_emits_promql_divisor_for_default_call,
        test_notes_contain_pool_params,
        test_next_steps_present,
        test_execution_time_recorded,
        test_monitor_has_attach_method,
        test_monitor_has_get_monitor,
        test_monitor_has_health_method,
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
