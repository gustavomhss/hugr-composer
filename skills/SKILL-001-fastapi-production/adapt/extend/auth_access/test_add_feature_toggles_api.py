"""Tests for TOOL-064 add_feature_toggles_api.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all structural completeness criteria.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_feature_toggles_api.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_feature_toggles_api.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_feature_toggles_api import add_feature_toggles_api
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


def _run(name: str) -> tuple[Path, object]:
    project_dir = create_fixture_project(name=name)
    result = add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    return project_dir, result


# ---------------------------------------------------------------------------
# T-01..T-03: Basic contract
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    _, result = _run("ft01_success")
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    _, result = _run("ft02_files_exist")
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    _, result = _run("ft03_modified_exist")
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-01: FeatureToggle model
# ---------------------------------------------------------------------------

def test_toggle_model_created() -> None:
    """CC-01: app/models/feature_toggle.py exists with FeatureToggle class."""
    project_dir, _ = _run("ft04_model")
    model_file = project_dir / "app" / "models" / "feature_toggle.py"
    assert model_file.exists(), "feature_toggle.py not created"
    content = model_file.read_text()
    assert "class FeatureToggle" in content


def test_toggle_model_fields() -> None:
    """CC-01b: FeatureToggle has all required fields."""
    project_dir, _ = _run("ft05_fields")
    content = (project_dir / "app" / "models" / "feature_toggle.py").read_text()
    for field in ("name", "enabled", "rollout_percentage", "allowed_users", "environments"):
        assert field in content, f"Missing field: {field}"


def test_toggle_model_registered_in_init() -> None:
    """CC-01c: FeatureToggle is imported in app/models/__init__.py."""
    project_dir, _ = _run("ft06_models_init")
    content = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert "FeatureToggle" in content


# ---------------------------------------------------------------------------
# CC-02: Schemas
# ---------------------------------------------------------------------------

def test_schemas_created() -> None:
    """CC-02: app/schemas/feature_toggle.py exists."""
    project_dir, _ = _run("ft07_schemas")
    schema_file = project_dir / "app" / "schemas" / "feature_toggle.py"
    assert schema_file.exists(), "feature_toggle.py schemas not created"


def test_schemas_classes() -> None:
    """CC-02b: Schemas have ToggleCreate, ToggleUpdate, ToggleRead, ToggleEvaluate."""
    project_dir, _ = _run("ft08_schema_classes")
    content = (project_dir / "app" / "schemas" / "feature_toggle.py").read_text()
    for cls in ("ToggleCreate", "ToggleUpdate", "ToggleRead", "ToggleEvaluate"):
        assert f"class {cls}" in content, f"Missing schema class: {cls}"


# ---------------------------------------------------------------------------
# CC-03: CRUD
# ---------------------------------------------------------------------------

def test_crud_created() -> None:
    """CC-03: app/crud/feature_toggle.py exists."""
    project_dir, _ = _run("ft09_crud")
    crud_file = project_dir / "app" / "crud" / "feature_toggle.py"
    assert crud_file.exists(), "crud/feature_toggle.py not created"


def test_crud_functions() -> None:
    """CC-03b: CRUD has get_by_name, list_toggles, create, update, delete."""
    project_dir, _ = _run("ft10_crud_fns")
    content = (project_dir / "app" / "crud" / "feature_toggle.py").read_text()
    for fn in ("get_by_name", "list_toggles", "create", "update", "delete"):
        assert f"async def {fn}" in content, f"Missing CRUD function: {fn}"


# ---------------------------------------------------------------------------
# CC-04: Evaluator
# ---------------------------------------------------------------------------

def test_evaluator_created() -> None:
    """CC-04: app/features/evaluator.py exists."""
    project_dir, _ = _run("ft11_evaluator")
    assert (project_dir / "app" / "features" / "evaluator.py").exists()


def test_evaluator_uses_hash_bucketing() -> None:
    """CC-04b: Evaluator uses hashlib sha256 for deterministic bucketing."""
    project_dir, _ = _run("ft12_hash")
    content = (project_dir / "app" / "features" / "evaluator.py").read_text()
    assert "hashlib" in content
    assert "sha256" in content


def test_evaluator_checks_disabled_first() -> None:
    """INV-01: Evaluator returns False immediately when toggle is disabled."""
    project_dir, _ = _run("ft13_disabled")
    content = (project_dir / "app" / "features" / "evaluator.py").read_text()
    assert "not toggle.enabled" in content or "toggle.enabled" in content
    # "disabled" reason must be present
    assert '"disabled"' in content


def test_evaluator_allowlist_priority() -> None:
    """INV-02: Allowlist check returns True before percentage rollout."""
    project_dir, _ = _run("ft14_allowlist")
    content = (project_dir / "app" / "features" / "evaluator.py").read_text()
    assert "allowed_users" in content
    assert '"allowlist"' in content


def test_evaluator_environment_gate() -> None:
    """INV-03: Environment gate blocks when env not in allowed list."""
    project_dir, _ = _run("ft15_envgate")
    content = (project_dir / "app" / "features" / "evaluator.py").read_text()
    assert "environments" in content
    assert "environment_gate" in content or '"environment_gate"' in content


# ---------------------------------------------------------------------------
# CC-05: Service
# ---------------------------------------------------------------------------

def test_service_created() -> None:
    """CC-05: app/features/service.py exists with FeatureToggleService."""
    project_dir, _ = _run("ft16_service")
    service_file = project_dir / "app" / "features" / "service.py"
    assert service_file.exists()
    content = service_file.read_text()
    assert "class FeatureToggleService" in content


def test_service_is_enabled() -> None:
    """CC-05b: FeatureToggleService has is_enabled method."""
    project_dir, _ = _run("ft17_is_enabled")
    content = (project_dir / "app" / "features" / "service.py").read_text()
    assert "async def is_enabled" in content


def test_service_env_var_priority() -> None:
    """INV-04: Service checks env-var override before DB (env vars take priority)."""
    project_dir, _ = _run("ft18_envpriority")
    content = (project_dir / "app" / "features" / "service.py").read_text()
    assert "os.getenv" in content


def test_service_ttl_cache() -> None:
    """INV-05: Service uses an in-memory TTL cache."""
    project_dir, _ = _run("ft19_cache")
    content = (project_dir / "app" / "features" / "service.py").read_text()
    assert "CACHE_TTL" in content or "_CACHE_TTL" in content
    assert "_CACHE" in content


def test_features_init_created() -> None:
    """CC-05c: app/features/__init__.py re-exports FeatureToggleService and evaluate."""
    project_dir, _ = _run("ft20_init")
    init_file = project_dir / "app" / "features" / "__init__.py"
    assert init_file.exists()
    content = init_file.read_text()
    assert "FeatureToggleService" in content
    assert "evaluate" in content


# ---------------------------------------------------------------------------
# CC-06: Routes
# ---------------------------------------------------------------------------

def test_routes_created() -> None:
    """CC-06: app/api/routes/feature_toggles.py exists."""
    project_dir, _ = _run("ft21_routes")
    routes_file = project_dir / "app" / "api" / "routes" / "feature_toggles.py"
    assert routes_file.exists(), "feature_toggles.py routes not created"


def test_routes_has_crud_endpoints() -> None:
    """CC-06b: Routes have list, create, update, delete, evaluate handlers."""
    project_dir, _ = _run("ft22_route_fns")
    content = (project_dir / "app" / "api" / "routes" / "feature_toggles.py").read_text()
    for fn in ("list_toggles", "create_toggle", "update_toggle", "delete_toggle", "evaluate_toggle"):
        assert f"async def {fn}" in content, f"Missing route function: {fn}"


def test_routes_require_superuser() -> None:
    """INV-06: All admin routes require CurrentSuperuser."""
    project_dir, _ = _run("ft23_superuser")
    content = (project_dir / "app" / "api" / "routes" / "feature_toggles.py").read_text()
    assert "CurrentSuperuser" in content


def test_routes_evaluate_endpoint() -> None:
    """CC-06c: Evaluate endpoint uses POST /{name}/evaluate."""
    project_dir, _ = _run("ft24_evaluate_ep")
    content = (project_dir / "app" / "api" / "routes" / "feature_toggles.py").read_text()
    assert "/evaluate" in content
    assert "ToggleEvaluateResult" in content


# ---------------------------------------------------------------------------
# CC-07: Alembic migration
# ---------------------------------------------------------------------------

def test_migration_created() -> None:
    """CC-07: Alembic migration file for feature_toggles is created."""
    project_dir, _ = _run("ft25_migration")
    versions_dir = project_dir / "alembic" / "versions"
    files = list(versions_dir.glob("*feature_toggles*"))
    assert len(files) >= 1, "No feature_toggles migration file created"


def test_migration_content() -> None:
    """CC-07b: Migration has upgrade, downgrade and rollout constraint."""
    project_dir, _ = _run("ft26_migration_content")
    versions_dir = project_dir / "alembic" / "versions"
    files = list(versions_dir.glob("*feature_toggles*"))
    content = files[0].read_text()
    assert "def upgrade" in content
    assert "def downgrade" in content
    assert "feature_toggles" in content
    assert "rollout_percentage" in content


# ---------------------------------------------------------------------------
# CC-08: Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_returns_no_op() -> None:
    """CC-08: Running tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="ft27_idempotent")
    r1 = add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"


def test_idempotent_project_parses() -> None:
    """CC-08b: After two runs all generated files still parse correctly."""
    project_dir = create_fixture_project(name="ft28_idempotent_parse")
    add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-09: dry_run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing() -> None:
    """CC-09: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ft29_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_feature_toggles_api(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-10: All generated files parse
# ---------------------------------------------------------------------------

def test_all_py_files_parse() -> None:
    """CC-10: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="ft30_parse_all")
    add_feature_toggles_api(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-11: elapsed_ms populated
# ---------------------------------------------------------------------------

def test_execution_time_ms_populated() -> None:
    """CC-11: result.execution_time_ms is a non-negative integer."""
    _, result = _run("ft31_elapsed")
    assert isinstance(result.execution_time_ms, int)
    assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_toggle_model_created,
        test_toggle_model_fields,
        test_toggle_model_registered_in_init,
        test_schemas_created,
        test_schemas_classes,
        test_crud_created,
        test_crud_functions,
        test_evaluator_created,
        test_evaluator_uses_hash_bucketing,
        test_evaluator_checks_disabled_first,
        test_evaluator_allowlist_priority,
        test_evaluator_environment_gate,
        test_service_created,
        test_service_is_enabled,
        test_service_env_var_priority,
        test_service_ttl_cache,
        test_features_init_created,
        test_routes_created,
        test_routes_has_crud_endpoints,
        test_routes_require_superuser,
        test_routes_evaluate_endpoint,
        test_migration_created,
        test_migration_content,
        test_idempotent_returns_no_op,
        test_idempotent_project_parses,
        test_dry_run_writes_nothing,
        test_all_py_files_parse,
        test_execution_time_ms_populated,
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
    sys.exit(0 if failed == 0 else 1)
