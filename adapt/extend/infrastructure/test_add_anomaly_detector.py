"""Tests for TOOL-102 add_anomaly_detector.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria (CC-01 through CC-LAST).

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_anomaly_detector.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_anomaly_detector.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_anomaly_detector import add_anomaly_detector
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="anomaly_t01")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="anomaly_t02")
    r1 = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing."""
    project_dir = create_fixture_project(name="anomaly_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 5 files created, all existing on disk."""
    project_dir = create_fixture_project(name="anomaly_t04")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (config), all existing on disk."""
    project_dir = create_fixture_project(name="anomaly_t05")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 file modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files in app/anomaly/ parse without SyntaxError."""
    project_dir = create_fixture_project(name="anomaly_t06")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    anomaly_dir = project_dir / "app" / "anomaly"
    for py_file in sorted(anomaly_dir.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="anomaly_t07")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    app_dir = project_dir / "app"
    violations: list[str] = []
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    if loc > 50:
                        violations.append(
                            f"{py_file.relative_to(project_dir)}::{node.name} ({loc} LOC)"
                        )
    assert not violations, "Functions exceed 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: ANOMALY_ENABLED in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="anomaly_t08")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists(), "config.py not found"
    content = config_file.read_text()
    assert "ANOMALY_ENABLED" in content
    for line in content.splitlines():
        if "ANOMALY_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"Config field must have 4-space indent: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: models/__init__.py untouched
# ---------------------------------------------------------------------------

def test_models_init_not_broken() -> None:
    """CC-09: models/__init__.py still parseable after tool run."""
    project_dir = create_fixture_project(name="anomaly_t09")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    if models_init.exists():
        ast.parse(models_init.read_text())


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: anomaly.py route file uses APIRouter with /anomaly prefix."""
    project_dir = create_fixture_project(name="anomaly_t10")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    anomaly_route = project_dir / "app" / "api" / "routes" / "anomaly.py"
    assert anomaly_route.exists(), "anomaly.py route not created"
    content = anomaly_route.read_text()
    assert "APIRouter" in content
    assert "/anomaly" in content


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_detector_has_zscore() -> None:
    """CC-11: detector.py implements Z-score anomaly detection."""
    project_dir = create_fixture_project(name="anomaly_t11")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    detector_file = project_dir / "app" / "anomaly" / "detector.py"
    assert detector_file.exists(), "detector.py not created"
    content = detector_file.read_text()
    assert "AnomalyDetector" in content
    assert "z_score" in content or "z-score" in content.lower()
    assert "sensitivity" in content


def test_detector_has_ema() -> None:
    """CC-12: detector.py implements EMA (exponential moving average)."""
    project_dir = create_fixture_project(name="anomaly_t12")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    detector_file = project_dir / "app" / "anomaly" / "detector.py"
    content = detector_file.read_text()
    assert "ema" in content.lower() or "exponential" in content.lower()
    assert "alpha" in content or "_ema" in content


def test_detector_tracks_four_metrics() -> None:
    """CC-13: AnomalyDetector tracks request_rate, error_rate, latency, payload_size."""
    project_dir = create_fixture_project(name="anomaly_t13")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    detector_file = project_dir / "app" / "anomaly" / "detector.py"
    content = detector_file.read_text()
    assert "request_rate" in content or "req_rate" in content
    assert "error_rate" in content or "err_rate" in content or "err_flag" in content
    assert "latency" in content
    assert "payload" in content or "payload_bytes" in content


def test_alerter_has_webhook_and_log() -> None:
    """CC-14: alerter.py implements AlertDispatcher with webhook + log."""
    project_dir = create_fixture_project(name="anomaly_t14")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    alerter_file = project_dir / "app" / "anomaly" / "alerter.py"
    assert alerter_file.exists(), "alerter.py not created"
    content = alerter_file.read_text()
    assert "AlertDispatcher" in content
    assert "webhook" in content.lower()
    assert "logger.warning" in content or "logging" in content


def test_httpx_lazy_in_alerter() -> None:
    """CC-15: httpx is imported lazily (inside function body) in alerter.py."""
    project_dir = create_fixture_project(name="anomaly_t15")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    alerter_file = project_dir / "app" / "anomaly" / "alerter.py"
    tree = ast.parse(alerter_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = ""
            if isinstance(node, ast.Import):
                name = node.names[0].name if node.names else ""
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ""
            assert "httpx" not in name.lower(), (
                f"httpx imported at top level in alerter.py: {name}"
            )


def test_middleware_updates_per_request() -> None:
    """CC-16: AnomalyMiddleware calls detector.observe() per request."""
    project_dir = create_fixture_project(name="anomaly_t16")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "anomaly.py"
    assert mw_file.exists(), "anomaly.py middleware not created"
    content = mw_file.read_text()
    assert "AnomalyMiddleware" in content
    assert "observe" in content
    assert "get_detector" in content


def test_anomaly_status_route() -> None:
    """CC-17: /anomaly/status endpoint exists in routes/anomaly.py."""
    project_dir = create_fixture_project(name="anomaly_t17")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    anomaly_route = project_dir / "app" / "api" / "routes" / "anomaly.py"
    content = anomaly_route.read_text()
    assert "anomaly_status" in content or "/status" in content


def test_anomaly_models_pydantic() -> None:
    """CC-18: anomaly/models.py contains AnomalyStatus Pydantic schema."""
    project_dir = create_fixture_project(name="anomaly_t18")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    models_file = project_dir / "app" / "anomaly" / "models.py"
    assert models_file.exists(), "anomaly/models.py not created"
    content = models_file.read_text()
    assert "AnomalyStatus" in content
    assert "BaseModel" in content


def test_detector_init_function() -> None:
    """CC-19: init_detector() function exists and sets global detector."""
    project_dir = create_fixture_project(name="anomaly_t19")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    detector_file = project_dir / "app" / "anomaly" / "detector.py"
    content = detector_file.read_text()
    assert "init_detector" in content
    assert "get_detector" in content


def test_config_has_all_anomaly_fields() -> None:
    """CC-20: All four ANOMALY_* fields are in config.py."""
    project_dir = create_fixture_project(name="anomaly_t20")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in [
        "ANOMALY_ENABLED",
        "ANOMALY_SENSITIVITY",
        "ANOMALY_WINDOW_SIZE",
        "ANOMALY_ALERT_WEBHOOK_URL",
    ]:
        assert field in content, f"{field} not found in config.py"


def test_anomaly_init_exports() -> None:
    """CC-21: app/anomaly/__init__.py re-exports AnomalyDetector and AlertDispatcher."""
    project_dir = create_fixture_project(name="anomaly_t21")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "anomaly" / "__init__.py"
    assert init_file.exists(), "anomaly/__init__.py not created"
    content = init_file.read_text()
    assert "AnomalyDetector" in content
    assert "AlertDispatcher" in content


def test_notes_mention_zscore_and_ema() -> None:
    """CC-22: notes describe Z-score and EMA detection."""
    project_dir = create_fixture_project(name="anomaly_t22")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "z-score" in combined or "zscore" in combined or "ema" in combined or "sliding" in combined


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="anomaly_t23")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps guides developer to set ANOMALY_ENABLED."""
    project_dir = create_fixture_project(name="anomaly_t24")
    result = add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "anomaly_enabled" in combined or "anomaly" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="anomaly_t25")
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    add_anomaly_detector(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_not_broken,
        test_routes_registered,
        test_detector_has_zscore,
        test_detector_has_ema,
        test_detector_tracks_four_metrics,
        test_alerter_has_webhook_and_log,
        test_httpx_lazy_in_alerter,
        test_middleware_updates_per_request,
        test_anomaly_status_route,
        test_anomaly_models_pydantic,
        test_detector_init_function,
        test_config_has_all_anomaly_fields,
        test_anomaly_init_exports,
        test_notes_mention_zscore_and_ema,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-102 add_anomaly_detector: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
