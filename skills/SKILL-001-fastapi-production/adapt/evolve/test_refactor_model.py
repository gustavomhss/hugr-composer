"""Tests for TOOL-044 refactor_model.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_refactor_model.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_refactor_model.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.refactor_model import refactor_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path, with_model: bool = True) -> Path:
    """Create a minimal project with an optional model file.

    Args:
        tmp: Parent temp directory.
        with_model: Whether to create a sample model file.

    Returns:
        Path to project root.
    """
    project = tmp / "refactor_proj"
    project.mkdir(parents=True, exist_ok=True)
    if with_model:
        app_dir = project / "app" / "models"
        app_dir.mkdir(parents=True, exist_ok=True)
        model_file = app_dir / "user.py"
        model_file.write_text(
            "from app.models.base import Base\n\nclass User(Base):\n    email: str\n"
        )
    return project


def _assert_parse(path: Path) -> None:
    src = path.read_text()
    try:
        ast.parse(src)
    except SyntaxError as exc:
        raise AssertionError(f"SyntaxError in {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_invalid_operation_returns_error() -> None:
    """T-01: Unknown operation must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="invalid_op",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.status == "error"
        assert "invalid_op" in result.error


def test_missing_target_returns_error() -> None:
    """T-02: Missing target must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="",
            new_name="email_address",
        )
        assert result.status == "error"


def test_missing_new_name_returns_error() -> None:
    """T-03: Missing new_name must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="",
        )
        assert result.status == "error"


def test_same_name_returns_no_op() -> None:
    """T-04: Same old and new name must return status='no_op'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email",
        )
        assert result.status == "no_op"


def test_success_status_rename_field() -> None:
    """T-05: rename_field must return status='success'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.status == "success", f"Expected success: {result.error}"


def test_patch_file_created() -> None:
    """T-06: A .patch file must be created in .refactor_patches/."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        patches_dir = project / ".refactor_patches"
        assert patches_dir.exists()
        patches = list(patches_dir.glob("*.patch"))
        assert len(patches) >= 1, "No .patch file created"


def test_patch_file_contains_diff() -> None:
    """T-07: Patch file must contain a unified diff for changed files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        patches_dir = project / ".refactor_patches"
        patch_files = list(patches_dir.glob("*.patch"))
        assert patch_files
        content = patch_files[0].read_text()
        assert "email_address" in content or "email" in content


def test_dry_run_creates_no_files() -> None:
    """T-08: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project), dry_run=True),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / ".refactor_patches").exists()


def test_dry_run_reports_occurrences() -> None:
    """T-09: dry_run notes must mention occurrence count."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project), dry_run=True),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert any("dry_run" in n.lower() or "occurrence" in n.lower() for n in result.notes)


def test_apply_modifies_files() -> None:
    """T-10: apply=True must rewrite model file in-place."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
            apply=True,
        )
        model_content = (project / "app" / "models" / "user.py").read_text()
        assert "email_address" in model_content


def test_apply_files_parse_after_rename() -> None:
    """T-11: All .py files must still parse after apply=True rename."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
            apply=True,
        )
        for py_file in project.rglob("*.py"):
            _assert_parse(py_file)


def test_schema_alias_note_created_for_rename_field() -> None:
    """T-12: A schema alias note must be created for rename_field."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.status == "success"
        alias_notes = [f for f in result.files_created if "alias" in f]
        assert alias_notes, "No schema alias note created"


def test_alembic_migration_created_when_versions_exist() -> None:
    """T-13: Alembic migration must be created when alembic/versions/ exists."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        versions_dir = project / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
            generate_migration=True,
        )
        assert result.status == "success"
        migrations = list(versions_dir.glob("*.py"))
        assert migrations, "No Alembic migration created"


def test_alembic_migration_parses() -> None:
    """T-14: Generated Alembic migration must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        versions_dir = project / "alembic" / "versions"
        versions_dir.mkdir(parents=True)
        refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
            generate_migration=True,
        )
        for mig in versions_dir.glob("*.py"):
            _assert_parse(mig)


def test_next_steps_include_alembic() -> None:
    """T-15: next_steps must mention alembic."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert any("alembic" in s.lower() for s in result.next_steps)


def test_rename_model_operation() -> None:
    """T-16: rename_model operation must succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_model",
            target="app.models.User",
            new_name="Account",
        )
        assert result.status == "success"


def test_change_type_operation() -> None:
    """T-17: change_type operation must succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="change_type",
            target="app.models.User.email",
            new_name="EmailStr",
        )
        assert result.status == "success"


def test_split_model_operation() -> None:
    """T-18: split_model operation must succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="split_model",
            target="app.models.User",
            new_name="UserProfile",
        )
        assert result.status == "success"


def test_execution_time_recorded() -> None:
    """T-19: execution_time_ms must be >= 0."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.execution_time_ms >= 0


def test_notes_contain_operation_info() -> None:
    """T-20: notes must contain operation and name info."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = refactor_model(
            ToolInput(project_dir=str(project)),
            operation="rename_field",
            target="app.models.User.email",
            new_name="email_address",
        )
        assert result.status == "success"
        full_notes = " ".join(result.notes)
        assert "email" in full_notes or "rename" in full_notes.lower()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_functions = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in test_functions:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "OK" if failed == 0 else f"({failed} FAILED)")
    sys.exit(0 if failed == 0 else 1)
