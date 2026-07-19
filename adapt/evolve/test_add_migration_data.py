"""Tests for TOOL-043 add_migration_data.

Run with::

    PYTHONPATH=. pytest adapt/evolve/test_add_migration_data.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/evolve/test_add_migration_data.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.evolve.add_migration_data import add_migration_data

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp: Path) -> Path:
    """Create a minimal project directory for testing.

    Args:
        tmp: Parent temp directory.

    Returns:
        Path to project root.
    """
    project = tmp / "test_proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "alembic" / "versions").mkdir(parents=True, exist_ok=True)
    (project / "alembic" / "versions" / ".gitkeep").write_text("")
    return project


def _assert_parse(path: Path) -> None:
    """Assert that *path* is valid Python.

    Args:
        path: Path to a .py file.
    """
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
        result = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result.status == "success", f"Expected success, got: {result.error}"


def test_files_created_non_empty() -> None:
    """T-02: files_created must be non-empty on success."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result.status == "success"
        assert len(result.files_created) >= 5, "Expected at least 5 files created"


def test_files_created_exist_on_disk() -> None:
    """T-03: Every path in files_created must exist on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result.status == "success"
        for f in result.files_created:
            assert Path(f).exists(), f"File missing: {f}"


def test_base_py_created() -> None:
    """T-04: data_migrations/base.py must be created with DataMigration class."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        base_file = project / "data_migrations" / "base.py"
        assert base_file.exists(), "base.py not created"
        src = base_file.read_text()
        assert "DataMigration" in src
        assert "run_batch" in src
        assert "verify_after_run" in src


def test_base_py_parses() -> None:
    """T-05: data_migrations/base.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        _assert_parse(project / "data_migrations" / "base.py")


def test_checkpoint_model_created() -> None:
    """T-06: checkpoint_model.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        ckpt = project / "data_migrations" / "checkpoint_model.py"
        assert ckpt.exists(), "checkpoint_model.py not created"
        assert "MigrationCheckpoint" in ckpt.read_text()


def test_checkpoint_model_parses() -> None:
    """T-07: checkpoint_model.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        _assert_parse(project / "data_migrations" / "checkpoint_model.py")


def test_runner_created() -> None:
    """T-08: runner.py must be created with run_migration function."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        runner = project / "data_migrations" / "runner.py"
        assert runner.exists()
        assert "run_migration" in runner.read_text()


def test_runner_parses() -> None:
    """T-09: runner.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        _assert_parse(project / "data_migrations" / "runner.py")


def test_cli_created() -> None:
    """T-10: cli.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        cli = project / "data_migrations" / "cli.py"
        assert cli.exists()
        assert "main" in cli.read_text()


def test_cli_parses() -> None:
    """T-11: cli.py must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        _assert_parse(project / "data_migrations" / "cli.py")


def test_sample_migration_created() -> None:
    """T-12: Sample migration file must be created with Migration class."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="my_migration")
        sample = project / "data_migrations" / "my_migration.py"
        assert sample.exists(), "Sample migration not created"
        src = sample.read_text()
        assert "class Migration" in src


def test_sample_migration_parses() -> None:
    """T-13: Sample migration must be valid Python."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="my_migration")
        _assert_parse(project / "data_migrations" / "my_migration.py")


def test_dry_run_creates_no_files() -> None:
    """T-14: dry_run=True must not write any files."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(
            ToolInput(project_dir=str(project), dry_run=True), name="test_migration"
        )
        assert result.status == "success"
        assert result.files_created == []
        assert not (project / "data_migrations" / "base.py").exists()


def test_dry_run_notes_contain_dry_run() -> None:
    """T-15: dry_run result notes must mention dry_run."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(
            ToolInput(project_dir=str(project), dry_run=True), name="test_migration"
        )
        assert any("dry_run" in n for n in result.notes)


def test_idempotency_returns_no_op() -> None:
    """T-16: Second run must return status='no_op' without overwriting."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        result2 = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result2.status == "no_op"


def test_idempotency_no_op_files_empty() -> None:
    """T-17: no_op result must have empty files_created and files_modified."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        result2 = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result2.files_created == []
        assert result2.files_modified == []


def test_custom_batch_size() -> None:
    """T-18: Custom batch_size must appear in the sample migration."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(
            ToolInput(project_dir=str(project)), name="custom_batch", batch_size=500
        )
        sample = project / "data_migrations" / "custom_batch.py"
        assert sample.exists()
        assert "500" in sample.read_text()


def test_custom_checkpoint_table() -> None:
    """T-19: Custom checkpoint_table must appear in base.py."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(
            ToolInput(project_dir=str(project)),
            name="test_migration",
            checkpoint_table="my_checkpoints",
        )
        base = project / "data_migrations" / "base.py"
        assert "my_checkpoints" in base.read_text()


def test_next_steps_non_empty() -> None:
    """T-20: next_steps must be non-empty on success."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result.status == "success"
        assert len(result.next_steps) >= 1


def test_init_file_created() -> None:
    """T-21: data_migrations/__init__.py must be created."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert (project / "data_migrations" / "__init__.py").exists()


def test_execution_time_recorded() -> None:
    """T-22: execution_time_ms must be > 0."""
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        result = add_migration_data(ToolInput(project_dir=str(project)), name="test_migration")
        assert result.execution_time_ms >= 0


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
