"""Tests for TOOL-068 add_ml_model_server.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_ml_model_server.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_ml_model_server.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_model_server import add_ml_model_server
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* sorted alphabetically."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py file under *root* fails ast.parse."""
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function/method in the given subdir."""
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
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ml_t02")
    r1 = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ml_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 6 new files (ml pkg, schemas, routes)."""
    project_dir = create_fixture_project(name="ml_t04")
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="ml_t05")
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
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
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ml_t07")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected ML_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="ml_t08")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("ML_MODEL_DIR", "ML_DEFAULT_MODEL", "ML_MAX_BATCH_SIZE", "ML_PREDICTION_TIMEOUT_MS"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent, CC-08)
    for line in content.splitlines():
        if "ML_MODEL_DIR" in line and ":" in line:
            assert line.startswith("    "), (
                f"ML_MODEL_DIR not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_routes_registered() -> None:
    """ML HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="ml_t09")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "ml_router" in content, "ML router not registered in routes __init__"
        assert "include_router" in content, "include_router call missing in routes __init__"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ml_t10")
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# Category C — Domain-specific: app/ml/ package
# ---------------------------------------------------------------------------

def test_ml_registry_created() -> None:
    """app/ml/registry.py exists with ModelRegistry and get_registry."""
    project_dir = create_fixture_project(name="ml_t11")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "ml" / "registry.py"
    assert registry_file.exists(), "app/ml/registry.py not created"
    content = registry_file.read_text()
    assert "class ModelRegistry" in content, "ModelRegistry class not found"
    assert "def get_registry" in content, "get_registry function not found"
    assert "def register" in content, "register method not found"
    assert "def get" in content, "get method not found"
    assert "def list_models" in content, "list_models method not found"


def test_ml_loader_created() -> None:
    """app/ml/loader.py exists with load_model function."""
    project_dir = create_fixture_project(name="ml_t12")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    loader_file = project_dir / "app" / "ml" / "loader.py"
    assert loader_file.exists(), "app/ml/loader.py not created"
    content = loader_file.read_text()
    assert "def load_model" in content, "load_model function not found"


def test_ml_predictor_created() -> None:
    """app/ml/predictor.py exists with Predictor class and predict methods."""
    project_dir = create_fixture_project(name="ml_t13")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    predictor_file = project_dir / "app" / "ml" / "predictor.py"
    assert predictor_file.exists(), "app/ml/predictor.py not created"
    content = predictor_file.read_text()
    assert "class Predictor" in content, "Predictor class not found"
    assert "async def predict" in content, "predict method not found"
    assert "async def predict_batch" in content, "predict_batch method not found"


def test_ml_schemas_created() -> None:
    """app/schemas/ml.py exists with PredictionRequest and PredictionResponse."""
    project_dir = create_fixture_project(name="ml_t14")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "ml.py"
    assert schema_file.exists(), "app/schemas/ml.py not created"
    content = schema_file.read_text()
    assert "class PredictionRequest" in content, "PredictionRequest not found"
    assert "class PredictionResponse" in content, "PredictionResponse not found"
    assert "class BatchPredictionRequest" in content, "BatchPredictionRequest not found"
    assert "class BatchPredictionResponse" in content, "BatchPredictionResponse not found"


def test_ml_routes_created() -> None:
    """app/api/routes/ml.py exists with all four endpoints."""
    project_dir = create_fixture_project(name="ml_t15")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "ml.py"
    assert routes_file.exists(), "app/api/routes/ml.py not created"
    content = routes_file.read_text()
    assert "POST /ml/predict" in content or "router.post" in content, "POST /predict not found"
    assert "predict_batch" in content, "predict_batch route not found"
    assert "list_models" in content, "GET /models not found"
    assert "model_health" in content, "GET /models/{name}/health not found"


def test_ml_init_re_exports() -> None:
    """app/ml/__init__.py re-exports ModelRegistry, Predictor, load_model, get_registry."""
    project_dir = create_fixture_project(name="ml_t16")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "ml" / "__init__.py"
    assert init_file.exists(), "app/ml/__init__.py not created"
    content = init_file.read_text()
    assert "ModelRegistry" in content, "ModelRegistry not re-exported from app/ml/__init__.py"
    assert "Predictor" in content, "Predictor not re-exported from app/ml/__init__.py"
    assert "get_registry" in content, "get_registry not re-exported from app/ml/__init__.py"
    assert "load_model" in content, "load_model not re-exported from app/ml/__init__.py"


def test_main_patched() -> None:
    """app/main.py references get_registry after tool application."""
    project_dir = create_fixture_project(name="ml_t17")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "get_registry" in content, "get_registry not referenced in main.py"


def test_next_steps_present() -> None:
    """next_steps guides developer to register a model."""
    project_dir = create_fixture_project(name="ml_t18")
    result = add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "register" in combined, "next_steps should mention model registration"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ml_t19")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_lazy_imports_in_loader() -> None:
    """app/ml/loader.py must NOT have torch/sklearn/onnxruntime at top-level."""
    project_dir = create_fixture_project(name="ml_t20")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    loader_file = project_dir / "app" / "ml" / "loader.py"
    assert loader_file.exists()
    tree = ast.parse(loader_file.read_text())
    ml_libs = {"torch", "sklearn", "onnxruntime", "numpy", "tensorflow", "joblib", "ort"}
    for node in tree.body:  # top-level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                for lib in ml_libs:
                    assert lib not in alias.name, (
                        f"Top-level import of ML lib '{alias.name}' in loader.py (must be lazy)"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for lib in ml_libs:
                assert lib not in node.module, (
                    f"Top-level 'from {node.module} import ...' of ML lib in loader.py (must be lazy)"
                )


def test_predictor_uses_asyncio_wait_for() -> None:
    """app/ml/predictor.py uses asyncio.wait_for for timeout enforcement."""
    project_dir = create_fixture_project(name="ml_t21")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    predictor_file = project_dir / "app" / "ml" / "predictor.py"
    content = predictor_file.read_text()
    assert "asyncio.wait_for" in content, "asyncio.wait_for not used in predictor.py"


def test_batch_route_checks_max_batch_size() -> None:
    """app/api/routes/ml.py enforces ML_MAX_BATCH_SIZE for batch endpoint."""
    project_dir = create_fixture_project(name="ml_t22")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "ml.py"
    content = routes_file.read_text()
    assert "ML_MAX_BATCH_SIZE" in content, "ML_MAX_BATCH_SIZE not checked in routes"


def test_model_health_returns_error_count() -> None:
    """app/api/routes/ml.py health endpoint references error_count."""
    project_dir = create_fixture_project(name="ml_t23")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "ml.py"
    content = routes_file.read_text()
    assert "error_count" in content, "error_count not referenced in health endpoint"


def test_registry_update_stats_method() -> None:
    """app/ml/registry.py has update_stats method for tracking latency and errors."""
    project_dir = create_fixture_project(name="ml_t24")
    add_ml_model_server(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "ml" / "registry.py"
    content = registry_file.read_text()
    assert "def update_stats" in content, "update_stats method not found in registry.py"


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
        test_execution_time_recorded,
        test_ml_registry_created,
        test_ml_loader_created,
        test_ml_predictor_created,
        test_ml_schemas_created,
        test_ml_routes_created,
        test_ml_init_re_exports,
        test_main_patched,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_lazy_imports_in_loader,
        test_predictor_uses_asyncio_wait_for,
        test_batch_route_checks_max_batch_size,
        test_model_health_returns_error_count,
        test_registry_update_stats_method,
    ]

    passed = 0
    failed = 0
    failures: list[str] = []

    for fn in tests:
        name = fn.__name__
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {name}: {exc}")
            failures.append(f"{name}: {exc}")
            failed += 1

    total = passed + failed
    status = "PASS" if failed == 0 else "FAIL"

    contract = {
        "tool": "TOOL-068 add_ml_model_server",
        "test_file": "test_add_ml_model_server.py",
        "total": total,
        "passed": passed,
        "failed": failed,
        "status": status,
        "failures": failures,
    }

    print(f"\n{'='*60}")
    print(f"TOOL-068 STRUCTURAL: {passed}/{total} passed")
    print("\nDelivery contract JSON:")
    print(json.dumps(contract, indent=2))

    if failed:
        sys.exit(1)
