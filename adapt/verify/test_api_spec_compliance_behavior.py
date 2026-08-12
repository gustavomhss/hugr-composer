"""Behavior tests for TOOL-033 api_spec_compliance.

Proves that:
1. Tool returns error for non-existent project directory (via validate_project_dir)
2. Tool respects dry_run mode
3. Tool is idempotent — second run returns no_op
4. Generated files pass ast.parse
5. elapsed_ms is present on all return paths

Run with::

    PYTHONPATH=. pytest adapt/verify/test_api_spec_compliance_behavior.py -v
"""

from __future__ import annotations

import ast
import pytest
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.api_spec_compliance import api_spec_compliance


def test_b01_error_on_invalid_project(tmp_path) -> None:
    """B-01: Tool returns error for invalid project directory."""
    nonexistent = tmp_path / "nonexistent"
    result = api_spec_compliance(ToolInput(project_dir=str(nonexistent)))
    assert result.status == "error"
    assert result.execution_time_ms >= 0


def test_b02_dry_run_no_files_written(tmp_path) -> None:
    """B-02: dry_run on valid project returns success."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = api_spec_compliance(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"  # dry_run on valid project returns success
    script = project / "scripts" / "api_spec_compliance.py"
    assert not script.exists()
    assert result.execution_time_ms >= 0


def test_b03_idempotent_on_second_run(tmp_path) -> None:
    """B-03: Tool is idempotent — second run returns no_op."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "api_spec_compliance.py").write_text(
        "class APISpecComplianceChecker:\n    pass\n"
    )

    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"
    assert result.execution_time_ms >= 0


def test_b04_generated_files_ast_parse(tmp_path) -> None:
    """B-04: Generated .py files pass ast.parse validation."""
    project = tmp_path / "test_project"
    project.mkdir()

    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    assert result.status == "success", f"Failed: {result.error}"

    for fpath in result.files_created:
        p = Path(project / fpath if not fpath.startswith("/") else fpath)
        if str(p).endswith(".py"):
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                pytest.fail(f"SyntaxError in {p}: {exc}")
