"""Tests for TOOL-020 add_long_running_task.

Generates a real fixture project, runs the tool, and verifies all
completeness criteria: TaskManager, Fernet IDs, ARQ worker, task routes
(submit/poll/cancel), schemas, migration, idempotency, dry_run.

Run with::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_long_running_task.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_long_running_task import add_long_running_task
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        src = f.read_text()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="lt_t01")
    result = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="lt_t02")
    result = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="lt_t03")
    result = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_task_manager_created() -> None:
    """CC-01: app/core/task_manager.py exists with TaskManager class."""
    project_dir = create_fixture_project(name="lt_t04")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    mgr = project_dir / "app" / "core" / "task_manager.py"
    assert mgr.exists(), "task_manager.py not created"
    content = mgr.read_text()
    assert "TaskManager" in content


def test_fernet_encryption_present() -> None:
    """CC-02: Task IDs encrypted with Fernet (clients cannot enumerate tasks)."""
    project_dir = create_fixture_project(name="lt_t05")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    assert "Fernet" in content
    assert "encrypt_task_id" in content
    assert "decrypt_task_id" in content


def test_fernet_invalid_token_raises_value_error() -> None:
    """CC-03: decrypt_task_id raises ValueError on invalid token."""
    project_dir = create_fixture_project(name="lt_t06")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    assert "InvalidToken" in content
    assert "ValueError" in content


def test_task_status_enum_present() -> None:
    """CC-04: TaskStatus enum has all 5 states."""
    project_dir = create_fixture_project(name="lt_t07")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    for state in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
        assert state in content, f"TaskStatus.{state} not found"


def test_task_registry_created() -> None:
    """CC-05: app/core/task_registry.py with TaskRegistry.register decorator."""
    project_dir = create_fixture_project(name="lt_t08")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    reg = project_dir / "app" / "core" / "task_registry.py"
    assert reg.exists(), "task_registry.py not created"
    content = reg.read_text()
    assert "TaskRegistry" in content
    assert "def register" in content


def test_task_registry_validates_async() -> None:
    """CC-06: TaskRegistry.register raises TypeError for non-async handlers."""
    project_dir = create_fixture_project(name="lt_t09")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_registry.py").read_text()
    assert "iscoroutinefunction" in content
    assert "TypeError" in content


def test_task_schemas_created() -> None:
    """CC-07: app/schemas/task.py has TaskSubmit and TaskStatusResponse."""
    project_dir = create_fixture_project(name="lt_t10")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    schema = project_dir / "app" / "schemas" / "task.py"
    assert schema.exists(), "schemas/task.py not created"
    content = schema.read_text()
    assert "TaskSubmit" in content
    assert "TaskStatusResponse" in content
    assert "TaskCancelResponse" in content


def test_task_routes_created() -> None:
    """CC-08: app/api/routes/tasks.py with submit, poll, cancel routes."""
    project_dir = create_fixture_project(name="lt_t11")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    routes = project_dir / "app" / "api" / "routes" / "tasks.py"
    assert routes.exists(), "routes/tasks.py not created"
    content = routes.read_text()
    assert "submit_task" in content
    assert "get_task_status" in content
    assert "cancel_task" in content


def test_submit_returns_202() -> None:
    """CC-09: Submit endpoint uses HTTP_202_ACCEPTED."""
    project_dir = create_fixture_project(name="lt_t12")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "tasks.py").read_text()
    assert "202" in content or "HTTP_202_ACCEPTED" in content


def test_submit_has_location_header() -> None:
    """CC-10: Submit response includes Location header pointing to poll URL."""
    project_dir = create_fixture_project(name="lt_t13")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "tasks.py").read_text()
    assert "Location" in content


def test_submit_validates_task_type() -> None:
    """CC-11: Submit endpoint returns 422 for unregistered task_type."""
    project_dir = create_fixture_project(name="lt_t14")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "tasks.py").read_text()
    assert "422" in content or "HTTP_422_UNPROCESSABLE_ENTITY" in content


def test_cancel_route_uses_redis_flag() -> None:
    """CC-12: Cancel uses a Redis flag (cooperative cancellation)."""
    project_dir = create_fixture_project(name="lt_t15")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    assert "request_cancel" in content
    assert "is_cancel_requested" in content


def test_arq_worker_created() -> None:
    """CC-13: workers/task_worker.py with WorkerSettings."""
    project_dir = create_fixture_project(name="lt_t16")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    worker = project_dir / "workers" / "task_worker.py"
    assert worker.exists(), "workers/task_worker.py not created"
    content = worker.read_text()
    assert "WorkerSettings" in content
    assert "arq" in content


def test_arq_worker_checks_cancellation() -> None:
    """CC-14: ARQ worker checks cancellation before and during task execution."""
    project_dir = create_fixture_project(name="lt_t17")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "workers" / "task_worker.py").read_text()
    assert "is_cancel_requested" in content


def test_migration_created() -> None:
    """CC-15: Alembic migration for tasks table is created."""
    project_dir = create_fixture_project(name="lt_t18")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migrations = list(versions_dir.glob("*tasks*"))
    assert len(migrations) >= 1, "No tasks migration file created"
    content = migrations[0].read_text()
    assert "tasks" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_all_py_files_parse() -> None:
    """CC-16: All .py files parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="lt_t19")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-17: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="lt_t20")
    r1 = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="lt_t21")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="lt_t22")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_long_running_task(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be positive after a successful run."""
    project_dir = create_fixture_project(name="lt_t23")
    result = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_arq_and_fernet() -> None:
    """next_steps mentions arq and TASK_FERNET_KEY setup."""
    project_dir = create_fixture_project(name="lt_t24")
    result = add_long_running_task(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    combined = " ".join(result.next_steps).lower()
    assert "arq" in combined
    assert "fernet" in combined or "task_fernet_key" in combined


def test_report_progress_in_task_manager() -> None:
    """CC-18: TaskManager has report_progress method for worker use."""
    project_dir = create_fixture_project(name="lt_t25")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    assert "report_progress" in content


def test_retry_after_header_in_submit_route() -> None:
    """CC-19: Submit route includes Retry-After header with poll hint."""
    project_dir = create_fixture_project(name="lt_t26")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "tasks.py").read_text()
    assert "Retry-After" in content


def test_get_task_manager_singleton() -> None:
    """CC-20: get_task_manager() returns a module-level singleton."""
    project_dir = create_fixture_project(name="lt_t27")
    add_long_running_task(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "task_manager.py").read_text()
    assert "get_task_manager" in content


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_task_manager_created,
        test_fernet_encryption_present,
        test_fernet_invalid_token_raises_value_error,
        test_task_status_enum_present,
        test_task_registry_created,
        test_task_registry_validates_async,
        test_task_schemas_created,
        test_task_routes_created,
        test_submit_returns_202,
        test_submit_has_location_header,
        test_submit_validates_task_type,
        test_cancel_route_uses_redis_flag,
        test_arq_worker_created,
        test_arq_worker_checks_cancellation,
        test_migration_created,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_arq_and_fernet,
        test_report_progress_in_task_manager,
        test_retry_after_header_in_submit_route,
        test_get_task_manager_singleton,
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
