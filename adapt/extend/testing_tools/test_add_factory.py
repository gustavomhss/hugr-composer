"""Tests for TOOL-025 add_factory.

Generates a real fixture project, runs the tool, and validates all
completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_factory.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_factory.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_factory import add_factory
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_all(root: Path) -> None:
    """Assert every .py file under *root* has valid syntax.

    Args:
        root: Project root to walk recursively.

    Raises:
        AssertionError: If any file fails ast.parse.
    """
    for py_file in sorted(root.rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def _fresh(name: str) -> Path:
    """Return a freshly generated fixture project for test isolation.

    Args:
        name: Unique project name (also the output dir name).

    Returns:
        Path to the generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("fac_t01")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = _fresh("fac_t02")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing on disk: {p}"


def test_factories_dir_created() -> None:
    """CC-01: tests/factories/ directory is created."""
    project_dir = _fresh("fac_t03")
    add_factory(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "factories").is_dir()


def test_init_file_created() -> None:
    """CC-02: tests/factories/__init__.py is created."""
    project_dir = _fresh("fac_t04")
    add_factory(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "factories" / "__init__.py").exists()


def test_factory_registry_in_init() -> None:
    """CC-03: FACTORY_REGISTRY and get_factory exported from __init__.py."""
    project_dir = _fresh("fac_t05")
    add_factory(ToolInput(project_dir=str(project_dir)))
    init_src = (project_dir / "tests" / "factories" / "__init__.py").read_text()
    assert "FACTORY_REGISTRY" in init_src
    assert "def get_factory" in init_src


def test_item_factory_file_created() -> None:
    """CC-04: tests/factories/item_factory.py is created for the Item model."""
    project_dir = _fresh("fac_t06")
    add_factory(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "factories" / "item_factory.py").exists()


def test_factory_class_name_correct() -> None:
    """CC-05: The factory class is named ItemFactory."""
    project_dir = _fresh("fac_t07")
    add_factory(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "class ItemFactory" in src


def test_factory_has_build_batch_seeded() -> None:
    """CC-06: ItemFactory exposes build_batch_seeded classmethod for determinism."""
    project_dir = _fresh("fac_t08")
    add_factory(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "build_batch_seeded" in src


def test_factory_has_stub_classmethod() -> None:
    """CC-07: ItemFactory exposes a stub() classmethod."""
    project_dir = _fresh("fac_t09")
    add_factory(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "def stub" in src


def test_conftest_patched_with_fixtures() -> None:
    """CC-08: tests/conftest.py is patched with item_factory fixture."""
    project_dir = _fresh("fac_t10")
    add_factory(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "conftest.py").exists()
    src = (project_dir / "tests" / "conftest.py").read_text()
    assert "item_factory" in src


def test_conftest_has_create_helper() -> None:
    """CC-09: tests/conftest.py has async create_item fixture."""
    project_dir = _fresh("fac_t11")
    add_factory(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "conftest.py").read_text()
    assert "create_item" in src or "async def _create" in src


def test_polyfactory_backend_default() -> None:
    """CC-10: Default backend is polyfactory (SQLAlchemyFactory in factory file)."""
    project_dir = _fresh("fac_t12")
    add_factory(ToolInput(project_dir=str(project_dir)))
    src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "SQLAlchemyFactory" in src


def test_factory_boy_backend() -> None:
    """CC-11: factory_boy backend generates factory.Factory subclass."""
    project_dir = _fresh("fac_t13")
    add_factory(ToolInput(project_dir=str(project_dir)), backend="factory_boy")
    src = (project_dir / "tests" / "factories" / "item_factory.py").read_text()
    assert "factory.Factory" in src


def test_notes_not_empty() -> None:
    """CC-12: result.notes is populated on success."""
    project_dir = _fresh("fac_t14")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.notes, "notes must not be empty on success"


def test_next_steps_mention_install() -> None:
    """CC-13: next_steps mentions pip install."""
    project_dir = _fresh("fac_t15")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert any("pip install" in s for s in result.next_steps), "Should mention pip install"


def test_execution_time_positive() -> None:
    """CC-14: execution_time_ms is a positive integer."""
    project_dir = _fresh("fac_t16")
    result = add_factory(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_idempotent_returns_no_op() -> None:
    """CC-15: Second run returns status='no_op' without writing files."""
    project_dir = _fresh("fac_t17")
    r1 = add_factory(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_factory(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """CC-16: Project parses cleanly after two runs."""
    project_dir = _fresh("fac_t18")
    add_factory(ToolInput(project_dir=str(project_dir)))
    add_factory(ToolInput(project_dir=str(project_dir)))
    _parse_all(project_dir)


def test_dry_run_writes_nothing() -> None:
    """CC-17: dry_run=True writes no files."""
    project_dir = _fresh("fac_t19")
    before = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    result = add_factory(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    after = {str(f): f.read_text() for f in project_dir.rglob("*.py")}
    assert before == after, "dry_run must not change any file"


def test_all_generated_py_files_parse() -> None:
    """CC-18: All .py files in project parse without SyntaxError after tool run."""
    project_dir = _fresh("fac_t20")
    add_factory(ToolInput(project_dir=str(project_dir)))
    _parse_all(project_dir)


def test_explicit_models_list() -> None:
    """CC-19: Passing explicit models= only generates factories for those models."""
    project_dir = _fresh("fac_t21")
    result = add_factory(ToolInput(project_dir=str(project_dir)), models=["Item"])
    assert result.status == "success"
    assert (project_dir / "tests" / "factories" / "item_factory.py").exists()


def test_error_when_no_models() -> None:
    """CC-20: Returns status='error' when models are explicitly specified as empty list."""
    project_dir = _fresh("fac_t22")
    result = add_factory(ToolInput(project_dir=str(project_dir)), models=[])
    assert result.status == "error"
    assert result.error


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_factories_dir_created,
        test_init_file_created,
        test_factory_registry_in_init,
        test_item_factory_file_created,
        test_factory_class_name_correct,
        test_factory_has_build_batch_seeded,
        test_factory_has_stub_classmethod,
        test_conftest_patched_with_fixtures,
        test_conftest_has_create_helper,
        test_polyfactory_backend_default,
        test_factory_boy_backend,
        test_notes_not_empty,
        test_next_steps_mention_install,
        test_execution_time_positive,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_all_generated_py_files_parse,
        test_explicit_models_list,
        test_error_when_no_models,
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
