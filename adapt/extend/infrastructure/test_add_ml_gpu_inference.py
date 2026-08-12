"""Tests for TOOL-069 add_ml_gpu_inference.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_ml_gpu_inference.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_ml_gpu_inference.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_ml_gpu_inference import add_ml_gpu_inference
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
    project_dir = create_fixture_project(name="gpu_t01")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="gpu_t02")
    r1 = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="gpu_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 5 new files (gpu pkg init + 3 modules + gpu_status route)."""
    project_dir = create_fixture_project(name="gpu_t04")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    py_created = [p for p in result.files_created if p.endswith(".py")]
    assert len(py_created) >= 5, (
        f"Expected >= 5 .py files_created, got {len(py_created)}: {py_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config + routes __init__)."""
    project_dir = create_fixture_project(name="gpu_t05")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: "
        f"{result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="gpu_t06")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_execution_time_on_invalid_dir() -> None:
    """execution_time_ms is present even on validation error."""
    result = add_ml_gpu_inference(ToolInput(project_dir="/nonexistent/path/abc"))
    assert result.status == "error"
    assert result.execution_time_ms >= 0, "execution_time_ms must be set on error path"


def test_next_steps_present() -> None:
    """next_steps is non-empty and mentions torch."""
    project_dir = create_fixture_project(name="gpu_t07")
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "torch" in combined, "next_steps should mention torch installation"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="gpu_t08")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="gpu_t09")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_torch_not_at_top_level_in_any_generated_file() -> None:
    """torch must NOT appear in top-level (module-level) imports in any app/ .py file.

    This is INV-04 / QS-04: lazy imports only.  The test walks the AST of
    every generated file and inspects only module-level statements.
    """
    project_dir = create_fixture_project(name="gpu_t10")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))

    app_dir = project_dir / "app"
    violations: list[str] = []
    for py_file in sorted(app_dir.rglob("*.py")):
        source = py_file.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:  # Only top-level statements
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "torch" or alias.name.startswith("torch."):
                        violations.append(
                            f"{py_file.relative_to(project_dir)}:"
                            f"{node.lineno}: import torch"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "torch" or node.module.startswith("torch."):
                    violations.append(
                        f"{py_file.relative_to(project_dir)}:"
                        f"{node.lineno}: from torch import ..."
                    )

    assert not violations, (
        "torch found at module top-level in the following files:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_config_fields_patched() -> None:
    """All 4 GPU settings fields exist inside the Settings class (4-space indent)."""
    project_dir = create_fixture_project(name="gpu_t11")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("GPU_ENABLED", "GPU_DEVICE_ID", "GPU_MEMORY_THRESHOLD_PCT",
                  "GPU_MIXED_PRECISION"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class body (4-space indent)
    for line in content.splitlines():
        if "GPU_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"GPU_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_routes_registered() -> None:
    """gpu_status router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="gpu_t12")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists(), "app/routes/__init__.py not found"
    content = routes_init.read_text()
    assert "gpu_status" in content.lower(), (
        "gpu_status router not registered in app/routes/__init__.py"
    )


# ---------------------------------------------------------------------------
# Category C — Domain-specific file existence and content
# ---------------------------------------------------------------------------

def test_device_module_created() -> None:
    """app/ml/gpu/device.py exists with DeviceManager class."""
    project_dir = create_fixture_project(name="gpu_t13")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    device_file = project_dir / "app" / "ml" / "gpu" / "device.py"
    assert device_file.exists(), "app/ml/gpu/device.py not created"
    content = device_file.read_text()
    assert "DeviceManager" in content, "DeviceManager not found in device.py"
    assert "get_device" in content, "get_device method not found in device.py"
    assert "memory_stats" in content, "memory_stats method not found in device.py"


def test_memory_guard_created() -> None:
    """app/ml/gpu/memory_guard.py exists with MemoryGuard class."""
    project_dir = create_fixture_project(name="gpu_t14")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    mg_file = project_dir / "app" / "ml" / "gpu" / "memory_guard.py"
    assert mg_file.exists(), "app/ml/gpu/memory_guard.py not created"
    content = mg_file.read_text()
    assert "MemoryGuard" in content, "MemoryGuard not found in memory_guard.py"
    assert "def check" in content, "check method not found in memory_guard.py"


def test_inference_module_created() -> None:
    """app/ml/gpu/inference.py exists with GPUPredictor class."""
    project_dir = create_fixture_project(name="gpu_t15")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    inf_file = project_dir / "app" / "ml" / "gpu" / "inference.py"
    assert inf_file.exists(), "app/ml/gpu/inference.py not created"
    content = inf_file.read_text()
    assert "GPUPredictor" in content, "GPUPredictor not found in inference.py"
    assert "def predict" in content, "predict method not found in inference.py"
    assert "autocast" in content, "autocast not referenced in inference.py"


def test_gpu_init_has_reexports() -> None:
    """app/ml/gpu/__init__.py re-exports DeviceManager, GPUPredictor, MemoryGuard."""
    project_dir = create_fixture_project(name="gpu_t16")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    gpu_init = project_dir / "app" / "ml" / "gpu" / "__init__.py"
    assert gpu_init.exists(), "app/ml/gpu/__init__.py not created"
    content = gpu_init.read_text()
    assert "DeviceManager" in content
    assert "GPUPredictor" in content
    assert "MemoryGuard" in content


def test_gpu_status_route_created() -> None:
    """app/api/routes/gpu_status.py exists with GET /ml/gpu/status."""
    project_dir = create_fixture_project(name="gpu_t17")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    status_file = project_dir / "app" / "api" / "routes" / "gpu_status.py"
    assert status_file.exists(), "app/api/routes/gpu_status.py not created"
    content = status_file.read_text()
    assert "router" in content, "APIRouter not found in gpu_status.py"
    assert "/status" in content, "GET /status endpoint not found in gpu_status.py"


def test_requirements_not_modified() -> None:
    """requirements.txt is NOT modified (torch is user-provided)."""
    project_dir = create_fixture_project(name="gpu_t18")
    req_before = (project_dir / "requirements.txt").read_text()
    result = add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    req_after = (project_dir / "requirements.txt").read_text()
    assert req_before == req_after, "requirements.txt must not be modified"
    # requirements.txt should not appear in files_modified
    for path in result.files_modified:
        assert "requirements.txt" not in path, (
            "requirements.txt must not appear in files_modified"
        )


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="gpu_t19")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_memory_guard_has_threshold() -> None:
    """MemoryGuard uses GPU_MEMORY_THRESHOLD_PCT from settings."""
    project_dir = create_fixture_project(name="gpu_t20")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    mg_file = project_dir / "app" / "ml" / "gpu" / "memory_guard.py"
    content = mg_file.read_text()
    assert "GPU_MEMORY_THRESHOLD_PCT" in content, (
        "GPU_MEMORY_THRESHOLD_PCT not referenced in memory_guard.py"
    )


def test_device_cpu_fallback_documented() -> None:
    """DeviceManager CPU fallback is described in device.py docstring/comments."""
    project_dir = create_fixture_project(name="gpu_t21")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    device_file = project_dir / "app" / "ml" / "gpu" / "device.py"
    content = device_file.read_text()
    assert "cpu" in content.lower(), "CPU fallback not mentioned in device.py"
    # Accept any of: "fallback", "fall back", "falling back"
    assert any(
        phrase in content.lower()
        for phrase in ("fallback", "fall back", "falling back", "falls back")
    ), "Fallback to CPU not described in device.py"


def test_gpu_status_endpoint_returns_available_key() -> None:
    """gpu_status.py response includes 'available' key (per spec contract)."""
    project_dir = create_fixture_project(name="gpu_t22")
    add_ml_gpu_inference(ToolInput(project_dir=str(project_dir)))
    status_file = project_dir / "app" / "api" / "routes" / "gpu_status.py"
    content = status_file.read_text()
    assert '"available"' in content or "'available'" in content, (
        "gpu_status.py response must include 'available' key"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def _run_all() -> None:
    tests = [
        ("test_success_status", test_success_status),
        ("test_idempotent", test_idempotent),
        ("test_dry_run", test_dry_run),
        ("test_files_created_count", test_files_created_count),
        ("test_files_modified_count", test_files_modified_count),
        ("test_execution_time_recorded", test_execution_time_recorded),
        ("test_execution_time_on_invalid_dir", test_execution_time_on_invalid_dir),
        ("test_next_steps_present", test_next_steps_present),
        ("test_all_py_parse", test_all_py_parse),
        ("test_no_function_over_50_loc", test_no_function_over_50_loc),
        ("test_torch_not_at_top_level_in_any_generated_file",
         test_torch_not_at_top_level_in_any_generated_file),
        ("test_config_fields_patched", test_config_fields_patched),
        ("test_routes_registered", test_routes_registered),
        ("test_device_module_created", test_device_module_created),
        ("test_memory_guard_created", test_memory_guard_created),
        ("test_inference_module_created", test_inference_module_created),
        ("test_gpu_init_has_reexports", test_gpu_init_has_reexports),
        ("test_gpu_status_route_created", test_gpu_status_route_created),
        ("test_requirements_not_modified", test_requirements_not_modified),
        ("test_idempotent_project_still_parses", test_idempotent_project_still_parses),
        ("test_memory_guard_has_threshold", test_memory_guard_has_threshold),
        ("test_device_cpu_fallback_documented", test_device_cpu_fallback_documented),
        ("test_gpu_status_endpoint_returns_available_key",
         test_gpu_status_endpoint_returns_available_key),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {name}: {exc}")
            traceback.print_exc()
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"TOOL-069 STRUCTURAL: {passed}/{total} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    _run_all()
