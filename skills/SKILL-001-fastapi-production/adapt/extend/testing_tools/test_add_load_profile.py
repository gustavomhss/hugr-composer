"""Tests for TOOL-027 add_load_profile.

Generates a real fixture project, runs the tool, and validates all
completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_load_profile.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_load_profile.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_load_profile import add_load_profile
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_all(root: Path) -> None:
    """Assert every .py under *root* has valid syntax.

    Args:
        root: Directory to walk recursively.

    Raises:
        AssertionError: On syntax error in any generated file.
    """
    for py_file in sorted(root.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def _fresh(name: str) -> Path:
    """Return a freshly generated fixture project.

    Args:
        name: Unique project name.

    Returns:
        Path to the generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("lp_t01")
    result = add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created exists on disk."""
    project_dir = _fresh("lp_t02")
    result = add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_load_dir_created() -> None:
    """CC-01: tests/load/ directory is created."""
    project_dir = _fresh("lp_t03")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load").is_dir()


def test_locustfile_created() -> None:
    """CC-02: tests/load/locustfile.py is created."""
    project_dir = _fresh("lp_t04")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load" / "locustfile.py").exists()


def test_locustfile_has_browsing_user() -> None:
    """CC-03: locustfile.py defines BrowsingUser class."""
    project_dir = _fresh("lp_t05")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "locustfile.py").read_text()
    assert "class BrowsingUser" in src


def test_locustfile_has_active_user() -> None:
    """CC-04: locustfile.py defines ActiveUser class."""
    project_dir = _fresh("lp_t06")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "locustfile.py").read_text()
    assert "class ActiveUser" in src


def test_locustfile_has_admin_user() -> None:
    """CC-05: locustfile.py defines AdminUser class."""
    project_dir = _fresh("lp_t07")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "locustfile.py").read_text()
    assert "class AdminUser" in src


def test_locustfile_has_auth_mixin() -> None:
    """CC-06: locustfile.py imports AuthMixin."""
    project_dir = _fresh("lp_t08")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "locustfile.py").read_text()
    assert "AuthMixin" in src


def test_locustfile_calls_login_on_start() -> None:
    """CC-07: locustfile.py calls self.login() in on_start."""
    project_dir = _fresh("lp_t09")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "locustfile.py").read_text()
    assert "self.login()" in src


def test_auth_mixin_created() -> None:
    """CC-08: tests/load/auth.py is created with AuthMixin."""
    project_dir = _fresh("lp_t10")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    auth_file = project_dir / "tests" / "load" / "auth.py"
    assert auth_file.exists()
    assert "class AuthMixin" in auth_file.read_text()


def test_auth_mixin_has_login_method() -> None:
    """CC-09: AuthMixin.login() method is defined."""
    project_dir = _fresh("lp_t11")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "auth.py").read_text()
    assert "def login" in src


def test_data_factories_created() -> None:
    """CC-10: tests/load/data_factories.py is created."""
    project_dir = _fresh("lp_t12")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load" / "data_factories.py").exists()


def test_data_factories_use_faker() -> None:
    """CC-11: data_factories.py imports and uses Faker."""
    project_dir = _fresh("lp_t13")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "data_factories.py").read_text()
    assert "Faker" in src or "faker" in src


def test_slo_assertions_created() -> None:
    """CC-12: tests/load/slo_assertions.py is created."""
    project_dir = _fresh("lp_t14")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load" / "slo_assertions.py").exists()


def test_slo_assertions_hooks_on_quitting() -> None:
    """CC-13: slo_assertions.py registers a locust.events.quitting listener."""
    project_dir = _fresh("lp_t15")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "slo_assertions.py").read_text()
    assert "events.quitting" in src


def test_slo_assertions_sets_exit_code() -> None:
    """CC-14: slo_assertions.py sets process_exit_code=1 on violation."""
    project_dir = _fresh("lp_t16")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "slo_assertions.py").read_text()
    assert "process_exit_code = 1" in src


def test_slo_yaml_created() -> None:
    """CC-15: tests/load/slo_config.yaml is created."""
    project_dir = _fresh("lp_t17")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load" / "slo_config.yaml").exists()


def test_slo_yaml_has_p99_targets() -> None:
    """CC-16: slo_config.yaml contains p99_targets_ms section."""
    project_dir = _fresh("lp_t18")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "tests" / "load" / "slo_config.yaml").read_text()
    assert "p99_targets_ms" in content


def test_custom_slo_targets_in_yaml() -> None:
    """CC-17: Custom targets_p99_ms dict appears in slo_config.yaml."""
    project_dir = _fresh("lp_t19")
    add_load_profile(
        ToolInput(project_dir=str(project_dir)),
        targets_p99_ms={"GET /api/v1/items": 150},
    )
    content = (project_dir / "tests" / "load" / "slo_config.yaml").read_text()
    assert "150" in content


def test_shapes_file_created() -> None:
    """CC-18: tests/load/shapes.py is created with LoadTestShape classes."""
    project_dir = _fresh("lp_t20")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    shapes_file = project_dir / "tests" / "load" / "shapes.py"
    assert shapes_file.exists()
    src = shapes_file.read_text()
    assert "LoadTestShape" in src


def test_shapes_has_three_profiles() -> None:
    """CC-19: shapes.py defines Smoke, Baseline, and Peak shape classes."""
    project_dir = _fresh("lp_t21")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "load" / "shapes.py").read_text()
    assert "SmokeShape" in src
    assert "BaselineShape" in src
    assert "PeakShape" in src


def test_scenarios_file_created() -> None:
    """CC-20: tests/load/scenarios.py is created."""
    project_dir = _fresh("lp_t22")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "load" / "scenarios.py").exists()


def test_ci_workflow_created() -> None:
    """CC-21: .github/workflows/load-tests.yml is created."""
    project_dir = _fresh("lp_t23")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / ".github" / "workflows" / "load-tests.yml").exists()


def test_ci_workflow_has_locust_run() -> None:
    """CC-22: CI workflow runs locust headlessly."""
    project_dir = _fresh("lp_t24")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / ".github" / "workflows" / "load-tests.yml").read_text()
    assert "locust" in src
    assert "--headless" in src


def test_all_generated_py_files_parse() -> None:
    """CC-23: All .py files parse without SyntaxError after tool run."""
    project_dir = _fresh("lp_t25")
    add_load_profile(ToolInput(project_dir=str(project_dir)))
    _parse_all(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-24: Second run returns status='no_op'."""
    project_dir = _fresh("lp_t26")
    r1 = add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run_writes_nothing() -> None:
    """CC-25: dry_run=True writes no files."""
    project_dir = _fresh("lp_t27")
    before = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    result = add_load_profile(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    after = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    assert before == after, "dry_run must not change any file"


def test_execution_time_positive() -> None:
    """CC-26: execution_time_ms is a positive integer."""
    project_dir = _fresh("lp_t28")
    result = add_load_profile(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_install() -> None:
    """CC-27: next_steps mentions locust installation."""
    project_dir = _fresh("lp_t29")
    result = add_load_profile(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps)
    assert "locust" in combined.lower()


def test_notes_describe_profiles() -> None:
    """CC-28: notes describe the 3 load profiles."""
    project_dir = _fresh("lp_t30")
    result = add_load_profile(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes)
    assert "smoke" in combined.lower() or "baseline" in combined.lower()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_load_dir_created,
        test_locustfile_created,
        test_locustfile_has_browsing_user,
        test_locustfile_has_active_user,
        test_locustfile_has_admin_user,
        test_locustfile_has_auth_mixin,
        test_locustfile_calls_login_on_start,
        test_auth_mixin_created,
        test_auth_mixin_has_login_method,
        test_data_factories_created,
        test_data_factories_use_faker,
        test_slo_assertions_created,
        test_slo_assertions_hooks_on_quitting,
        test_slo_assertions_sets_exit_code,
        test_slo_yaml_created,
        test_slo_yaml_has_p99_targets,
        test_custom_slo_targets_in_yaml,
        test_shapes_file_created,
        test_shapes_has_three_profiles,
        test_scenarios_file_created,
        test_ci_workflow_created,
        test_ci_workflow_has_locust_run,
        test_all_generated_py_files_parse,
        test_idempotent_returns_no_op,
        test_dry_run_writes_nothing,
        test_execution_time_positive,
        test_next_steps_mention_install,
        test_notes_describe_profiles,
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
