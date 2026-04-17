"""Tests for TOOL-059 add_celery_beat.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_celery_beat.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_celery_beat.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_celery_beat import add_celery_beat
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
    project_dir = create_fixture_project(name="celery_t01")
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="celery_t02")
    r1 = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="celery_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_celery_beat(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 6 new files (workers pkg + 4 py + 2 Dockerfiles)."""
    project_dir = create_fixture_project(name="celery_t04")
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config.py and requirements.txt)."""
    project_dir = create_fixture_project(name="celery_t05")
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="celery_t06")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="celery_t07")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_TASK_ALWAYS_EAGER exist in config.py."""
    project_dir = create_fixture_project(name="celery_t08")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "CELERY_TASK_ALWAYS_EAGER"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify the first field is inside the Settings class (4-space indent).
    for line in content.splitlines():
        if "CELERY_BROKER_URL" in line:
            assert line.startswith("    "), (
                f"CELERY_BROKER_URL not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_requirements_patched() -> None:
    """requirements.txt contains celery[redis]>=."""
    project_dir = create_fixture_project(name="celery_t09")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "celery" in content, "celery dependency not added to requirements.txt"


def test_celery_app_created() -> None:
    """app/workers/celery_app.py exists and contains celery_app."""
    project_dir = create_fixture_project(name="celery_t10")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    celery_app_file = project_dir / "app" / "workers" / "celery_app.py"
    assert celery_app_file.exists(), "celery_app.py not created"
    content = celery_app_file.read_text()
    assert "celery_app" in content, "celery_app not found in celery_app.py"
    assert "create_celery_app" in content, "create_celery_app factory not found"


def test_tasks_module_created() -> None:
    """app/workers/celery_tasks.py exists with 3 example tasks."""
    project_dir = create_fixture_project(name="celery_t11")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    tasks_file = project_dir / "app" / "workers" / "celery_tasks.py"
    assert tasks_file.exists(), "celery_tasks.py not created"
    content = tasks_file.read_text()
    assert "cleanup_expired" in content, "cleanup_expired task not found"
    assert "send_digest" in content, "send_digest task not found"
    assert "sync_external" in content, "sync_external task not found"


def test_beat_schedule_created() -> None:
    """app/workers/celery_beat_schedule.py exists with BEAT_SCHEDULE and crontab entries."""
    project_dir = create_fixture_project(name="celery_t12")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    beat_file = project_dir / "app" / "workers" / "celery_beat_schedule.py"
    assert beat_file.exists(), "celery_beat_schedule.py not created"
    content = beat_file.read_text()
    assert "BEAT_SCHEDULE" in content, "BEAT_SCHEDULE not found in celery_beat_schedule.py"
    assert "crontab" in content, "crontab not referenced in beat schedule"


def test_status_route_created() -> None:
    """app/api/routes/celery_status.py exists with GET /celery/status."""
    project_dir = create_fixture_project(name="celery_t13")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "celery_status.py"
    assert route_file.exists(), "celery_status.py not created"
    content = route_file.read_text()
    assert "get_celery_status" in content, "get_celery_status route not found"
    assert "/celery" in content, "Route prefix /celery not found"


def test_dockerfile_worker_created() -> None:
    """Dockerfile.celery-worker exists and runs as non-root."""
    project_dir = create_fixture_project(name="celery_t14")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    dockerfile = project_dir / "Dockerfile.celery-worker"
    assert dockerfile.exists(), "Dockerfile.celery-worker not created"
    content = dockerfile.read_text()
    assert "USER" in content, "Dockerfile.celery-worker should run as non-root"
    assert "celery" in content.lower(), "Dockerfile.celery-worker CMD should reference celery"


def test_dockerfile_beat_created() -> None:
    """Dockerfile.celery-beat exists and runs as non-root."""
    project_dir = create_fixture_project(name="celery_t15")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    dockerfile = project_dir / "Dockerfile.celery-beat"
    assert dockerfile.exists(), "Dockerfile.celery-beat not created"
    content = dockerfile.read_text()
    assert "USER" in content, "Dockerfile.celery-beat should run as non-root"
    assert "beat" in content.lower(), "Dockerfile.celery-beat CMD should reference beat"


def test_lazy_celery_import() -> None:
    """celery_app.py uses a lazy import (celery imported inside function body)."""
    project_dir = create_fixture_project(name="celery_t16")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    celery_app_file = project_dir / "app" / "workers" / "celery_app.py"
    content = celery_app_file.read_text()
    # The lazy import pattern means 'from celery import Celery' should appear
    # inside a function body (indented), NOT at module level.
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("from celery import Celery") or stripped.startswith("import celery"):
            # This line is a lazy import — it must be indented (inside a function)
            assert line.startswith("    "), (
                f"Celery import is at module level instead of lazy: {line!r}"
            )


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="celery_t17")
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps contains actionable guidance for running the worker and beat."""
    project_dir = create_fixture_project(name="celery_t18")
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) >= 3, (
        f"Expected >= 3 next_steps, got {len(result.next_steps)}"
    )
    combined = " ".join(result.next_steps).lower()
    assert "celery" in combined, "next_steps should mention celery"
    assert "worker" in combined or "beat" in combined, (
        "next_steps should mention worker or beat"
    )


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="celery_t19")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_celery_app_uses_settings_broker() -> None:
    """celery_app.py reads broker from settings, not a hard-coded host."""
    project_dir = create_fixture_project(name="celery_t20")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    celery_app_file = project_dir / "app" / "workers" / "celery_app.py"
    content = celery_app_file.read_text()
    # Must reference settings for the broker URL.
    assert "settings" in content, "celery_app.py must read broker from settings"
    # Must NOT hard-code a Redis host.
    assert "localhost" not in content, (
        "celery_app.py must not hard-code 'localhost' as broker URL"
    )
    assert "redis://localhost" not in content, (
        "celery_app.py must not hard-code redis://localhost"
    )


def test_main_py_not_modified() -> None:
    """app/main.py is NOT modified (Celery is a separate process)."""
    project_dir = create_fixture_project(name="celery_t21")
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        before = main_file.read_text()
    else:
        before = None
    result = add_celery_beat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    if before is not None:
        after = main_file.read_text()
        assert before == after, "app/main.py must NOT be modified by add_celery_beat"
    modified_names = [Path(p).name for p in result.files_modified]
    assert "main.py" not in modified_names, "main.py must not appear in files_modified"


def test_workers_package_init_created() -> None:
    """app/workers/__init__.py exists after tool runs."""
    project_dir = create_fixture_project(name="celery_t22")
    add_celery_beat(ToolInput(project_dir=str(project_dir)))
    workers_init = project_dir / "app" / "workers" / "__init__.py"
    assert workers_init.exists(), "app/workers/__init__.py not created"


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
        test_requirements_patched,
        test_celery_app_created,
        test_tasks_module_created,
        test_beat_schedule_created,
        test_status_route_created,
        test_dockerfile_worker_created,
        test_dockerfile_beat_created,
        test_lazy_celery_import,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_celery_app_uses_settings_broker,
        test_main_py_not_modified,
        test_workers_package_init_created,
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
    print(f"TOOL-059 add_celery_beat: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
