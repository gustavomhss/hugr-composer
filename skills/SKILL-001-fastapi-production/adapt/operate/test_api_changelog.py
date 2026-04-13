"""Tests for TOOL-038 api_changelog.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_api_changelog.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.api_changelog import (
    api_changelog,
    _diff_specs,
    _suggest_semver,
    _render_section,
    _change,
    _get_tag,
    _prepend_section,
    _BREAKING,
    _ADDED,
    _CHANGED,
    _REMOVED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_SPEC: dict = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "summary": "List items",
                "tags": ["items"],
                "parameters": [{"name": "limit", "in": "query"}],
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
    "components": {"schemas": {"Item": {"type": "object"}}},
}


def _make_project_with_specs(tmp: Path, old: dict, new: dict) -> Path:
    """Create a project with two OpenAPI snapshots on disk."""
    proj = tmp / "proj"
    proj.mkdir()
    (proj / "openapi.json").write_text(json.dumps(new))
    old_dir = proj / ".openapi"
    old_dir.mkdir()
    (old_dir / "v1.0.0.json").write_text(json.dumps(old))
    return proj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = api_changelog(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"


def test_dry_run_no_files() -> None:
    """T-03: dry_run=True writes no files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project_with_specs(Path(tmp), _MINIMAL_SPEC, _MINIMAL_SPEC)
        before = list(proj.rglob("*"))
        result = api_changelog(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert not result.files_modified


def test_identical_specs_no_changes() -> None:
    """T-04: Identical specs produce an empty changes list."""
    changes = _diff_specs(_MINIMAL_SPEC, _MINIMAL_SPEC)
    assert changes == []


def test_added_route_detected() -> None:
    """T-05: New route detected as ADDED."""
    old = {"paths": {}, "components": {"schemas": {}}}
    new = {"paths": {"/new": {"get": {"tags": ["x"], "summary": "new", "responses": {}}}}, "components": {"schemas": {}}}
    changes = _diff_specs(old, new)
    assert any(c["category"] == _ADDED for c in changes)


def test_removed_route_detected_as_breaking() -> None:
    """T-06: Removed route detected as BREAKING."""
    old = {"paths": {"/old": {"get": {"tags": ["x"], "summary": "old", "responses": {}}}}, "components": {"schemas": {}}}
    new = {"paths": {}, "components": {"schemas": {}}}
    changes = _diff_specs(old, new)
    assert any(c["category"] == _BREAKING for c in changes)


def test_removed_parameter_breaking() -> None:
    """T-07: Removed parameter detected as BREAKING."""
    old = {"paths": {"/x": {"get": {"parameters": [{"name": "id"}], "tags": ["x"], "responses": {}}}}, "components": {}}
    new = {"paths": {"/x": {"get": {"parameters": [], "tags": ["x"], "responses": {}}}}, "components": {}}
    changes = _diff_specs(old, new)
    assert any(c["category"] == _BREAKING for c in changes)


def test_added_schema_detected() -> None:
    """T-08: New schema detected as ADDED."""
    old = {"paths": {}, "components": {"schemas": {}}}
    new = {"paths": {}, "components": {"schemas": {"NewModel": {"type": "object"}}}}
    changes = _diff_specs(old, new)
    assert any(c["category"] == _ADDED and "NewModel" in c["description"] for c in changes)


def test_removed_schema_detected() -> None:
    """T-09: Removed schema detected as REMOVED."""
    old = {"paths": {}, "components": {"schemas": {"OldModel": {"type": "object"}}}}
    new = {"paths": {}, "components": {"schemas": {}}}
    changes = _diff_specs(old, new)
    assert any(c["category"] == _REMOVED for c in changes)


def test_semver_major_on_breaking() -> None:
    """T-10: Breaking change suggests major version bump."""
    changes = [_change(_BREAKING, "/x", "get", "t", "desc")]
    assert _suggest_semver(changes) == "major"


def test_semver_minor_on_added() -> None:
    """T-11: Added route suggests minor version bump."""
    changes = [_change(_ADDED, "/new", "get", "t", "desc")]
    assert _suggest_semver(changes) == "minor"


def test_semver_patch_on_empty() -> None:
    """T-12: No changes suggests patch version bump."""
    assert _suggest_semver([]) == "patch"


def test_render_section_keepachangelog() -> None:
    """T-13: Rendered section includes changelog header and categories."""
    changes = [
        _change(_BREAKING, "/x", "delete", "users", "Route removed."),
        _change(_ADDED, "/y", "post", "orders", "New order endpoint."),
    ]
    section = _render_section(changes, "v1.0.0", "HEAD", "major", "keepachangelog", True)
    assert "Unreleased" in section
    assert "BREAKING" in section
    assert "ADDED" in section


def test_render_section_breaking_prefix() -> None:
    """T-14: include_breaking_prefix=True prepends BREAKING: to descriptions."""
    changes = [_change(_BREAKING, "/x", "delete", "general", "Route removed.")]
    section = _render_section(changes, "v1", "HEAD", "major", "keepachangelog", True)
    assert "BREAKING:" in section


def test_render_section_no_breaking_prefix() -> None:
    """T-15: include_breaking_prefix=False omits BREAKING: prefix."""
    changes = [_change(_BREAKING, "/x", "delete", "general", "Route removed.")]
    section = _render_section(changes, "v1", "HEAD", "major", "keepachangelog", False)
    assert "BREAKING:" not in section


def test_changelog_file_written() -> None:
    """T-16: api_changelog writes a CHANGELOG.md file."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project_with_specs(Path(tmp), _MINIMAL_SPEC, _MINIMAL_SPEC)
        result = api_changelog(
            ToolInput(project_dir=str(proj)),
            from_ref="local",
            to_ref="local",
        )
        assert result.status == "success"
        assert result.files_modified
        assert Path(result.files_modified[0]).exists()


def test_prepend_section_creates_file() -> None:
    """T-17: _prepend_section creates the file if it does not exist."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "CHANGELOG.md"
        _prepend_section(p, "## My Section\n")
        assert p.exists()
        assert "My Section" in p.read_text()


def test_prepend_section_preserves_existing() -> None:
    """T-18: _prepend_section preserves existing changelog content."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "CHANGELOG.md"
        p.write_text("## Old Content\n")
        _prepend_section(p, "## New Section\n")
        text = p.read_text()
        assert "New Section" in text
        assert "Old Content" in text


def test_get_tag_returns_first_tag() -> None:
    """T-19: _get_tag returns the first tag from operation."""
    op = {"tags": ["users", "admin"], "summary": "op"}
    assert _get_tag(op) == "users"


def test_get_tag_default_general() -> None:
    """T-20: _get_tag returns 'general' when no tags present."""
    op = {"summary": "no tags"}
    assert _get_tag(op) == "general"


def test_notes_contain_semver() -> None:
    """T-21: notes include semver suggestion."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project_with_specs(Path(tmp), _MINIMAL_SPEC, _MINIMAL_SPEC)
        result = api_changelog(
            ToolInput(project_dir=str(proj)),
            from_ref="local",
            to_ref="local",
        )
        assert result.status == "success"
        assert any("semver" in n.lower() or "bump" in n.lower() for n in (result.notes or []))


def test_execution_time_recorded() -> None:
    """T-22: execution_time_ms is non-negative."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = _make_project_with_specs(Path(tmp), _MINIMAL_SPEC, _MINIMAL_SPEC)
        result = api_changelog(
            ToolInput(project_dir=str(proj)),
            from_ref="local",
            to_ref="local",
        )
        assert result.execution_time_ms >= 0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_dry_run_no_files,
        test_identical_specs_no_changes,
        test_added_route_detected,
        test_removed_route_detected_as_breaking,
        test_removed_parameter_breaking,
        test_added_schema_detected,
        test_removed_schema_detected,
        test_semver_major_on_breaking,
        test_semver_minor_on_added,
        test_semver_patch_on_empty,
        test_render_section_keepachangelog,
        test_render_section_breaking_prefix,
        test_render_section_no_breaking_prefix,
        test_changelog_file_written,
        test_prepend_section_creates_file,
        test_prepend_section_preserves_existing,
        test_get_tag_returns_first_tag,
        test_get_tag_default_general,
        test_notes_contain_semver,
        test_execution_time_recorded,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
