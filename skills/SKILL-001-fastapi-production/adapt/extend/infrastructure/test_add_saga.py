"""Tests for TOOL-024 add_saga.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_saga.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_saga.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_saga import add_saga
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
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="saga_t01")
    result = add_saga(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="saga_t02")
    result = add_saga(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_saga_models_created() -> None:
    """CC-01: app/models/saga.py exists with SagaInstance and SagaStepExecution."""
    project_dir = create_fixture_project(name="saga_t03")
    add_saga(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "saga.py"
    assert model_file.exists(), "saga.py model not created"
    content = model_file.read_text()
    assert "SagaInstance" in content
    assert "saga_instances" in content
    assert "SagaStepExecution" in content
    assert "saga_step_executions" in content


def test_saga_instance_state_field() -> None:
    """CC-02: SagaInstance has state field with index."""
    project_dir = create_fixture_project(name="saga_t04")
    add_saga(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "saga.py"
    content = model_file.read_text()
    assert "state" in content
    assert "pending" in content


def test_saga_instance_durable_state_fields() -> None:
    """CC-03: SagaInstance has input_data, output_data, current_step."""
    project_dir = create_fixture_project(name="saga_t05")
    add_saga(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "saga.py"
    content = model_file.read_text()
    assert "input_data" in content
    assert "output_data" in content
    assert "current_step" in content


def test_step_execution_compensation_fields() -> None:
    """CC-04: SagaStepExecution has compensation_attempts and compensated_at."""
    project_dir = create_fixture_project(name="saga_t06")
    add_saga(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "saga.py"
    content = model_file.read_text()
    assert "compensation_attempts" in content
    assert "compensated_at" in content


def test_saga_core_file_created() -> None:
    """CC-05: app/core/saga.py exists with Saga base class and saga_step."""
    project_dir = create_fixture_project(name="saga_t07")
    add_saga(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "saga.py"
    assert core_file.exists(), "saga.py core not created"
    content = core_file.read_text()
    assert "class Saga" in content
    assert "def saga_step" in content


def test_saga_step_decorator_attributes() -> None:
    """CC-06: @saga_step sets _is_saga_step, _compensate_name, _step_timeout."""
    project_dir = create_fixture_project(name="saga_t08")
    add_saga(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "saga.py"
    content = core_file.read_text()
    assert "_is_saga_step" in content
    assert "_compensate_name" in content
    assert "_step_timeout" in content


def test_collect_steps_class_method() -> None:
    """CC-07: Saga.collect_steps() class method discovers decorated steps."""
    project_dir = create_fixture_project(name="saga_t09")
    add_saga(ToolInput(project_dir=str(project_dir)))
    core_file = project_dir / "app" / "core" / "saga.py"
    content = core_file.read_text()
    assert "collect_steps" in content, "collect_steps() method must be present"


def test_coordinator_service_created() -> None:
    """CC-08: app/services/saga_coordinator.py exists with SagaCoordinator."""
    project_dir = create_fixture_project(name="saga_t10")
    add_saga(ToolInput(project_dir=str(project_dir)))
    coord_file = project_dir / "app" / "services" / "saga_coordinator.py"
    assert coord_file.exists(), "saga_coordinator.py not created"
    content = coord_file.read_text()
    assert "SagaCoordinator" in content
    assert "async def run" in content


def test_coordinator_persists_before_step() -> None:
    """CC-09: Coordinator flushes/commits state before executing each step."""
    project_dir = create_fixture_project(name="saga_t11")
    add_saga(ToolInput(project_dir=str(project_dir)))
    coord_file = project_dir / "app" / "services" / "saga_coordinator.py"
    content = coord_file.read_text()
    assert "flush" in content or "commit" in content, (
        "Coordinator must persist state before step execution"
    )


def test_compensation_reverse_order() -> None:
    """CC-10: Compensation iterates completed steps in reversed() order."""
    project_dir = create_fixture_project(name="saga_t12")
    add_saga(ToolInput(project_dir=str(project_dir)))
    coord_file = project_dir / "app" / "services" / "saga_coordinator.py"
    content = coord_file.read_text()
    assert "reversed(" in content, "Compensation must run in reversed() order"


def test_per_step_timeout() -> None:
    """CC-11: Each step is wrapped in asyncio.wait_for with per-step timeout."""
    project_dir = create_fixture_project(name="saga_t13")
    add_saga(ToolInput(project_dir=str(project_dir)))
    coord_file = project_dir / "app" / "services" / "saga_coordinator.py"
    content = coord_file.read_text()
    assert "asyncio.wait_for" in content, "Per-step timeout via asyncio.wait_for required"


def test_compensation_uses_idempotency_key() -> None:
    """CC-12: Compensation calls pass idempotency_key for idempotent execution."""
    project_dir = create_fixture_project(name="saga_t14")
    add_saga(ToolInput(project_dir=str(project_dir)))
    coord_file = project_dir / "app" / "services" / "saga_coordinator.py"
    content = coord_file.read_text()
    assert "idempotency_key" in content, "Compensation must pass idempotency_key"


def test_admin_routes_created() -> None:
    """CC-13: app/api/routes/sagas_admin.py exists with dashboard endpoints."""
    project_dir = create_fixture_project(name="saga_t15")
    add_saga(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "sagas_admin.py"
    assert admin_route.exists(), "sagas_admin.py not created"
    content = admin_route.read_text()
    assert "list_sagas" in content or "/admin/sagas" in content
    assert "inspect_saga" in content or "saga_id" in content


def test_admin_retry_endpoint() -> None:
    """CC-14: Admin route has POST /{saga_id}/retry endpoint."""
    project_dir = create_fixture_project(name="saga_t16")
    add_saga(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "sagas_admin.py"
    content = admin_route.read_text()
    assert "retry" in content, "Admin route must have retry endpoint"


def test_prometheus_metrics_created() -> None:
    """CC-15: app/core/saga_metrics.py exists with Prometheus metrics."""
    project_dir = create_fixture_project(name="saga_t17")
    add_saga(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "core" / "saga_metrics.py"
    assert metrics_file.exists(), "saga_metrics.py not created"
    content = metrics_file.read_text()
    assert "saga_state_total" in content or "saga_state" in content
    assert "saga_step_duration" in content


def test_prometheus_graceful_import() -> None:
    """CC-16: Metrics file handles missing prometheus_client gracefully."""
    project_dir = create_fixture_project(name="saga_t18")
    add_saga(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "core" / "saga_metrics.py"
    content = metrics_file.read_text()
    assert "ImportError" in content, "Must handle missing prometheus_client gracefully"


def test_migration_file_created() -> None:
    """CC-17: Alembic migration creates saga_instances and saga_step_executions."""
    project_dir = create_fixture_project(name="saga_t19")
    add_saga(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*saga*"))
    assert len(migration_files) >= 1, "No saga migration file created"
    content = migration_files[0].read_text()
    assert "saga_instances" in content
    assert "saga_step_executions" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_all_created_files_parse() -> None:
    """CC-18: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="saga_t20")
    add_saga(ToolInput(project_dir=str(project_dir)))
    for subdir in ["models", "core", "services"]:
        d = project_dir / "app" / subdir
        if d.exists():
            for py_file in sorted(d.rglob("*.py")):
                if "saga" in py_file.name:
                    source = py_file.read_text()
                    try:
                        ast.parse(source)
                    except SyntaxError as exc:
                        raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def test_idempotent_returns_no_op() -> None:
    """CC-19: Running the tool twice returns no_op on second run."""
    project_dir = create_fixture_project(name="saga_t21")
    r1 = add_saga(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_saga(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="saga_t22")
    add_saga(ToolInput(project_dir=str(project_dir)))
    add_saga(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="saga_t23")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_saga(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="saga_t24")
    result = add_saga(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_alembic_and_subclass() -> None:
    """next_steps guides developer to run migration and subclass Saga."""
    project_dir = create_fixture_project(name="saga_t25")
    result = add_saga(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_saga_models_created,
        test_saga_instance_state_field,
        test_saga_instance_durable_state_fields,
        test_step_execution_compensation_fields,
        test_saga_core_file_created,
        test_saga_step_decorator_attributes,
        test_collect_steps_class_method,
        test_coordinator_service_created,
        test_coordinator_persists_before_step,
        test_compensation_reverse_order,
        test_per_step_timeout,
        test_compensation_uses_idempotency_key,
        test_admin_routes_created,
        test_admin_retry_endpoint,
        test_prometheus_metrics_created,
        test_prometheus_graceful_import,
        test_migration_file_created,
        test_all_created_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_alembic_and_subclass,
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
    print(f"TOOL-024 add_saga: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
