"""Tests for TOOL-026 add_contract_tests.

Generates a real fixture project, runs the tool, and validates all
completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_contract_tests.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_contract_tests.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_contract_tests import add_contract_tests
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_all(root: Path) -> None:
    """Assert every .py file under *root* has valid syntax.

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
    project_dir = _fresh("ct_t01")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created exists on disk."""
    project_dir = _fresh("ct_t02")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_contracts_dir_created() -> None:
    """CC-01: tests/contracts/ directory is created."""
    project_dir = _fresh("ct_t03")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts").is_dir()


def test_conftest_created() -> None:
    """CC-02: tests/contracts/conftest.py is created."""
    project_dir = _fresh("ct_t04")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts" / "conftest.py").exists()


def test_conftest_has_schema_fixture() -> None:
    """CC-03: conftest.py contains the schemathesis schema fixture."""
    project_dir = _fresh("ct_t05")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "contracts" / "conftest.py").read_text()
    assert "schemathesis" in src
    assert "def schema" in src


def test_base_schemathesis_test_created() -> None:
    """CC-04: tests/contracts/test_api_schema.py is created."""
    project_dir = _fresh("ct_t06")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts" / "test_api_schema.py").exists()


def test_schemathesis_test_uses_parametrize() -> None:
    """CC-05: test_api_schema.py uses @schema.parametrize() decorator."""
    project_dir = _fresh("ct_t07")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "contracts" / "test_api_schema.py").read_text()
    assert "@schema.parametrize()" in src


def test_schemathesis_test_has_max_examples() -> None:
    """CC-06: test_api_schema.py embeds the configured max_examples value."""
    project_dir = _fresh("ct_t08")
    add_contract_tests(ToolInput(project_dir=str(project_dir)), max_examples=42)
    src = (project_dir / "tests" / "contracts" / "test_api_schema.py").read_text()
    assert "42" in src


def test_stateful_test_created() -> None:
    """CC-07: tests/contracts/test_stateful.py is created."""
    project_dir = _fresh("ct_t09")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts" / "test_stateful.py").exists()


def test_stateful_disabled_has_skip_marker() -> None:
    """CC-08: stateful=False generates a pytest.mark.skip placeholder."""
    project_dir = _fresh("ct_t10")
    add_contract_tests(ToolInput(project_dir=str(project_dir)), stateful=False)
    src = (project_dir / "tests" / "contracts" / "test_stateful.py").read_text()
    assert "pytest.mark.skip" in src


def test_stateful_enabled_removes_skip() -> None:
    """CC-09: stateful=True generates active (non-skipped) stateful test."""
    project_dir = _fresh("ct_t11")
    add_contract_tests(ToolInput(project_dir=str(project_dir)), stateful=True)
    src = (project_dir / "tests" / "contracts" / "test_stateful.py").read_text()
    assert "pytest.mark.skip" not in src
    assert "Stateful.links" in src


def test_custom_checks_module_created() -> None:
    """CC-10: tests/contracts/custom_checks.py is created."""
    project_dir = _fresh("ct_t12")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts" / "custom_checks.py").exists()


def test_custom_checks_has_schemathesis_decorator() -> None:
    """CC-11: custom_checks.py uses @schemathesis.check decorator."""
    project_dir = _fresh("ct_t13")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "contracts" / "custom_checks.py").read_text()
    assert "@schemathesis.check" in src


def test_pact_stubs_created() -> None:
    """CC-12: tests/contracts/test_pact_stubs.py is created."""
    project_dir = _fresh("ct_t14")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "contracts" / "test_pact_stubs.py").exists()


def test_pact_markers_in_stubs() -> None:
    """CC-13: Pact stubs use pact_consumer / pact_provider markers."""
    project_dir = _fresh("ct_t15")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "contracts" / "test_pact_stubs.py").read_text()
    assert "pact_consumer" in src
    assert "pact_provider" in src


def test_exclude_yaml_created() -> None:
    """CC-14: .schemathesis-exclude.yaml is created at project root."""
    project_dir = _fresh("ct_t16")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / ".schemathesis-exclude.yaml").exists()


def test_exclude_yaml_contains_defaults() -> None:
    """CC-15: Exclude YAML always lists /health and /metrics as base exclusions."""
    project_dir = _fresh("ct_t17")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / ".schemathesis-exclude.yaml").read_text()
    assert "/health" in content or "/metrics" in content


def test_custom_excludes_in_yaml() -> None:
    """CC-16: Custom exclude_endpoints appear in the generated YAML."""
    project_dir = _fresh("ct_t18")
    add_contract_tests(
        ToolInput(project_dir=str(project_dir)),
        exclude_endpoints=["/admin/wipe"],
    )
    content = (project_dir / ".schemathesis-exclude.yaml").read_text()
    assert "/admin/wipe" in content


def test_ci_workflow_created() -> None:
    """CC-17: .github/workflows/contract-tests.yml is created."""
    project_dir = _fresh("ct_t19")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / ".github" / "workflows" / "contract-tests.yml").exists()


def test_ci_workflow_has_schemathesis_step() -> None:
    """CC-18: CI workflow runs schemathesis pytest step."""
    project_dir = _fresh("ct_t20")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / ".github" / "workflows" / "contract-tests.yml").read_text()
    assert "schemathesis" in src


def test_all_generated_py_files_parse() -> None:
    """CC-19: All .py files in the project parse without SyntaxError."""
    project_dir = _fresh("ct_t21")
    add_contract_tests(ToolInput(project_dir=str(project_dir)))
    _parse_all(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-20: Second run returns status='no_op'."""
    project_dir = _fresh("ct_t22")
    r1 = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_dry_run_writes_nothing() -> None:
    """CC-21: dry_run=True writes no files."""
    project_dir = _fresh("ct_t23")
    before = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    result = add_contract_tests(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    after = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    assert before == after, "dry_run must not change any file"


def test_execution_time_positive() -> None:
    """CC-22: execution_time_ms is a positive integer."""
    project_dir = _fresh("ct_t24")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_install() -> None:
    """CC-23: next_steps mentions schemathesis install."""
    project_dir = _fresh("ct_t25")
    result = add_contract_tests(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps)
    assert "schemathesis" in combined


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_contracts_dir_created,
        test_conftest_created,
        test_conftest_has_schema_fixture,
        test_base_schemathesis_test_created,
        test_schemathesis_test_uses_parametrize,
        test_schemathesis_test_has_max_examples,
        test_stateful_test_created,
        test_stateful_disabled_has_skip_marker,
        test_stateful_enabled_removes_skip,
        test_custom_checks_module_created,
        test_custom_checks_has_schemathesis_decorator,
        test_pact_stubs_created,
        test_pact_markers_in_stubs,
        test_exclude_yaml_created,
        test_exclude_yaml_contains_defaults,
        test_custom_excludes_in_yaml,
        test_ci_workflow_created,
        test_ci_workflow_has_schemathesis_step,
        test_all_generated_py_files_parse,
        test_idempotent_returns_no_op,
        test_dry_run_writes_nothing,
        test_execution_time_positive,
        test_next_steps_mention_install,
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
