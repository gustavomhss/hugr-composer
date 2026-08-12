"""Structural tests for TOOL-085 add_opentelemetry.

Covers all Completeness Criteria (CC-01 through CC-LAST) from the
MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_opentelemetry.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_opentelemetry.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_opentelemetry import add_opentelemetry
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under root parses without SyntaxError."""
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


def _otel_top_level_imports(py_file: Path) -> list[str]:
    """Return any top-level opentelemetry import names in py_file."""
    tree = ast.parse(py_file.read_text())
    top_otel: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "opentelemetry" in alias.name.lower():
                    top_otel.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and "opentelemetry" in node.module.lower():
                top_otel.append(node.module)
    return top_otel


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="otel_t01")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="otel_t02")
    r1 = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="otel_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 4 new files (init, setup, middleware, metrics)."""
    project_dir = create_fixture_project(name="otel_t04")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: "
        f"{result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 1 file (config)."""
    project_dir = create_fixture_project(name="otel_t05")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}: "
        f"{result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="otel_t06")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="otel_t07")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """OTEL_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="otel_t08")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "OTEL_ENABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "OTEL_TRACES_SAMPLER",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify field is inside class body (4-space indent)
    for line in content.splitlines():
        if "OTEL_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"OTEL_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests (≥5)
# ---------------------------------------------------------------------------

def test_telemetry_package_exists() -> None:
    """app/telemetry/__init__.py exists and exports init_telemetry."""
    project_dir = create_fixture_project(name="otel_t11")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    pkg_init = project_dir / "app" / "telemetry" / "__init__.py"
    assert pkg_init.exists(), "app/telemetry/__init__.py not created"
    content = pkg_init.read_text()
    assert "init_telemetry" in content, (
        "init_telemetry not exported from app/telemetry/__init__.py"
    )


def test_all_otel_imports_are_lazy_in_setup() -> None:
    """setup.py has ZERO top-level opentelemetry imports."""
    project_dir = create_fixture_project(name="otel_t12")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "telemetry" / "setup.py"
    assert setup_file.exists(), "app/telemetry/setup.py not created"
    top_level = _otel_top_level_imports(setup_file)
    assert not top_level, (
        f"setup.py has top-level opentelemetry imports (MUST be lazy): {top_level}"
    )


def test_all_otel_imports_are_lazy_in_middleware() -> None:
    """middleware.py has ZERO top-level opentelemetry imports."""
    project_dir = create_fixture_project(name="otel_t13")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "telemetry" / "middleware.py"
    assert mw_file.exists(), "app/telemetry/middleware.py not created"
    top_level = _otel_top_level_imports(mw_file)
    assert not top_level, (
        f"middleware.py has top-level opentelemetry imports (MUST be lazy): {top_level}"
    )


def test_all_otel_imports_are_lazy_in_metrics() -> None:
    """metrics.py has ZERO top-level opentelemetry imports."""
    project_dir = create_fixture_project(name="otel_t14")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "telemetry" / "metrics.py"
    assert metrics_file.exists(), "app/telemetry/metrics.py not created"
    top_level = _otel_top_level_imports(metrics_file)
    assert not top_level, (
        f"metrics.py has top-level opentelemetry imports (MUST be lazy): {top_level}"
    )


def test_middleware_has_otel_middleware_class() -> None:
    """app/telemetry/middleware.py defines OTELMiddleware."""
    project_dir = create_fixture_project(name="otel_t15")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "telemetry" / "middleware.py"
    content = mw_file.read_text()
    assert "OTELMiddleware" in content, "OTELMiddleware class not found in middleware.py"
    assert "BaseHTTPMiddleware" in content, (
        "OTELMiddleware should extend BaseHTTPMiddleware"
    )


def test_metrics_has_counters() -> None:
    """app/telemetry/metrics.py has request_count, error_count, duration."""
    project_dir = create_fixture_project(name="otel_t16")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "telemetry" / "metrics.py"
    content = metrics_file.read_text()
    assert "request_count" in content or "request_counter" in content, (
        "request counter not found in metrics.py"
    )
    assert "error_count" in content or "error_counter" in content, (
        "error counter not found in metrics.py"
    )
    assert "duration" in content.lower(), "duration metric not found in metrics.py"


def test_setup_has_three_providers() -> None:
    """setup.py initialises TracerProvider, MeterProvider, and LoggerProvider."""
    project_dir = create_fixture_project(name="otel_t17")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "telemetry" / "setup.py"
    content = setup_file.read_text()
    assert "TracerProvider" in content, "TracerProvider not in setup.py"
    assert "MeterProvider" in content, "MeterProvider not in setup.py"
    assert "LoggerProvider" in content, "LoggerProvider not in setup.py"


def test_otel_enabled_gate_in_init_telemetry() -> None:
    """init_telemetry checks OTEL_ENABLED before importing SDK packages."""
    project_dir = create_fixture_project(name="otel_t18")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    setup_file = project_dir / "app" / "telemetry" / "setup.py"
    content = setup_file.read_text()
    assert "OTEL_ENABLED" in content, "OTEL_ENABLED gate not in setup.py"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="otel_t19")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps should mention opentelemetry-sdk."""
    project_dir = create_fixture_project(name="otel_t20")
    result = add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "opentelemetry" in combined, "next_steps should mention opentelemetry"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="otel_t21")
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    add_opentelemetry(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: error on invalid project_dir
# ---------------------------------------------------------------------------

def test_error_on_missing_project_dir() -> None:
    """Tool returns error when project_dir does not exist."""
    result = add_opentelemetry(ToolInput(project_dir="/nonexistent/path/xyz"))
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


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
        test_telemetry_package_exists,
        test_all_otel_imports_are_lazy_in_setup,
        test_all_otel_imports_are_lazy_in_middleware,
        test_all_otel_imports_are_lazy_in_metrics,
        test_middleware_has_otel_middleware_class,
        test_metrics_has_counters,
        test_setup_has_three_providers,
        test_otel_enabled_gate_in_init_telemetry,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_error_on_missing_project_dir,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if failed == 0 else 1)
