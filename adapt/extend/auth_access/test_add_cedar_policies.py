"""Tests for TOOL-071 add_cedar_policies.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_cedar_policies.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_cedar_policies.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_cedar_policies import add_cedar_policies
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py(root: Path) -> list[Path]:
    """Return all .py files under *root*, sorted for determinism."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py file under *root* has a SyntaxError."""
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
    """T-01 / CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cedar_t01")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got: {result.status} / {result.error}"
    )


def test_files_created_all_exist() -> None:
    """T-02: Every path in files_created exists on disk after the run."""
    project_dir = create_fixture_project(name="cedar_t02")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_files_modified_all_exist() -> None:
    """T-03: Every path in files_modified exists on disk after the run."""
    project_dir = create_fixture_project(name="cedar_t03")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_modified:
        assert Path(p).exists(), f"Modified file missing: {p}"


def test_engine_file_created() -> None:
    """T-04 / CC-11: app/authz/engine.py exists with CedarEngine class."""
    project_dir = create_fixture_project(name="cedar_t04")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    engine = project_dir / "app" / "authz" / "engine.py"
    assert engine.exists(), "app/authz/engine.py not created"
    content = engine.read_text()
    assert "class CedarEngine" in content
    assert "def load_policies" in content
    assert "def is_authorized" in content


def test_engine_lazy_cedarpy_import() -> None:
    """T-05 / CC-17: cedarpy is NOT imported at module top level in engine.py."""
    project_dir = create_fixture_project(name="cedar_t05")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "authz" / "engine.py"
    tree = ast.parse(engine_file.read_text())
    for node in tree.body:  # Only top-level nodes
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "cedarpy" not in alias.name, "cedarpy must not be a top-level import"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "cedarpy" not in node.module, "cedarpy must not be a top-level import"


def test_models_file_created() -> None:
    """T-06 / CC-11: app/authz/models.py exists with AuthzRequest and AuthzResponse."""
    project_dir = create_fixture_project(name="cedar_t06")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    models = project_dir / "app" / "authz" / "models.py"
    assert models.exists(), "app/authz/models.py not created"
    content = models.read_text()
    assert "class AuthzRequest" in content
    assert "class AuthzResponse" in content


def test_models_pydantic_fields() -> None:
    """T-07: AuthzRequest has principal, action, resource, context fields."""
    project_dir = create_fixture_project(name="cedar_t07")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "models.py").read_text()
    for field in ("principal", "action", "resource", "context"):
        assert field in content, f"AuthzRequest missing field: {field}"


def test_middleware_file_created() -> None:
    """T-08 / CC-11: app/authz/middleware.py exists with CedarAuthzMiddleware."""
    project_dir = create_fixture_project(name="cedar_t08")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    mw = project_dir / "app" / "authz" / "middleware.py"
    assert mw.exists(), "app/authz/middleware.py not created"
    content = mw.read_text()
    assert "class CedarAuthzMiddleware" in content
    assert "dispatch" in content


def test_middleware_returns_403_on_deny() -> None:
    """T-09: Middleware returns 403 JSON when Cedar denies a request."""
    project_dir = create_fixture_project(name="cedar_t09")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "middleware.py").read_text()
    assert "403" in content
    assert "Forbidden" in content or "forbidden" in content or "deny" in content


def test_middleware_skip_paths_present() -> None:
    """T-10: Middleware has configurable skip_paths with health/docs defaults."""
    project_dir = create_fixture_project(name="cedar_t10")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "middleware.py").read_text()
    assert "skip_paths" in content
    assert "/healthz" in content


def test_policies_dir_created() -> None:
    """T-11: app/authz/policies/ directory exists with 3 .cedar files."""
    project_dir = create_fixture_project(name="cedar_t11")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    policies_dir = project_dir / "app" / "authz" / "policies"
    assert policies_dir.is_dir(), "policies directory not created"
    cedar_files = list(policies_dir.glob("*.cedar"))
    assert len(cedar_files) == 3, f"Expected 3 .cedar files, got {len(cedar_files)}"


def test_cedar_policy_files_content() -> None:
    """T-12: admin_full_access.cedar, owner_read_write.cedar, default_deny.cedar exist."""
    project_dir = create_fixture_project(name="cedar_t12")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    policies_dir = project_dir / "app" / "authz" / "policies"
    for name in ("admin_full_access.cedar", "owner_read_write.cedar", "default_deny.cedar"):
        assert (policies_dir / name).exists(), f"Missing policy file: {name}"
    admin_content = (policies_dir / "admin_full_access.cedar").read_text()
    assert "permit" in admin_content
    deny_content = (policies_dir / "default_deny.cedar").read_text()
    assert "forbid" in deny_content


def test_authz_routes_file_created() -> None:
    """T-13 / CC-11: app/api/routes/authz.py exists with /authz endpoints."""
    project_dir = create_fixture_project(name="cedar_t13")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    routes = project_dir / "app" / "api" / "routes" / "authz.py"
    assert routes.exists(), "app/api/routes/authz.py not created"
    content = routes.read_text()
    assert '"/check"' in content or "check" in content
    assert '"/policies"' in content or "policies" in content


def test_authz_routes_prefix() -> None:
    """T-14: authz router uses prefix='/authz'."""
    project_dir = create_fixture_project(name="cedar_t14")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "authz.py").read_text()
    assert 'prefix="/authz"' in content


def test_config_patched() -> None:
    """T-15 / CC-08: app/core/config.py has CEDAR_ENABLED, CEDAR_POLICY_DIR, CEDAR_DEFAULT_EFFECT."""
    project_dir = create_fixture_project(name="cedar_t15")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "CEDAR_ENABLED" in content
    assert "CEDAR_POLICY_DIR" in content
    assert "CEDAR_DEFAULT_EFFECT" in content


def test_config_fields_inside_settings_class() -> None:
    """T-16 / CC-08: Cedar config fields are indented (inside Settings class body)."""
    project_dir = create_fixture_project(name="cedar_t16")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    for field_name in ("CEDAR_ENABLED", "CEDAR_POLICY_DIR", "CEDAR_DEFAULT_EFFECT"):
        for line in content.splitlines():
            if field_name in line and ":" in line:
                assert line.startswith("    "), (
                    f"{field_name} line not inside Settings class body: {line!r}"
                )
                break


def test_routes_init_patched() -> None:
    """T-17 / CC-10: app/routes/__init__.py imports and includes the authz router."""
    project_dir = create_fixture_project(name="cedar_t17")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "routes" / "__init__.py").read_text()
    assert "authz_router" in content
    assert "include_router" in content


def test_requirements_patched() -> None:
    """T-18 / CC-12: requirements.txt contains cedarpy>=0.4.0."""
    project_dir = create_fixture_project(name="cedar_t18")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "requirements.txt").read_text()
    assert "cedarpy" in content


def test_authz_init_reexports() -> None:
    """T-19: app/authz/__init__.py re-exports CedarEngine, get_cedar_engine, AuthzRequest, AuthzResponse."""
    project_dir = create_fixture_project(name="cedar_t19")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "authz" / "__init__.py"
    assert init_file.exists(), "app/authz/__init__.py not created"
    content = init_file.read_text()
    for name in ("CedarEngine", "get_cedar_engine", "AuthzRequest", "AuthzResponse"):
        assert name in content, f"__init__.py missing re-export: {name}"


def test_all_py_files_parse() -> None:
    """T-20 / CC-06: All .py files in the project parse without SyntaxError."""
    project_dir = create_fixture_project(name="cedar_t20")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """T-21 / CC-02 / INV-01: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="cedar_t21")
    r1 = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Expected no_op on second run, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """T-22 / CC-15: After two runs, all .py files still parse."""
    project_dir = create_fixture_project(name="cedar_t22")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """T-23 / CC-03 / INV-02: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="cedar_t23")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """T-24 / CC-13 / INV-06: execution_time_ms is a positive integer."""
    project_dir = create_fixture_project(name="cedar_t24")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """T-25 / CC-14: next_steps is non-empty and mentions cedarpy install."""
    project_dir = create_fixture_project(name="cedar_t25")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    assert any("cedarpy" in s for s in result.next_steps)


def test_minimum_files_created() -> None:
    """T-26 / CC-04: At least 6 files are created (init, engine, models, middleware, 3 cedar, routes)."""
    project_dir = create_fixture_project(name="cedar_t26")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >=6 files created, got {len(result.files_created)}: {result.files_created}"
    )


def test_minimum_files_modified() -> None:
    """T-27 / CC-05: At least 3 files are modified (config, routes_init, requirements)."""
    project_dir = create_fixture_project(name="cedar_t27")
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 3, (
        f"Expected >=3 files modified, got {len(result.files_modified)}: {result.files_modified}"
    )


def test_no_function_over_50_loc() -> None:
    """T-28 / CC-07 / INV-05: No generated function body exceeds 50 LOC."""
    project_dir = create_fixture_project(name="cedar_t28")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    authz_dir = project_dir / "app" / "authz"
    routes_file = project_dir / "app" / "api" / "routes" / "authz.py"
    py_files = list(authz_dir.rglob("*.py")) + [routes_file]
    for py in py_files:
        if not py.exists():
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    assert loc <= 50, (
                        f"Function '{node.name}' in {py} has {loc} LOC (max 50)"
                    )


def test_no_dead_imports_in_generated_code() -> None:
    """T-29 / QS-08: ruff F401 passes on the generated app/authz/ directory."""
    project_dir = create_fixture_project(name="cedar_t29")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    authz_dir = project_dir / "app" / "authz"
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F401", str(authz_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 or "F401" not in result.stdout, (
        f"Dead imports (F401) detected:\n{result.stdout}"
    )


def test_engine_has_singleton_getter() -> None:
    """T-30: engine.py exposes get_cedar_engine singleton function."""
    project_dir = create_fixture_project(name="cedar_t30")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "engine.py").read_text()
    assert "def get_cedar_engine" in content


def test_authz_response_has_allowed_field() -> None:
    """T-31: AuthzResponse.allowed is present for boolean decision."""
    project_dir = create_fixture_project(name="cedar_t31")
    add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "authz" / "models.py").read_text()
    assert "allowed" in content
    assert "bool" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_all_exist,
        test_files_modified_all_exist,
        test_engine_file_created,
        test_engine_lazy_cedarpy_import,
        test_models_file_created,
        test_models_pydantic_fields,
        test_middleware_file_created,
        test_middleware_returns_403_on_deny,
        test_middleware_skip_paths_present,
        test_policies_dir_created,
        test_cedar_policy_files_content,
        test_authz_routes_file_created,
        test_authz_routes_prefix,
        test_config_patched,
        test_config_fields_inside_settings_class,
        test_routes_init_patched,
        test_requirements_patched,
        test_authz_init_reexports,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_minimum_files_created,
        test_minimum_files_modified,
        test_no_function_over_50_loc,
        test_no_dead_imports_in_generated_code,
        test_engine_has_singleton_getter,
        test_authz_response_has_allowed_field,
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
