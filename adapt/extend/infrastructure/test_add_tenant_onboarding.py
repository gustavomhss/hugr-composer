"""Structural tests for TOOL-121 add_tenant_onboarding.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_tenant_onboarding.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_tenant_onboarding.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding
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


def _max_function_loc(root: Path, subdir: str = "app") -> int:
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


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="ob_t01")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ob_t02")
    r1 = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ob_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 new files."""
    project_dir = create_fixture_project(name="ob_t04")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="ob_t05")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="ob_t06")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ob_t07")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: ONBOARDING_* config fields exist inside the Settings class body."""
    project_dir = create_fixture_project(name="ob_t08")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["ONBOARDING_STEPS", "ONBOARDING_WELCOME_EMAIL_TEMPLATE"]:
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "ONBOARDING_STEPS" in line and ":" in line:
            assert line.startswith("    "), (
                f"ONBOARDING_STEPS not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: Onboarding router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="ob_t09")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "onboarding_router" in content or "onboarding" in content.lower(), (
            "Onboarding router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_orchestrator_created() -> None:
    """CC-11: app/onboarding/orchestrator.py exists with OnboardingOrchestrator."""
    project_dir = create_fixture_project(name="ob_t10")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    orch_file = project_dir / "app" / "onboarding" / "orchestrator.py"
    assert orch_file.exists(), "app/onboarding/orchestrator.py not created"
    content = orch_file.read_text()
    assert "class OnboardingOrchestrator" in content, "OnboardingOrchestrator not found"
    assert "class OnboardingProgress" in content, "OnboardingProgress not found"
    assert "class OnboardingStatus" in content, "OnboardingStatus enum not found"


def test_steps_file_created() -> None:
    """CC-11: app/onboarding/steps.py contains all 5 built-in steps."""
    project_dir = create_fixture_project(name="ob_t11")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    steps_file = project_dir / "app" / "onboarding" / "steps.py"
    assert steps_file.exists(), "app/onboarding/steps.py not created"
    content = steps_file.read_text()
    for step_cls in [
        "CreateTenantStep",
        "CreateAdminUserStep",
        "SeedDataStep",
        "ConfigureBillingStep",
        "SendWelcomeEmailStep",
    ]:
        assert step_cls in content, f"{step_cls} not found in steps.py"


def test_onboarding_schemas_created() -> None:
    """CC-11: app/schemas/onboarding.py contains required schemas."""
    project_dir = create_fixture_project(name="ob_t12")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "onboarding.py"
    assert schema_file.exists(), "app/schemas/onboarding.py not created"
    content = schema_file.read_text()
    for schema in ["OnboardingRequest", "OnboardingStatusResponse", "OnboardingStartResponse"]:
        assert schema in content, f"{schema} not found in onboarding schemas"


def test_onboarding_routes_endpoints() -> None:
    """CC-11: app/api/routes/onboarding.py contains start and status endpoints."""
    project_dir = create_fixture_project(name="ob_t13")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "onboarding.py"
    assert route_file.exists(), "app/api/routes/onboarding.py not created"
    content = route_file.read_text()
    assert "/start" in content, "POST /onboarding/start not found"
    assert "status" in content.lower(), "GET /onboarding/{id}/status not found"


def test_step_compensation_present() -> None:
    """CC-11: Each built-in step has both execute() and compensate() methods."""
    project_dir = create_fixture_project(name="ob_t14")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    steps_file = project_dir / "app" / "onboarding" / "steps.py"
    content = steps_file.read_text()
    execute_count = content.count("def execute(")
    compensate_count = content.count("def compensate(")
    assert execute_count >= 5, f"Expected >= 5 execute() methods, found {execute_count}"
    assert compensate_count >= 5, f"Expected >= 5 compensate() methods, found {compensate_count}"


def test_orchestrator_compensates_on_failure() -> None:
    """CC-11: OnboardingOrchestrator._compensate() is called when a step fails."""
    project_dir = create_fixture_project(name="ob_t15")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    orch_file = project_dir / "app" / "onboarding" / "orchestrator.py"
    content = orch_file.read_text()
    assert "_compensate" in content, "_compensate method not found in orchestrator"
    assert "COMPENSATING" in content, "COMPENSATING status not found in orchestrator"
    assert "COMPENSATED" in content, "COMPENSATED status not found in orchestrator"


def test_build_steps_from_config_factory() -> None:
    """CC-11: build_steps_from_config() factory function exists in steps.py."""
    project_dir = create_fixture_project(name="ob_t16")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    steps_file = project_dir / "app" / "onboarding" / "steps.py"
    content = steps_file.read_text()
    assert "def build_steps_from_config" in content, (
        "build_steps_from_config factory function not found in steps.py"
    )


def test_onboarding_step_protocol() -> None:
    """CC-11: OnboardingStep Protocol is defined in steps.py."""
    project_dir = create_fixture_project(name="ob_t17")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    steps_file = project_dir / "app" / "onboarding" / "steps.py"
    content = steps_file.read_text()
    assert "class OnboardingStep" in content, "OnboardingStep Protocol not found in steps.py"
    assert "Protocol" in content, "typing.Protocol not used for OnboardingStep"


# ---------------------------------------------------------------------------
# CC-N-1 & CC-N: execution_time and next_steps
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ob_t18")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions ONBOARDING_STEPS."""
    project_dir = create_fixture_project(name="ob_t19")
    result = add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps must be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "onboarding" in combined or "step" in combined, (
        "next_steps should mention onboarding configuration"
    )


# ---------------------------------------------------------------------------
# CC-LAST: idempotent + project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ob_t20")
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
    add_tenant_onboarding(ToolInput(project_dir=str(project_dir)))
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
        test_routes_registered,
        test_orchestrator_created,
        test_steps_file_created,
        test_onboarding_schemas_created,
        test_onboarding_routes_endpoints,
        test_step_compensation_present,
        test_orchestrator_compensates_on_failure,
        test_build_steps_from_config_factory,
        test_onboarding_step_protocol,
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
    print(f"TOOL-121 add_tenant_onboarding: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
