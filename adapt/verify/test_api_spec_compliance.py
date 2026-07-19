"""Tests for TOOL-033 api_spec_compliance.

Verifies idempotency, orchestrator creation, diff algorithm correctness,
documentation gate, semver suggestion, snapshot lifecycle, and CI workflow.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_api_spec_compliance.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.api_spec_compliance import (
    api_spec_compliance,
    check_documentation,
    diff_openapi,
    suggest_semver,
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


_BASE_SCHEMA: dict = {
    "openapi": "3.1.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/items/": {
            "get": {
                "summary": "List items",
                "description": "Returns a paginated list of items.",
                "tags": ["items"],
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


# ---------------------------------------------------------------------------
# Unit tests for diff + doc gate helpers
# ---------------------------------------------------------------------------

def test_diff_no_changes() -> None:
    """T-01: diff_openapi returns empty list when schemas are identical."""
    changes = diff_openapi(_BASE_SCHEMA, _BASE_SCHEMA)
    assert changes == []


def test_diff_breaking_removed_route() -> None:
    """T-02: Removed route is classified as BREAKING."""
    new_schema = {"paths": {}, "info": {}}
    changes = diff_openapi(_BASE_SCHEMA, new_schema)
    breaking = [c for c in changes if c["type"] == "BREAKING"]
    assert breaking


def test_diff_non_breaking_added_route() -> None:
    """T-03: Added route is classified as NON_BREAKING."""
    new_schema = dict(_BASE_SCHEMA)
    new_schema["paths"] = dict(_BASE_SCHEMA["paths"])
    new_schema["paths"]["/users/"] = {"get": {}}
    changes = diff_openapi(_BASE_SCHEMA, new_schema)
    non_breaking = [c for c in changes if c["type"] == "NON_BREAKING"]
    assert non_breaking


def test_diff_metadata_description_change() -> None:
    """T-04: Info description change is classified as METADATA."""
    old = {"paths": {}, "info": {"description": "v1"}}
    new = {"paths": {}, "info": {"description": "v2"}}
    changes = diff_openapi(old, new)
    metadata = [c for c in changes if c["type"] == "METADATA"]
    assert metadata


def test_suggest_semver_breaking() -> None:
    """T-05: suggest_semver returns 'major' for BREAKING changes."""
    changes = [{"type": "BREAKING", "path": "/items/", "description": "removed"}]
    assert suggest_semver(changes) == "major"


def test_suggest_semver_non_breaking() -> None:
    """T-06: suggest_semver returns 'minor' for NON_BREAKING changes."""
    changes = [{"type": "NON_BREAKING", "path": "/users/", "description": "added"}]
    assert suggest_semver(changes) == "minor"


def test_suggest_semver_metadata_only() -> None:
    """T-07: suggest_semver returns 'patch' for METADATA-only changes."""
    changes = [{"type": "METADATA", "path": "info.description", "description": "changed"}]
    assert suggest_semver(changes) == "patch"


def test_suggest_semver_empty() -> None:
    """T-08: suggest_semver returns 'patch' for no changes."""
    assert suggest_semver([]) == "patch"


def test_check_documentation_no_violations() -> None:
    """T-09: check_documentation passes for well-documented routes."""
    violations = check_documentation(_BASE_SCHEMA)
    assert violations == []


def test_check_documentation_missing_summary() -> None:
    """T-10: check_documentation flags missing summary."""
    schema = {
        "paths": {"/items/": {"get": {"description": "A long description here", "tags": ["items"], "responses": {"200": {}}}}}
    }
    violations = check_documentation(schema)
    assert any("summary" in v["violations"][0] for v in violations)


def test_check_documentation_short_description() -> None:
    """T-11: check_documentation flags description < 20 chars."""
    schema = {
        "paths": {"/items/": {"get": {"summary": "List", "description": "Short", "tags": ["items"], "responses": {"200": {}}}}}
    }
    violations = check_documentation(schema)
    assert any("description" in " ".join(v["violations"]) for v in violations)


def test_check_documentation_missing_tags() -> None:
    """T-12: check_documentation flags missing tags."""
    schema = {
        "paths": {"/items/": {"get": {"summary": "List items", "description": "Returns a list of all items.", "responses": {"200": {}}}}}
    }
    violations = check_documentation(schema)
    assert any("tag" in " ".join(v["violations"]) for v in violations)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-13: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="asc_t13")
    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-14: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="asc_t14")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_orchestrator_created() -> None:
    """T-15: scripts/api_spec_compliance.py is created."""
    project = create_fixture_project(name="asc_t15")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    assert (project / "scripts" / "api_spec_compliance.py").exists()


def test_orchestrator_parses() -> None:
    """T-16: scripts/api_spec_compliance.py has no syntax errors."""
    project = create_fixture_project(name="asc_t16")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "scripts" / "api_spec_compliance.py")


def test_orchestrator_has_class() -> None:
    """T-17: Orchestrator contains APISpecComplianceChecker class."""
    project = create_fixture_project(name="asc_t17")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    content = (project / "scripts" / "api_spec_compliance.py").read_text()
    assert "APISpecComplianceChecker" in content


def test_diff_rules_created() -> None:
    """T-18: .api-diff-rules.yaml is created."""
    project = create_fixture_project(name="asc_t18")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    assert (project / ".api-diff-rules.yaml").exists()


def test_diff_rules_has_breaking_category() -> None:
    """T-19: .api-diff-rules.yaml has a breaking category."""
    project = create_fixture_project(name="asc_t19")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    content = (project / ".api-diff-rules.yaml").read_text()
    assert "breaking" in content.lower()


def test_ci_workflow_created() -> None:
    """T-20: .github/workflows/api-spec-compliance.yml is created."""
    project = create_fixture_project(name="asc_t20")
    api_spec_compliance(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "api-spec-compliance.yml").exists()


def test_dry_run_no_files_written() -> None:
    """T-21: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="asc_t21")
    result = api_spec_compliance(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "scripts" / "api_spec_compliance.py").exists()


def test_files_created_all_exist() -> None:
    """T-22: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="asc_t22")
    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_notes_mention_breaking_changes() -> None:
    """T-23: notes mention BREAKING classification."""
    project = create_fixture_project(name="asc_t23")
    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    combined = " ".join(result.notes + result.next_steps).upper()
    assert "BREAKING" in combined


def test_next_steps_mention_update_snapshot() -> None:
    """T-24: next_steps mention --update-snapshot."""
    project = create_fixture_project(name="asc_t24")
    result = api_spec_compliance(ToolInput(project_dir=str(project)))
    combined = " ".join(result.next_steps)
    assert "snapshot" in combined.lower()


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
