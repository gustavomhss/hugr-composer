"""Tests for TOOL-031 schema_coverage.

Verifies idempotency, AST discovery, coverage reporting, orphan detection,
exclusion schema, CI workflow, and the _run_analysis / _discover_schemas helpers.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_schema_coverage.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import textwrap
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.schema_coverage import (
    _collect_test_references,
    _extract_fields,
    _is_basemodel_subclass,
    _run_analysis,
    schema_coverage,
)
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ok(path: Path) -> bool:
    try:
        ast.parse(path.read_text())
        return True
    except SyntaxError:
        return False


def _make_schema_file(tmp_dir: Path, content: str) -> Path:
    """Write a fake schema file into a minimal app/schemas/ structure."""
    schemas_dir = tmp_dir / "app" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    f = schemas_dir / "item.py"
    f.write_text(content)
    return tmp_dir


# ---------------------------------------------------------------------------
# Unit tests for AST helpers
# ---------------------------------------------------------------------------

def test_extract_fields_simple() -> None:
    """T-01: _extract_fields returns annotated assignment names."""
    src = textwrap.dedent("""\
        class Item(BaseModel):
            title: str
            description: str
            price: float
    """)
    node = ast.parse(src).body[0]
    fields = _extract_fields(node)
    assert set(fields) == {"title", "description", "price"}


def test_extract_fields_skips_private() -> None:
    """T-02: _extract_fields skips underscore-prefixed names."""
    src = textwrap.dedent("""\
        class Item(BaseModel):
            title: str
            _internal: str
    """)
    node = ast.parse(src).body[0]
    fields = _extract_fields(node)
    assert "_internal" not in fields
    assert "title" in fields


def test_is_basemodel_subclass_direct() -> None:
    """T-03: _is_basemodel_subclass detects BaseModel base."""
    src = "class Foo(BaseModel): pass"
    node = ast.parse(src).body[0]
    assert _is_basemodel_subclass(node)


def test_is_basemodel_subclass_sqlmodel() -> None:
    """T-04: _is_basemodel_subclass detects SQLModel base."""
    src = "class Foo(SQLModel, table=True): pass"
    node = ast.parse(src).body[0]
    assert _is_basemodel_subclass(node)


def test_is_basemodel_subclass_plain_class() -> None:
    """T-05: _is_basemodel_subclass returns False for plain classes."""
    src = "class Foo: pass"
    node = ast.parse(src).body[0]
    assert not _is_basemodel_subclass(node)


def test_collect_test_references_attribute() -> None:
    """T-06: _collect_test_references finds attribute access patterns."""
    with tempfile.TemporaryDirectory() as tmp:
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_item.py").write_text("def test_x():\n    item.title\n    item.price\n")
        refs = _collect_test_references(tests_dir)
        assert "title" in refs
        assert "price" in refs


def test_collect_test_references_string_keys() -> None:
    """T-07: _collect_test_references finds dict key string literals."""
    with tempfile.TemporaryDirectory() as tmp:
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_item.py").write_text("d = {'email': 'a@b.com', 'password': 's'}\n")
        refs = _collect_test_references(tests_dir)
        assert "email" in refs
        assert "password" in refs


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-08: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="sc_t08")
    result = schema_coverage(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-09: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="sc_t09")
    schema_coverage(ToolInput(project_dir=str(project)))
    result = schema_coverage(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-10: scripts/schema_coverage.py is created."""
    project = create_fixture_project(name="sc_t10")
    schema_coverage(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "schema_coverage.py").exists()


def test_orchestrator_parses() -> None:
    """T-11: scripts/schema_coverage.py has no syntax errors."""
    project = create_fixture_project(name="sc_t11")
    schema_coverage(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "schema_coverage.py")


def test_orchestrator_has_class() -> None:
    """T-12: scripts/schema_coverage.py contains SchemaCoverageAnalyzer."""
    project = create_fixture_project(name="sc_t12")
    schema_coverage(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "schema_coverage.py").read_text()
    assert "SchemaCoverageAnalyzer" in content


def test_exclusion_yaml_created() -> None:
    """T-13: .schema-coverage-exclude.yaml is created."""
    project = create_fixture_project(name="sc_t13")
    schema_coverage(ToolInput(project_dir=str(project)))
    assert (project / ".schema-coverage-exclude.yaml").exists()


def test_exclusion_yaml_has_expiry() -> None:
    """T-14: .schema-coverage-exclude.yaml mentions expiry."""
    project = create_fixture_project(name="sc_t14")
    schema_coverage(ToolInput(project_dir=str(project)))
    content = (project / ".schema-coverage-exclude.yaml").read_text()
    assert "expiry" in content


def test_coverage_report_created() -> None:
    """T-15: schema-coverage.json is created."""
    project = create_fixture_project(name="sc_t15")
    schema_coverage(ToolInput(project_dir=str(project)))
    assert (project / "schema-coverage.json").exists()


def test_coverage_report_is_valid_json() -> None:
    """T-16: schema-coverage.json is valid JSON with expected keys."""
    project = create_fixture_project(name="sc_t16")
    schema_coverage(ToolInput(project_dir=str(project)))
    data = json.loads((project / "schema-coverage.json").read_text())
    assert "overall_coverage_pct" in data
    assert "schemas" in data


def test_ci_workflow_created() -> None:
    """T-17: .github/workflows/schema-coverage.yml is created."""
    project = create_fixture_project(name="sc_t17")
    schema_coverage(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "schema-coverage.yml").exists()


def test_dry_run_no_files_written() -> None:
    """T-18: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="sc_t18")
    result = schema_coverage(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "scripts" / "schema_coverage.py").exists()


def test_run_analysis_returns_schema_dict() -> None:
    """T-19: _run_analysis returns dict with overall_coverage_pct and schemas."""
    with tempfile.TemporaryDirectory() as tmp:
        app_dir = Path(tmp) / "app"
        _make_schema_file(Path(tmp), textwrap.dedent("""\
            from pydantic import BaseModel
            class Item(BaseModel):
                title: str
                price: float
        """))
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_item.py").write_text("item.title\n")
        result = _run_analysis(app_dir, tests_dir)
        assert "overall_coverage_pct" in result
        assert isinstance(result["schemas"], dict)


def test_run_analysis_detects_orphans() -> None:
    """T-20: _run_analysis detects fields not referenced in tests."""
    with tempfile.TemporaryDirectory() as tmp:
        _make_schema_file(Path(tmp), textwrap.dedent("""\
            from pydantic import BaseModel
            class Item(BaseModel):
                title: str
                orphan_field: str
        """))
        tests_dir = Path(tmp) / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_item.py").write_text("item.title\n")
        app_dir = Path(tmp) / "app"
        result = _run_analysis(app_dir, tests_dir)
        item_data = result["schemas"].get("Item", {})
        assert "orphan_field" in item_data.get("orphan_fields", [])


def test_files_created_all_exist() -> None:
    """T-21: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="sc_t21")
    result = schema_coverage(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_mention_coverage_pct() -> None:
    """T-22: notes mention overall coverage percentage."""
    project = create_fixture_project(name="sc_t22")
    result = schema_coverage(ToolInput(project_dir=str(project)))
    combined = " ".join(result.notes)
    assert "coverage" in combined.lower()


# ---------------------------------------------------------------------------
# Self-runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
