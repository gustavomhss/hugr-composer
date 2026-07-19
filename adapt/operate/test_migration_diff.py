"""Tests for TOOL-036 migration_diff.

Run with::

    PYTHONPATH=. python3 adapt/operate/test_migration_diff.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.operate.migration_diff import (
    _classify_ops,
    _detect_multi_phase,
    _extract_ops,
    _is_allow_listed,
    _rollback_distance,
    _sha256,
    migration_diff,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_migration_dir(tmp: Path) -> tuple[Path, Path]:
    """Create an alembic/versions directory with sample migration files."""
    proj = tmp / "proj"
    versions = proj / "alembic" / "versions"
    versions.mkdir(parents=True)
    return proj, versions


def _write_migration(versions: Path, name: str, body: str) -> Path:
    """Write a migration file with the given upgrade() body."""
    content = f"""\
\"\"\"Migration {name}.\"\"\"
from alembic import op
import sqlalchemy as sa

revision = "{name}"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
{body}

def downgrade() -> None:
    pass
"""
    f = versions / f"{name}.py"
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_error_missing_project() -> None:
    """T-01: Returns error for nonexistent project_dir."""
    result = migration_diff(ToolInput(project_dir="/nonexistent"))
    assert result.status == "error"
    assert "does not exist" in (result.error or "")


def test_error_no_versions_dir() -> None:
    """T-02: Returns error when alembic/versions/ is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "nodb"
        proj.mkdir()
        result = migration_diff(ToolInput(project_dir=str(proj)))
        assert result.status == "error"
        assert "alembic" in (result.error or "").lower()


def test_dry_run_no_files() -> None:
    """T-03: dry_run returns success without writing files."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        _write_migration(versions, "m001", "    op.add_column('items', sa.Column('x', sa.String()))\n")
        before = set(proj.rglob("*"))
        result = migration_diff(ToolInput(project_dir=str(proj), dry_run=True))
        assert result.status == "success"
        assert set(proj.rglob("*")) == before


def test_safe_migration_passes() -> None:
    """T-04: A purely additive migration returns no errors."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        _write_migration(versions, "m002", "    op.add_column('items', sa.Column('y', sa.String(), nullable=True))\n")
        result = migration_diff(
            ToolInput(project_dir=str(proj)),
            fail_on_destructive=True,
        )
        assert result.status == "success"


def test_destructive_migration_blocked() -> None:
    """T-05: DROP COLUMN returns error when fail_on_destructive=True."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        _write_migration(versions, "m003", "    op.drop_column('items', 'y')\n")
        result = migration_diff(
            ToolInput(project_dir=str(proj)),
            fail_on_destructive=True,
        )
        assert result.status == "error"
        assert "DESTRUCTIVE" in (result.error or "")


def test_destructive_allowed_via_allow_list() -> None:
    """T-06: Destructive op allow-listed by hash passes."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        mig = _write_migration(versions, "m004", "    op.drop_column('items', 'z')\n")
        file_hash = _sha256(mig)
        allow_file = proj / ".migration-allow.yaml"
        allow_file.write_text(f"m004.py:\n  sha256: {file_hash}\n  reason: approved\n")
        result = migration_diff(
            ToolInput(project_dir=str(proj)),
            fail_on_destructive=True,
            allow_list_file=".migration-allow.yaml",
        )
        assert result.status == "success"


def test_extract_ops_add_column() -> None:
    """T-07: _extract_ops detects add_column."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "m.py"
        f.write_text(
            "from alembic import op\nimport sqlalchemy as sa\n"
            "def upgrade():\n    op.add_column('t', sa.Column('c', sa.String()))\n"
            "def downgrade():\n    pass\n"
        )
        ops = _extract_ops(f)
        assert any(o["type"] == "add_column" for o in ops)


def test_extract_ops_drop_table() -> None:
    """T-08: _extract_ops detects drop_table."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "m.py"
        f.write_text(
            "from alembic import op\n"
            "def upgrade():\n    op.drop_table('old')\n"
            "def downgrade():\n    pass\n"
        )
        ops = _extract_ops(f)
        assert any(o["type"] == "drop_table" for o in ops)


def test_classify_safe() -> None:
    """T-09: add_column classified as SAFE."""
    ops = [{"type": "add_column", "detail": "items", "func_name": "upgrade"}]
    assert _classify_ops(ops) == "SAFE"


def test_classify_unsafe_rename() -> None:
    """T-10: rename_column classified as UNSAFE."""
    ops = [{"type": "rename_column", "detail": "", "func_name": "upgrade"}]
    assert _classify_ops(ops) == "UNSAFE"


def test_classify_destructive_drop() -> None:
    """T-11: drop_column classified as DESTRUCTIVE."""
    ops = [{"type": "drop_column", "detail": "items", "func_name": "upgrade"}]
    assert _classify_ops(ops) == "DESTRUCTIVE"


def test_classify_execute_destructive() -> None:
    """T-12: raw execute() classified as DESTRUCTIVE."""
    ops = [{"type": "execute", "detail": "", "func_name": "upgrade"}]
    assert _classify_ops(ops) == "DESTRUCTIVE"


def test_classify_empty_is_safe() -> None:
    """T-13: Empty ops list classified as SAFE."""
    assert _classify_ops([]) == "SAFE"


def test_rollback_distance_last_migration() -> None:
    """T-14: Last migration has rollback distance 0."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        m = _write_migration(versions, "m005", "    pass\n")
        dist = _rollback_distance(m, versions)
        assert dist == 0


def test_rollback_distance_first_of_two() -> None:
    """T-15: First of two migrations has rollback distance 1."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        m1 = _write_migration(versions, "a_001", "    pass\n")
        _write_migration(versions, "b_002", "    pass\n")
        dist = _rollback_distance(m1, versions)
        assert dist == 1


def test_detect_multi_phase_true() -> None:
    """T-16: Multi-phase detection triggers on add+alter combo."""
    ops = [
        {"type": "add_column", "detail": "items", "func_name": "upgrade"},
        {"type": "alter_column", "detail": "items", "func_name": "upgrade"},
    ]
    assert _detect_multi_phase(ops, Path("/tmp")) is True


def test_detect_multi_phase_false() -> None:
    """T-17: Multi-phase is False for single add_column."""
    ops = [{"type": "add_column", "detail": "items", "func_name": "upgrade"}]
    assert _detect_multi_phase(ops, Path("/tmp")) is False


def test_sha256_deterministic() -> None:
    """T-18: SHA-256 is deterministic for the same file."""
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.py"
        f.write_text("hello world")
        assert _sha256(f) == _sha256(f)


def test_is_allow_listed_wrong_hash() -> None:
    """T-19: Wrong hash returns False even if filename matches."""
    assert _is_allow_listed("m.py", "wronghash", {"m.py": {"sha256": "correcthash"}}) is False


def test_notes_present_on_success() -> None:
    """T-20: Success result has non-empty notes."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        _write_migration(versions, "m006", "    op.add_column('t', sa.Column('c', sa.String(), nullable=True))\n")
        result = migration_diff(ToolInput(project_dir=str(proj)))
        assert result.notes


def test_fail_on_unsafe_false_skips_check() -> None:
    """T-21: fail_on_unsafe_default=False does not block UNSAFE ops."""
    with tempfile.TemporaryDirectory() as tmp:
        proj, versions = _make_migration_dir(Path(tmp))
        _write_migration(versions, "m007", "    op.rename_column('t', 'old', 'new')\n")
        result = migration_diff(
            ToolInput(project_dir=str(proj)),
            fail_on_unsafe_default=False,
            fail_on_destructive=False,
        )
        assert result.status == "success"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_error_missing_project,
        test_error_no_versions_dir,
        test_dry_run_no_files,
        test_safe_migration_passes,
        test_destructive_migration_blocked,
        test_destructive_allowed_via_allow_list,
        test_extract_ops_add_column,
        test_extract_ops_drop_table,
        test_classify_safe,
        test_classify_unsafe_rename,
        test_classify_destructive_drop,
        test_classify_execute_destructive,
        test_classify_empty_is_safe,
        test_rollback_distance_last_migration,
        test_rollback_distance_first_of_two,
        test_detect_multi_phase_true,
        test_detect_multi_phase_false,
        test_sha256_deterministic,
        test_is_allow_listed_wrong_hash,
        test_notes_present_on_success,
        test_fail_on_unsafe_false_skips_check,
    ]

    passed = failed = 0
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
