"""Tests for TOOL-070 add_ml_model_registry.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_ml_model_registry.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_ml_model_registry.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_model_registry import add_ml_model_registry
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


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="ml_t01")
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ml_t02")
    r1 = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ml_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files."""
    project_dir = create_fixture_project(name="ml_t04")
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init, routes init)."""
    project_dir = create_fixture_project(name="ml_t05")
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="ml_t06")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ml_t07")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """ML registry config fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="ml_t08")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("ML_REGISTRY_DEFAULT_FRAMEWORK", "ML_REGISTRY_ARTIFACT_BASE_PATH"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent (fields inside Settings class body)
    for line in content.splitlines():
        if "ML_REGISTRY_DEFAULT_FRAMEWORK" in line and ":" in line:
            assert line.startswith("    "), (
                f"ML_REGISTRY_DEFAULT_FRAMEWORK not inside class body: {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """MLModel is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="ml_t09")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "MLModel" in content, "MLModel not registered in models __init__"


def test_routes_registered() -> None:
    """ML registry router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="ml_t10")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "ml_registry" in content.lower(), (
            "ml_registry router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_ml_model_created() -> None:
    """app/models/ml_model.py exists with MLModel class."""
    project_dir = create_fixture_project(name="ml_t11")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "ml_model.py"
    assert model_file.exists(), "app/models/ml_model.py not created"
    content = model_file.read_text()
    assert "class MLModel" in content, "MLModel class not found"


def test_ml_model_status_field() -> None:
    """MLModel has a status column and an artifact_path column."""
    project_dir = create_fixture_project(name="ml_t12")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "ml_model.py").read_text()
    assert "status" in content, "status column not found in MLModel"
    assert "artifact_path" in content, "artifact_path column not found in MLModel"


def test_schemas_created() -> None:
    """app/schemas/ml_model.py with all four schemas."""
    project_dir = create_fixture_project(name="ml_t13")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "ml_model.py"
    assert schema_file.exists(), "app/schemas/ml_model.py not created"
    content = schema_file.read_text()
    for cls in ("MLModelCreate", "MLModelRead", "MLModelPromote", "MLModelCompare"):
        assert cls in content, f"Schema class {cls} not found"


def test_crud_created_with_helpers() -> None:
    """app/crud/ml_model.py exists with ≥7 async helpers."""
    project_dir = create_fixture_project(name="ml_t14")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "ml_model.py"
    assert crud_file.exists(), "app/crud/ml_model.py not created"
    content = crud_file.read_text()
    fn_count = content.count("async def ")
    assert fn_count >= 7, f"Expected >= 7 CRUD helpers, found {fn_count}"


def test_registry_service_created() -> None:
    """app/ml/registry_service.py exists with RegistryService class."""
    project_dir = create_fixture_project(name="ml_t15")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    svc_file = project_dir / "app" / "ml" / "registry_service.py"
    assert svc_file.exists(), "app/ml/registry_service.py not created"
    content = svc_file.read_text()
    assert "class RegistryService" in content, "RegistryService class not found"
    for method in ("register_model", "promote_to_production", "rollback_to_previous",
                   "get_active_model", "ab_split"):
        assert method in content, f"RegistryService.{method} not found"


def test_routes_created() -> None:
    """app/api/routes/ml_registry.py has all 7 endpoints."""
    project_dir = create_fixture_project(name="ml_t16")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "ml_registry.py"
    assert route_file.exists(), "app/api/routes/ml_registry.py not created"
    content = route_file.read_text()
    for path in ("/ml/models", "promote", "rollback", "ab-test", "compare"):
        assert path in content, f"Route path '{path}' not found in ml_registry.py"


def test_migration_created() -> None:
    """Alembic migration file for ml_models exists and chains to head."""
    project_dir = create_fixture_project(name="ml_t17")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    mig_file = versions_dir / "add_ml_model_registry.py"
    assert mig_file.exists(), "add_ml_model_registry.py migration not created"
    content = mig_file.read_text()
    assert "ml_models" in content, "ml_models table not referenced in migration"
    assert "down_revision" in content, "down_revision not set in migration"
    assert "None" not in content.split("down_revision")[1][:30], (
        "down_revision must chain to head, not None"
    )


def test_no_ml_framework_imports() -> None:
    """No ML framework (torch, sklearn, etc.) imported at top-level in any generated file."""
    project_dir = create_fixture_project(name="ml_t18")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    forbidden = {"torch", "sklearn", "tensorflow", "keras", "xgboost", "lightgbm"}
    app_dir = project_dir / "app"
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for child in ast.iter_child_nodes(tree):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden, (
                        f"ML framework '{top}' imported at top-level in {py_file}"
                    )
            elif isinstance(child, ast.ImportFrom) and child.module:
                top = child.module.split(".")[0]
                assert top not in forbidden, (
                    f"ML framework '{top}' imported at top-level in {py_file}"
                )


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ml_t19")
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """result.next_steps is non-empty and mentions alembic upgrade head."""
    project_dir = create_fixture_project(name="ml_t20")
    result = add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps should be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic upgrade head"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ml_t21")
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_requirements_unchanged() -> None:
    """requirements.txt is NOT modified (no new deps added)."""
    project_dir = create_fixture_project(name="ml_t22")
    req_before = (project_dir / "requirements.txt").read_text()
    add_ml_model_registry(ToolInput(project_dir=str(project_dir)))
    req_after = (project_dir / "requirements.txt").read_text()
    assert req_before == req_after, (
        "requirements.txt must not be modified — ML registry adds no new packages"
    )


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
        test_models_init_patched,
        test_routes_registered,
        test_ml_model_created,
        test_ml_model_status_field,
        test_schemas_created,
        test_crud_created_with_helpers,
        test_registry_service_created,
        test_routes_created,
        test_migration_created,
        test_no_ml_framework_imports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_requirements_unchanged,
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
    print(f"TOOL-070 add_ml_model_registry: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
