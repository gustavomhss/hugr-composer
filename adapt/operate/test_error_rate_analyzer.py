"""Tests for TOOL-041 error_rate_analyzer.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_error_rate_analyzer.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.error_rate_analyzer import error_rate_analyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp: Path) -> Path:
    """Create a minimal FastAPI project with main.py."""
    proj = tmp / "proj"
    app = proj / "app"
    (app / "core").mkdir(parents=True)
    (app / "core" / "config.py").write_text(
        "from pydantic_settings import BaseSettings\nclass Settings(BaseSettings): pass\nsettings = Settings()\n"
    )
    (app / "api" / "middleware").mkdir(parents=True)
    (app / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = error_rate_analyzer(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_success_creates_files() -> None:
    """T-02: Returns success and creates middleware and support files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert result.status == "success"
        assert result.files_created


def test_middleware_file_created() -> None:
    """T-03: app/api/middleware/error_rate.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        mw = proj / "app" / "api" / "middleware" / "error_rate.py"
        assert mw.exists()


def test_middleware_contains_class() -> None:
    """T-04: error_rate.py contains ErrorRateMiddleware class."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "api" / "middleware" / "error_rate.py").read_text()
        assert "class ErrorRateMiddleware" in content


def test_middleware_has_dispatch() -> None:
    """T-05: ErrorRateMiddleware has async dispatch method."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "api" / "middleware" / "error_rate.py").read_text()
        assert "async def dispatch" in content


def test_aggregator_created() -> None:
    """T-06: app/core/error_aggregator.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        agg = proj / "app" / "core" / "error_aggregator.py"
        assert agg.exists()


def test_aggregator_has_ring_buffer() -> None:
    """T-07: error_aggregator.py contains RingBufferAggregator."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "error_aggregator.py").read_text()
        assert "RingBufferAggregator" in content


def test_trend_detector_created() -> None:
    """T-08: app/core/error_trend.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert (proj / "app" / "core" / "error_trend.py").exists()


def test_classifier_created() -> None:
    """T-09: app/core/error_classifier.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert (proj / "app" / "core" / "error_classifier.py").exists()


def test_alert_rules_created() -> None:
    """T-10: Prometheus alert rules YAML is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        alert = proj / "infra" / "prometheus" / "error_rate_alerts.yaml"
        assert alert.exists()


def test_alert_rules_contain_5xx() -> None:
    """T-11: Alert rules reference 5xx errors."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "infra" / "prometheus" / "error_rate_alerts.yaml").read_text()
        assert "5xx" in content


def test_main_py_patched() -> None:
    """T-12: main.py is patched to add ErrorRateMiddleware."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        main = (proj / "app" / "main.py").read_text()
        assert "ErrorRateMiddleware" in main


def test_idempotent_returns_no_op() -> None:
    """T-13: Running twice returns no_op on second run."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        r1 = error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert r1.status == "success"
        r2 = error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert r2.status == "no_op"


def test_dry_run_no_files() -> None:
    """T-14: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        before = set(proj.rglob("*"))
        result = error_rate_analyzer(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert set(proj.rglob("*")) == before


def test_middleware_has_structlog() -> None:
    """T-15: Middleware uses structlog (or fallback logging)."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "api" / "middleware" / "error_rate.py").read_text()
        assert "structlog" in content or "logging" in content


def test_middleware_has_prometheus_counter() -> None:
    """T-16: Middleware references Prometheus Counter."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "api" / "middleware" / "error_rate.py").read_text()
        assert "Counter" in content


def test_trend_has_is_spike() -> None:
    """T-17: TrendDetector has is_spike method."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "error_trend.py").read_text()
        assert "def is_spike" in content


def test_classifier_has_classify() -> None:
    """T-18: ErrorClassifier has classify method."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        content = (proj / "app" / "core" / "error_classifier.py").read_text()
        assert "def classify" in content


def test_notes_contain_sink() -> None:
    """T-19: notes mention the configured sink."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = error_rate_analyzer(
            ToolInput(project_dir=str(proj)),
            sink="prometheus",
        )
        notes_text = " ".join(result.notes or [])
        assert "prometheus" in notes_text.lower()


def test_execution_time_recorded() -> None:
    """T-20: execution_time_ms is non-negative."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        result = error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert result.execution_time_ms >= 0


def test_metrics_file_created() -> None:
    """T-21: app/core/error_metrics.py is created."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project(Path(tmp))
        error_rate_analyzer(ToolInput(project_dir=str(proj)))
        assert (proj / "app" / "core" / "error_metrics.py").exists()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_success_creates_files,
        test_middleware_file_created,
        test_middleware_contains_class,
        test_middleware_has_dispatch,
        test_aggregator_created,
        test_aggregator_has_ring_buffer,
        test_trend_detector_created,
        test_classifier_created,
        test_alert_rules_created,
        test_alert_rules_contain_5xx,
        test_main_py_patched,
        test_idempotent_returns_no_op,
        test_dry_run_no_files,
        test_middleware_has_structlog,
        test_middleware_has_prometheus_counter,
        test_trend_has_is_spike,
        test_classifier_has_classify,
        test_notes_contain_sink,
        test_execution_time_recorded,
        test_metrics_file_created,
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
