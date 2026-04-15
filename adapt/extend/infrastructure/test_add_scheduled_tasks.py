"""Tests for TOOL-058 add_scheduled_tasks."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_scheduled_tasks import add_scheduled_tasks
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
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


def test_success_status() -> None:
    project_dir = create_fixture_project(name="sch_t01")
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"{result.status}: {result.error}"


def test_idempotent() -> None:
    project_dir = create_fixture_project(name="sch_t02")
    r1 = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run() -> None:
    project_dir = create_fixture_project(name="sch_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after


def test_files_created_count() -> None:
    project_dir = create_fixture_project(name="sch_t04")
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3
    for p in result.files_created:
        assert Path(p).exists()


def test_files_modified_count() -> None:
    project_dir = create_fixture_project(name="sch_t05")
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert len(result.files_modified) >= 2
    for p in result.files_modified:
        assert Path(p).exists()


def test_all_py_parse() -> None:
    project_dir = create_fixture_project(name="sch_t06")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    project_dir = create_fixture_project(name="sch_t07")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir)
    assert max_loc <= 50, f"Found function with {max_loc} LOC"


def test_config_fields_patched() -> None:
    project_dir = create_fixture_project(name="sch_t08")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "config.py").read_text()
    for field in ("SCHEDULER_ENABLED", "SCHEDULER_TIMEZONE", "SCHEDULER_JOBSTORE_URL"):
        assert field in content
    for line in content.splitlines():
        if "SCHEDULER_ENABLED" in line:
            assert line.startswith("    ")
            break


def test_main_lifespan_hooks() -> None:
    project_dir = create_fixture_project(name="sch_t09")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "main.py").read_text()
    assert "start_scheduler" in content
    assert "stop_scheduler" in content
    # Modern FastAPI: injected into existing @asynccontextmanager lifespan
    # before the yield / after the shutdown marker.
    assert "await start_scheduler()" in content
    assert "await stop_scheduler()" in content


def test_requirements_apscheduler() -> None:
    project_dir = create_fixture_project(name="sch_t10")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert "apscheduler" in (project_dir / "requirements.txt").read_text().lower()


def test_scheduler_factory_created() -> None:
    project_dir = create_fixture_project(name="sch_t11")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    f = project_dir / "app" / "workers" / "scheduler.py"
    assert f.exists()
    c = f.read_text()
    assert "class SchedulerFactory" in c
    assert "AsyncIOScheduler" in c
    assert "async def start_scheduler" in c
    assert "async def stop_scheduler" in c


def test_cron_jobs_registry_created() -> None:
    project_dir = create_fixture_project(name="sch_t12")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    f = project_dir / "app" / "workers" / "cron_jobs.py"
    assert f.exists()
    c = f.read_text()
    assert "def scheduled_job" in c
    assert "class ScheduledJob" in c
    assert "def register_jobs" in c
    assert "def list_jobs" in c


def test_example_jobs_present() -> None:
    project_dir = create_fixture_project(name="sch_t13")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    c = (project_dir / "app" / "workers" / "cron_jobs.py").read_text()
    assert "health_heartbeat" in c
    assert "cleanup_expired_sessions" in c
    assert "refresh_materialized_view" in c


def test_status_route_created() -> None:
    project_dir = create_fixture_project(name="sch_t14")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    f = project_dir / "app" / "api" / "routes" / "scheduler.py"
    assert f.exists()
    c = f.read_text()
    assert "/jobs" in c
    assert "JobInfo" in c


def test_redis_jobstore_branch() -> None:
    project_dir = create_fixture_project(name="sch_t15")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    c = (project_dir / "app" / "workers" / "scheduler.py").read_text()
    assert "redis://" in c
    assert "RedisJobStore" in c


def test_cron_decorator_usage() -> None:
    project_dir = create_fixture_project(name="sch_t16")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    c = (project_dir / "app" / "workers" / "cron_jobs.py").read_text()
    assert '@scheduled_job("' in c


def test_execution_time_recorded() -> None:
    project_dir = create_fixture_project(name="sch_t17")
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    project_dir = create_fixture_project(name="sch_t18")
    result = add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "apscheduler" in combined
    assert "scheduled_job" in combined or "cron" in combined


def test_idempotent_project_still_parses() -> None:
    project_dir = create_fixture_project(name="sch_t19")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_disabled_flag_default_true() -> None:
    project_dir = create_fixture_project(name="sch_t20")
    add_scheduled_tasks(ToolInput(project_dir=str(project_dir)))
    c = (project_dir / "app" / "core" / "config.py").read_text()
    assert "SCHEDULER_ENABLED: bool = True" in c


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run,
        test_files_created_count, test_files_modified_count,
        test_all_py_parse, test_no_function_over_50_loc,
        test_config_fields_patched, test_main_lifespan_hooks,
        test_requirements_apscheduler, test_scheduler_factory_created,
        test_cron_jobs_registry_created, test_example_jobs_present,
        test_status_route_created, test_redis_jobstore_branch,
        test_cron_decorator_usage, test_execution_time_recorded,
        test_next_steps_present, test_idempotent_project_still_parses,
        test_disabled_flag_default_true,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\nTOOL-058: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
