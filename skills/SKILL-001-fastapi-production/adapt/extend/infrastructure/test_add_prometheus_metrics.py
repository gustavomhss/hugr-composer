"""Structural tests for TOOL-086 add_prometheus_metrics.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_prometheus_metrics.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_prometheus_metrics.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_prometheus_metrics import add_prometheus_metrics
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
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="prom_t01")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------


def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = create_fixture_project(name="prom_t02")
    r1 = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------


def test_dry_run() -> None:
    """CC-03: dry_run=True must not touch any file on disk."""
    project_dir = create_fixture_project(name="prom_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count + existence
# ---------------------------------------------------------------------------


def test_files_created_count() -> None:
    """CC-04: At least 3 files created, all exist on disk."""
    project_dir = create_fixture_project(name="prom_t04")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count + existence
# ---------------------------------------------------------------------------


def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified, all exist on disk."""
    project_dir = create_fixture_project(name="prom_t05")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------


def test_all_py_parse() -> None:
    """CC-06: Every .py file in project parses without SyntaxError after tool."""
    project_dir = create_fixture_project(name="prom_t06")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------


def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = create_fixture_project(name="prom_t07")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    metrics_dir = project_dir / "app" / "metrics"
    violations: list[str] = []
    for py_file in sorted(metrics_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------


def test_config_fields_patched() -> None:
    """CC-08: PROMETHEUS_ENABLED and PROMETHEUS_PREFIX appear in config.py."""
    project_dir = create_fixture_project(name="prom_t08")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "PROMETHEUS_ENABLED" in content, "PROMETHEUS_ENABLED not in config.py"
    assert "PROMETHEUS_PREFIX" in content, "PROMETHEUS_PREFIX not in config.py"
    # Verify 4-space indent inside Settings class
    for line in content.splitlines():
        if "PROMETHEUS_ENABLED" in line or "PROMETHEUS_PREFIX" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-10: /metrics route registered (if routes_init exists)
# ---------------------------------------------------------------------------


def test_routes_registered() -> None:
    """CC-10: app/api/routes/metrics.py is created with a router."""
    project_dir = create_fixture_project(name="prom_t09")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    metrics_route = project_dir / "app" / "api" / "routes" / "metrics.py"
    assert metrics_route.exists(), "app/api/routes/metrics.py not created"
    content = metrics_route.read_text()
    assert "router" in content, "metrics.py must define a router"
    assert "/metrics" in content or "prometheus_metrics" in content


# ---------------------------------------------------------------------------
# Domain tests (CC-11+): >= 5 domain-specific checks
# ---------------------------------------------------------------------------


def test_collectors_file_has_request_metrics() -> None:
    """D-01: app/metrics/collectors.py has RequestMetrics class."""
    project_dir = create_fixture_project(name="prom_t10")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    collectors = project_dir / "app" / "metrics" / "collectors.py"
    assert collectors.exists()
    content = collectors.read_text()
    assert "RequestMetrics" in content
    assert "request_total" in content or "requests_total" in content


def test_collectors_has_duration_histogram() -> None:
    """D-02: collectors.py has request_duration_seconds Histogram."""
    project_dir = create_fixture_project(name="prom_t11")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    collectors = project_dir / "app" / "metrics" / "collectors.py"
    content = collectors.read_text()
    assert "request_duration_seconds" in content or "duration_seconds" in content
    assert "Histogram" in content or "buckets" in content


def test_collectors_has_errors_counter() -> None:
    """D-03: collectors.py has request_errors_total Counter."""
    project_dir = create_fixture_project(name="prom_t12")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    collectors = project_dir / "app" / "metrics" / "collectors.py"
    content = collectors.read_text()
    assert "errors_total" in content or "request_errors" in content


def test_prometheus_client_is_lazy() -> None:
    """D-04: prometheus_client is NOT imported at module top-level (lazy import)."""
    project_dir = create_fixture_project(name="prom_t13")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    metrics_dir = project_dir / "app" / "metrics"
    for py_file in sorted(metrics_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "prometheus_client" not in alias.name, (
                        f"prometheus_client imported at top-level in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "prometheus_client", (
                    f"prometheus_client imported at top-level in {py_file}"
                )


def test_middleware_file_created() -> None:
    """D-05: app/metrics/middleware.py is created with PrometheusMiddleware."""
    project_dir = create_fixture_project(name="prom_t14")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "metrics" / "middleware.py"
    assert mw.exists(), "middleware.py not created"
    content = mw.read_text()
    assert "PrometheusMiddleware" in content


def test_main_py_patched_with_middleware() -> None:
    """D-06: main.py is patched to register PrometheusMiddleware."""
    project_dir = create_fixture_project(name="prom_t15")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        content = main_file.read_text()
        assert "PrometheusMiddleware" in content or "init_metrics" in content


def test_metrics_init_has_exports() -> None:
    """D-07: app/metrics/__init__.py re-exports public symbols."""
    project_dir = create_fixture_project(name="prom_t16")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "metrics" / "__init__.py"
    assert init_file.exists()
    content = init_file.read_text()
    assert "RequestMetrics" in content
    assert "PrometheusMiddleware" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="prom_t17")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------


def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention prometheus."""
    project_dir = create_fixture_project(name="prom_t18")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "prometheus" in combined or "pip" in combined


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="prom_t19")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra structural checks
# ---------------------------------------------------------------------------


def test_notes_mention_red_metrics() -> None:
    """notes describe RED metrics."""
    project_dir = create_fixture_project(name="prom_t20")
    result = add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "request" in combined or "red" in combined or "metrics" in combined


def test_latency_buckets_in_collectors() -> None:
    """Histogram latency buckets are defined."""
    project_dir = create_fixture_project(name="prom_t21")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    collectors = project_dir / "app" / "metrics" / "collectors.py"
    content = collectors.read_text()
    assert "buckets" in content, "collectors.py must define histogram buckets"


def test_get_metrics_function_present() -> None:
    """get_metrics() module-level accessor is in collectors.py."""
    project_dir = create_fixture_project(name="prom_t22")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    collectors = project_dir / "app" / "metrics" / "collectors.py"
    content = collectors.read_text()
    assert "get_metrics" in content


def test_path_label_uses_route_template_not_raw_path() -> None:
    """R6-S5-F1: the middleware must label by route TEMPLATE, not raw url.path.

    Using ``request.url.path`` as a Prometheus label is unbounded cardinality:
    every distinct id and every 404 scanner URL mints a new time series, a
    metrics-store DoS. The fix reads the matched route's template from the
    request scope and collapses unmatched paths to a constant.
    """
    project_dir = create_fixture_project(name="prom_cardinality")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    mw_src = (project_dir / "app" / "metrics" / "middleware.py").read_text()
    # The path passed to record_request must NOT be the raw url.path.
    assert "path=request.url.path" not in mw_src, (
        "middleware still labels metrics by raw request.url.path (cardinality DoS)"
    )
    # It must resolve the matched route from the scope and have an unmatched fallback.
    assert 'scope.get("route")' in mw_src or 'scope["route"]' in mw_src, (
        "middleware does not read the matched route template from the request scope"
    )
    assert "_route_label" in mw_src, "expected a _route_label helper for the path label"
    assert "__unmatched__" in mw_src, "unmatched paths must collapse to a constant label"


def test_method_label_is_bounded_to_allowlist() -> None:
    """R8-J6-1: the `method` label must be bounded, not raw request.method.

    ``request.method`` is fully client-controlled, so a scanner sending garbage
    verbs mints an unbounded number of time series on the method axis — the same
    cardinality / metrics-store DoS the path normalisation closed (R6-S5-F1),
    still reachable via method. The middleware must allowlist the standard HTTP
    methods and collapse anything else to a single constant bucket BEFORE the
    record_request call.
    """
    project_dir = create_fixture_project(name="prom_method_card")
    add_prometheus_metrics(ToolInput(project_dir=str(project_dir)))
    mw_src = (project_dir / "app" / "metrics" / "middleware.py").read_text()
    # The method passed to record_request must NOT be the raw request.method.
    assert "method=request.method" not in mw_src, (
        "middleware still labels metrics by raw request.method (cardinality DoS via method axis)"
    )
    # It must bound the method via an allowlist helper with an OTHER fallback.
    assert "_method_label" in mw_src, "expected a _method_label helper to bound the method label"
    assert "OTHER" in mw_src, "non-standard methods must collapse to a constant OTHER bucket"
    # All standard verbs must be in the allowlist.
    for verb in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        assert verb in mw_src, f"standard method {verb} missing from the allowlist"

    # Behavioural: the helper must map a garbage verb to OTHER and keep GET as GET.
    import ast as _ast

    mod = _ast.parse(mw_src)
    helper = next(
        n for n in mod.body if isinstance(n, _ast.FunctionDef) and n.name == "_method_label"
    )

    class _Req:
        def __init__(self, method: str) -> None:
            self.method = method

    # Exec only the safe top-level defs (constants + helper), dropping the
    # starlette / app imports and the Request type hint so it runs standalone.
    snippet = "\n".join(mw_src.splitlines()[: (helper.end_lineno or helper.lineno)])
    safe_src = "\n".join(
        ln
        for ln in snippet.splitlines()
        if not ln.startswith(("from starlette", "from app.metrics", "import logging", "logger ="))
    ).replace(": Request", "")
    ns: dict[str, object] = {}
    exec(compile(safe_src, "<mw>", "exec"), ns)  # noqa: S102
    fn = ns["_method_label"]
    assert fn(_Req("GET")) == "GET"
    assert fn(_Req("post")) == "POST"
    assert fn(_Req("FROBNICATE")) == "OTHER"
    assert fn(_Req("\x00garbage")) == "OTHER"


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
        test_routes_registered,
        test_collectors_file_has_request_metrics,
        test_collectors_has_duration_histogram,
        test_collectors_has_errors_counter,
        test_prometheus_client_is_lazy,
        test_middleware_file_created,
        test_main_py_patched_with_middleware,
        test_metrics_init_has_exports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_notes_mention_red_metrics,
        test_latency_buckets_in_collectors,
        test_get_metrics_function_present,
        test_path_label_uses_route_template_not_raw_path,
        test_method_label_is_bounded_to_allowlist,
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

    print(f"\n{'=' * 60}")
    print(f"TOOL-086 add_prometheus_metrics: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
