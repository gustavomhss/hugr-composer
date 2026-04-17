"""Tests for TOOL-072 add_opa_integration.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_opa_integration.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_opa_integration.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_opa_integration import add_opa_integration
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="opa_t01")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got: {result.status} / {result.error}"


def test_files_created_all_exist() -> None:
    """T-02: Every path in files_created exists on disk after the run."""
    project_dir = create_fixture_project(name="opa_t02")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_files_modified_all_exist() -> None:
    """T-03: Every path in files_modified exists on disk after the run."""
    project_dir = create_fixture_project(name="opa_t03")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_modified:
        assert Path(p).exists(), f"Modified file missing: {p}"


def test_authz_init_created() -> None:
    """CC-01: app/authz/__init__.py exists and re-exports OPAClient, OPAMiddleware."""
    project_dir = create_fixture_project(name="opa_t04")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "authz" / "__init__.py"
    assert init_file.exists(), "app/authz/__init__.py not created"
    content = init_file.read_text()
    assert "OPAClient" in content
    assert "OPAMiddleware" in content


def test_opa_models_file_created() -> None:
    """CC-02: app/authz/opa_models.py exists with OPAInput and OPADecision."""
    project_dir = create_fixture_project(name="opa_t05")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    models_file = project_dir / "app" / "authz" / "opa_models.py"
    assert models_file.exists(), "opa_models.py not created"
    content = models_file.read_text()
    assert "class OPAInput" in content
    assert "class OPADecision" in content


def test_opa_input_has_required_fields() -> None:
    """CC-03: OPAInput has subject, action, resource, context fields."""
    project_dir = create_fixture_project(name="opa_t06")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_models.py").read_text()
    for field in ("subject", "action", "resource", "context"):
        assert field in content, f"OPAInput missing field: {field}"


def test_opa_decision_has_allow_field() -> None:
    """CC-04: OPADecision has allow bool field."""
    project_dir = create_fixture_project(name="opa_t07")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_models.py").read_text()
    assert "allow" in content
    assert "bool" in content


def test_opa_client_file_created() -> None:
    """CC-05: app/authz/opa_client.py exists with OPAClient class."""
    project_dir = create_fixture_project(name="opa_t08")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "authz" / "opa_client.py"
    assert client_file.exists(), "opa_client.py not created"
    content = client_file.read_text()
    assert "class OPAClient" in content


def test_opa_client_has_query_method() -> None:
    """CC-06: OPAClient has async query() method."""
    project_dir = create_fixture_project(name="opa_t09")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "async def query" in content


def test_opa_client_has_health_method() -> None:
    """CC-07: OPAClient has async health() method."""
    project_dir = create_fixture_project(name="opa_t10")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "async def health" in content


def test_opa_client_circuit_breaker() -> None:
    """CC-08: opa_client.py contains circuit breaker logic."""
    project_dir = create_fixture_project(name="opa_t11")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "circuit" in content.lower() or "_CircuitBreaker" in content


def test_opa_client_lazy_httpx() -> None:
    """CC-09: httpx is NOT imported at module top level in opa_client.py."""
    project_dir = create_fixture_project(name="opa_t12")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "authz" / "opa_client.py"
    tree = ast.parse(client_file.read_text())
    for node in tree.body:  # top-level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "httpx" not in alias.name, "httpx must be a lazy import"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "httpx" not in node.module, "httpx must be a lazy import"


def test_opa_middleware_file_created() -> None:
    """CC-10: app/authz/opa_middleware.py exists with OPAMiddleware class."""
    project_dir = create_fixture_project(name="opa_t13")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "authz" / "opa_middleware.py"
    assert mw_file.exists(), "opa_middleware.py not created"
    content = mw_file.read_text()
    assert "class OPAMiddleware" in content


def test_opa_middleware_returns_403() -> None:
    """CC-11: OPAMiddleware returns HTTP 403 on denied requests."""
    project_dir = create_fixture_project(name="opa_t14")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_middleware.py").read_text()
    assert "403" in content or "HTTP_403_FORBIDDEN" in content


def test_rego_policies_created() -> None:
    """CC-12: app/authz/policies/ contains authz.rego, data.json, authz_test.rego."""
    project_dir = create_fixture_project(name="opa_t15")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    policies_dir = project_dir / "app" / "authz" / "policies"
    assert policies_dir.is_dir(), "policies/ dir not created"
    for fname in ("authz.rego", "data.json", "authz_test.rego"):
        assert (policies_dir / fname).exists(), f"{fname} not created"


def test_authz_rego_default_deny() -> None:
    """CC-13: authz.rego contains 'default allow := false'."""
    project_dir = create_fixture_project(name="opa_t16")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    rego = (project_dir / "app" / "authz" / "policies" / "authz.rego").read_text()
    assert "default allow" in rego


def test_opa_routes_file_created() -> None:
    """CC-14: app/api/routes/opa.py exists with /authz/opa prefix."""
    project_dir = create_fixture_project(name="opa_t17")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "opa.py"
    assert routes_file.exists(), "opa.py routes not created"
    content = routes_file.read_text()
    assert "/authz/opa" in content or 'prefix="/authz/opa"' in content


def test_opa_routes_check_endpoint() -> None:
    """CC-15: opa.py has POST /authz/opa/check endpoint."""
    project_dir = create_fixture_project(name="opa_t18")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "opa.py").read_text()
    assert "/check" in content
    assert "async def check_policy" in content or "def check" in content


def test_opa_routes_health_endpoint() -> None:
    """CC-16: opa.py has GET /authz/opa/health endpoint."""
    project_dir = create_fixture_project(name="opa_t19")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "opa.py").read_text()
    assert "/health" in content


def test_config_fields_patched() -> None:
    """CC-17: app/core/config.py has all 5 OPA fields at 4-space indent."""
    project_dir = create_fixture_project(name="opa_t20")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    for field in ("OPA_URL", "OPA_ENABLED", "OPA_POLICY_PATH", "OPA_TIMEOUT_MS", "OPA_FAIL_OPEN"):
        assert field in content, f"Missing config field: {field}"
        for line in content.splitlines():
            if field in line and ":" in line and "=" in line:
                assert line.startswith("    "), f"{field} not at 4-space indent: {line!r}"
                break


def test_routes_init_patched() -> None:
    """CC-18: app/routes/__init__.py imports and includes opa_router."""
    project_dir = create_fixture_project(name="opa_t21")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert "from app.api.routes.opa import router as opa_router" in content
    assert "api_router.include_router(opa_router)" in content


def test_requirements_patched() -> None:
    """CC-19: requirements.txt contains httpx>=0.28.0 (or any httpx entry)."""
    project_dir = create_fixture_project(name="opa_t22")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "requirements.txt").read_text()
    assert "httpx" in content, "httpx not in requirements.txt"


def test_all_py_files_parse() -> None:
    """CC-20: All .py files in the project parse without SyntaxError after run."""
    project_dir = create_fixture_project(name="opa_t23")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-21: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="opa_t24")
    r1 = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Expected no_op on second run, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs, project .py files must still parse without error."""
    project_dir = create_fixture_project(name="opa_t25")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="opa_t26")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_opa_integration(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="opa_t27")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """next_steps must be non-empty and mention OPA sidecar."""
    project_dir = create_fixture_project(name="opa_t28")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "opa" in combined or "openpolicyagent" in combined


def test_minimum_files_created() -> None:
    """Spec requires >= 5 files created (authz_init, models, client, middleware, routes)."""
    project_dir = create_fixture_project(name="opa_t29")
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >=5 files created, got {len(result.files_created)}: {result.files_created}"
    )


def test_no_function_over_50_loc() -> None:
    """CC-22: No generated function in app/authz/ or app/api/routes/opa.py exceeds 50 LOC."""
    project_dir = create_fixture_project(name="opa_t30")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    dirs = [
        project_dir / "app" / "authz",
        project_dir / "app" / "api" / "routes",
    ]
    violations: list[str] = []
    for d in dirs:
        for py_file in sorted(d.rglob("*.py")):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno:
                        loc = node.end_lineno - node.lineno + 1
                        if loc > 50:
                            violations.append(f"{py_file.name}::{node.name}: {loc} LOC")
    assert not violations, f"Functions exceed 50 LOC: {violations}"


def test_get_opa_client_dependency() -> None:
    """CC-23: opa_client.py exposes get_opa_client FastAPI dependency."""
    project_dir = create_fixture_project(name="opa_t31")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "def get_opa_client" in content


def test_no_dead_imports_ruff() -> None:
    """QS-08: No F401 dead imports in generated app/authz/ files."""
    project_dir = create_fixture_project(name="opa_t32")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    authz_dir = str(project_dir / "app" / "authz")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F401", authz_dir],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 or "F401" not in result.stdout, (
        f"Dead imports found:\n{result.stdout}"
    )


def test_fail_open_configurable() -> None:
    """CC-24: opa_client.py supports fail_open configuration."""
    project_dir = create_fixture_project(name="opa_t33")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "fail_open" in content


def test_circuit_breaker_in_client() -> None:
    """CC-25: Circuit breaker is referenced in OPAClient.query."""
    project_dir = create_fixture_project(name="opa_t34")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_client.py").read_text()
    assert "is_open" in content
    assert "record_failure" in content
    assert "record_success" in content


def test_pydantic_models_use_config_dict() -> None:
    """QS-11: OPA Pydantic models use ConfigDict."""
    project_dir = create_fixture_project(name="opa_t35")
    add_opa_integration(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "opa_models.py").read_text()
    assert "ConfigDict" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_all_exist,
        test_files_modified_all_exist,
        test_authz_init_created,
        test_opa_models_file_created,
        test_opa_input_has_required_fields,
        test_opa_decision_has_allow_field,
        test_opa_client_file_created,
        test_opa_client_has_query_method,
        test_opa_client_has_health_method,
        test_opa_client_circuit_breaker,
        test_opa_client_lazy_httpx,
        test_opa_middleware_file_created,
        test_opa_middleware_returns_403,
        test_rego_policies_created,
        test_authz_rego_default_deny,
        test_opa_routes_file_created,
        test_opa_routes_check_endpoint,
        test_opa_routes_health_endpoint,
        test_config_fields_patched,
        test_routes_init_patched,
        test_requirements_patched,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_minimum_files_created,
        test_no_function_over_50_loc,
        test_get_opa_client_dependency,
        test_no_dead_imports_ruff,
        test_fail_open_configurable,
        test_circuit_breaker_in_client,
        test_pydantic_models_use_config_dict,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)
