"""Tests for TOOL-048 generate_admin_panel.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_generate_admin_panel.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_generate_admin_panel.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.generate_admin_panel import generate_admin_panel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path, models: list[str] | None = None) -> Path:
    """Create a minimal FastAPI project with SQLAlchemy models.

    Args:
        tmp: Parent temp directory.
        models: Model names to create stub files for.

    Returns:
        Path to project root.
    """
    project = tmp / "admin_proj"
    project.mkdir(parents=True, exist_ok=True)
    app_dir = project / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    models_dir = app_dir / "models"
    models_dir.mkdir()
    (models_dir / "base.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\nclass Base(DeclarativeBase): pass\n"
    )
    for model in (models or ["user", "item"]):
        (models_dir / f"{model.lower()}.py").write_text(
            f"from app.models.base import Base\nclass {model.capitalize()}(Base):\n    __tablename__ = '{model.lower()}s'\n"
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


def test_success_status() -> None:
    """T-01: Tool returns status='success' on fresh project."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User", "Item"]
        )
        assert result.status == "success", f"Expected success: {result.error}"


def test_no_models_found_returns_error() -> None:
    """T-02: No models found must return status='error'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "empty_proj"
        project.mkdir()
        (project / "app").mkdir()
        (project / "app" / "models").mkdir()
        result = generate_admin_panel(ToolInput(project_dir=str(project)))
        assert result.status == "error"


def test_admin_init_created() -> None:
    """T-03: app/admin/__init__.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User", "Item"])
        assert (project / "app" / "admin" / "__init__.py").exists()


def test_admin_init_parses() -> None:
    """T-04: admin/__init__.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        _assert_parse(project / "app" / "admin" / "__init__.py")


def test_admin_init_contains_sqladmin() -> None:
    """T-05: admin/__init__.py must reference sqladmin."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        src = (project / "app" / "admin" / "__init__.py").read_text()
        assert "sqladmin" in src


def test_auth_file_created() -> None:
    """T-06: app/admin/auth.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        assert (project / "app" / "admin" / "auth.py").exists()


def test_auth_file_parses() -> None:
    """T-07: auth.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        _assert_parse(project / "app" / "admin" / "auth.py")


def test_audit_file_created() -> None:
    """T-08: app/admin/audit.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        assert (project / "app" / "admin" / "audit.py").exists()


def test_audit_file_parses() -> None:
    """T-09: audit.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        _assert_parse(project / "app" / "admin" / "audit.py")


def test_view_files_created_per_model() -> None:
    """T-10: A view file must exist for each model."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User", "Item"]
        )
        views_dir = project / "app" / "admin" / "views"
        assert (views_dir / "user_view.py").exists()
        assert (views_dir / "item_view.py").exists()


def test_view_files_parse() -> None:
    """T-11: All view files must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User", "Item"]
        )
        for view_file in (project / "app" / "admin" / "views").glob("*_view.py"):
            _assert_parse(view_file)


def test_read_only_view_has_can_false() -> None:
    """T-12: Read-only view must set can_create/can_edit/can_delete = False."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)),
            models=["User"],
            read_only_models=["User"],
        )
        src = (project / "app" / "admin" / "views" / "user_view.py").read_text()
        assert "can_create = False" in src
        assert "can_edit = False" in src
        assert "can_delete = False" in src


def test_writable_view_has_can_true() -> None:
    """T-13: Writable view must set can_create/can_edit/can_delete = True."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)),
            models=["Item"],
            read_only_models=[],
        )
        src = (project / "app" / "admin" / "views" / "item_view.py").read_text()
        assert "can_create = True" in src


def test_csv_export_cap_present() -> None:
    """T-14: export_max_rows must be set in every view."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User"]
        )
        src = (project / "app" / "admin" / "views" / "user_view.py").read_text()
        assert "export_max_rows" in src


def test_audit_log_model_created() -> None:
    """T-15: app/models/audit_log.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User"]
        )
        assert (project / "app" / "models" / "audit_log.py").exists()


def test_audit_log_model_parses() -> None:
    """T-16: audit_log.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        _assert_parse(project / "app" / "models" / "audit_log.py")


def test_idempotency_returns_no_op() -> None:
    """T-17: Second run must return status='no_op'."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        result2 = generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User"]
        )
        assert result2.status == "no_op"


def test_dry_run_creates_no_files() -> None:
    """T-18: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_admin_panel(
            ToolInput(project_dir=str(project), dry_run=True), models=["User"]
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "app" / "admin").exists()


def test_mount_path_in_admin_init() -> None:
    """T-19: Admin __init__.py must reference the configured mount path."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(
            ToolInput(project_dir=str(project)),
            models=["User"],
            mount_path="/management",
        )
        src = (project / "app" / "admin" / "__init__.py").read_text()
        assert "/management" in src


def test_next_steps_non_empty() -> None:
    """T-20: next_steps must be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = generate_admin_panel(
            ToolInput(project_dir=str(project)), models=["User"]
        )
        assert len(result.next_steps) >= 1


def test_test_file_created() -> None:
    """T-21: tests/test_admin_panel.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        assert (project / "tests" / "test_admin_panel.py").exists()


def test_test_file_parses() -> None:
    """T-22: test_admin_panel.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        generate_admin_panel(ToolInput(project_dir=str(project)), models=["User"])
        _assert_parse(project / "tests" / "test_admin_panel.py")


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
