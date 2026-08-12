"""Tests for TOOL-022 add_arq_worker.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_arq_worker.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_arq_worker.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_arq_worker import add_arq_worker
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
    project_dir = create_fixture_project(name="arq_t01")
    result = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="arq_t02")
    r1 = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="arq_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_arq_worker(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 8 new files (workers pkg, tasks, worker, enqueue, model, schemas, crud, routes, migration, dockerfile)."""
    project_dir = create_fixture_project(name="arq_t04")
    result = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 8, (
        f"Expected >= 8 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init, main, requirements)."""
    project_dir = create_fixture_project(name="arq_t05")
    result = add_arq_worker(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="arq_t06")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="arq_t07")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected ARQ_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="arq_t08")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("ARQ_MAX_JOBS", "ARQ_JOB_TIMEOUT"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "ARQ_MAX_JOBS" in line:
            assert line.startswith("    "), (
                f"ARQ_MAX_JOBS not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """Job model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="arq_t09")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "Job" in content, "Job not registered in models __init__"


def test_routes_registered() -> None:
    """Jobs HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="arq_t10")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "job" in content.lower(), "Jobs router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_worker_module_created() -> None:
    """app/workers/arq_worker.py exists with WorkerSettings."""
    project_dir = create_fixture_project(name="arq_t11")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "arq_worker.py"
    assert worker_file.exists(), "arq_worker.py not created"
    content = worker_file.read_text()
    assert "WorkerSettings" in content, "WorkerSettings class not found in arq_worker.py"


def test_tasks_module_created() -> None:
    """app/workers/tasks.py exists with TASK_REGISTRY containing 3 tasks."""
    project_dir = create_fixture_project(name="arq_t12")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    tasks_file = project_dir / "app" / "workers" / "tasks.py"
    assert tasks_file.exists(), "tasks.py not created"
    content = tasks_file.read_text()
    assert "TASK_REGISTRY" in content, "TASK_REGISTRY not found in tasks.py"
    assert "send_email_task" in content, "send_email_task not in TASK_REGISTRY"
    assert "cleanup_task" in content, "cleanup_task not in TASK_REGISTRY"
    assert "webhook_retry_task" in content, "webhook_retry_task not in TASK_REGISTRY"


def test_enqueue_module_created() -> None:
    """app/workers/enqueue.py exists with create_arq_pool and enqueue."""
    project_dir = create_fixture_project(name="arq_t13")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    enqueue_file = project_dir / "app" / "workers" / "enqueue.py"
    assert enqueue_file.exists(), "enqueue.py not created"
    content = enqueue_file.read_text()
    assert "create_arq_pool" in content, "create_arq_pool not found in enqueue.py"
    assert "enqueue" in content, "enqueue function not found in enqueue.py"


def test_job_model_created() -> None:
    """app/models/job.py exists with Job model."""
    project_dir = create_fixture_project(name="arq_t14")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    job_model = project_dir / "app" / "models" / "job.py"
    assert job_model.exists(), "app/models/job.py not created"
    content = job_model.read_text()
    assert "class Job" in content, "Job model class not found"


def test_dockerfile_worker_created() -> None:
    """Dockerfile.worker exists in the project root."""
    project_dir = create_fixture_project(name="arq_t15")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    dockerfile = project_dir / "Dockerfile.worker"
    assert dockerfile.exists(), "Dockerfile.worker not created"
    content = dockerfile.read_text()
    assert "USER" in content, "Dockerfile.worker should run as non-root"


def test_lifespan_patched() -> None:
    """app/main.py contains create_arq_pool and close_arq_pool."""
    project_dir = create_fixture_project(name="arq_t16")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "create_arq_pool" in content, "create_arq_pool not found in main.py"
    assert "close_arq_pool" in content, "close_arq_pool not found in main.py"


def test_requirements_arq() -> None:
    """requirements.txt contains arq>=."""
    project_dir = create_fixture_project(name="arq_t17")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "arq>=" in content, "arq dependency not added to requirements.txt"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="arq_t18")
    result = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_mention_alembic_and_redis() -> None:
    """next_steps guides developer to run migration and set Redis."""
    project_dir = create_fixture_project(name="arq_t19")
    result = add_arq_worker(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"
    assert "redis" in combined, "next_steps should mention Redis"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="arq_t20")
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
    add_arq_worker(ToolInput(project_dir=str(project_dir)))
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
        test_models_init_patched,
        test_routes_registered,
        test_worker_module_created,
        test_tasks_module_created,
        test_enqueue_module_created,
        test_job_model_created,
        test_dockerfile_worker_created,
        test_lifespan_patched,
        test_requirements_arq,
        test_execution_time_recorded,
        test_next_steps_mention_alembic_and_redis,
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
    print(f"TOOL-022 add_arq_worker: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
