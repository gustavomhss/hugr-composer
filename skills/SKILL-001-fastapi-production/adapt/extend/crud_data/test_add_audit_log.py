"""Tests for TOOL-005 add_audit_log.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_audit_log.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_audit_log.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_audit_log import add_audit_log
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="audit_t01_success")
    result = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="audit_t02_files_exist")
    result = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="audit_t03_modified_exist")
    result = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_audit_model_created() -> None:
    """CC: app/models/audit_log.py exists and contains AuditLog class."""
    project_dir = create_fixture_project(name="audit_t04_model")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "audit_log.py"
    assert model_file.exists(), "audit_log.py not created"
    content = model_file.read_text()
    assert "class AuditLog" in content, "AuditLog class missing"
    assert "entity_type" in content, "entity_type column missing"
    assert "entity_id" in content, "entity_id column missing"
    assert "action" in content, "action column missing"
    assert "user_id" in content, "user_id column missing"


def test_audit_model_jsonb_columns() -> None:
    """AuditLog has before_values and after_values as JSONB columns."""
    project_dir = create_fixture_project(name="audit_t05_jsonb")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "audit_log.py"
    content = model_file.read_text()
    assert "before_values" in content and "JSONB" in content, "before_values JSONB missing"
    assert "after_values" in content, "after_values column missing"


def test_audit_model_hash_chain_columns() -> None:
    """AuditLog has entry_hash and prev_hash columns for hash chain."""
    project_dir = create_fixture_project(name="audit_t06_hash_cols")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "audit_log.py"
    content = model_file.read_text()
    assert "entry_hash" in content, "entry_hash column missing"
    assert "prev_hash" in content, "prev_hash column missing"


def test_audit_model_has_check_constraint() -> None:
    """AuditLog has a CheckConstraint on the action column."""
    project_dir = create_fixture_project(name="audit_t07_check")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "audit_log.py"
    content = model_file.read_text()
    assert "CheckConstraint" in content, "CheckConstraint missing from AuditLog"
    assert "create" in content and "delete" in content, "action values missing from constraint"


def test_audit_context_created() -> None:
    """app/core/audit_context.py exists with set_audit_context and get_audit_context."""
    project_dir = create_fixture_project(name="audit_t08_context")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    ctx_file = project_dir / "app" / "core" / "audit_context.py"
    assert ctx_file.exists(), "audit_context.py not created"
    content = ctx_file.read_text()
    assert "set_audit_context" in content, "set_audit_context missing"
    assert "get_audit_context" in content, "get_audit_context missing"
    assert "contextvars" in content, "Must use contextvars for request-scoped state"


def test_audit_listeners_created() -> None:
    """app/core/audit_listeners.py exists with before_flush event listener."""
    project_dir = create_fixture_project(name="audit_t09_listeners")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    listeners_file = project_dir / "app" / "core" / "audit_listeners.py"
    assert listeners_file.exists(), "audit_listeners.py not created"
    content = listeners_file.read_text()
    assert "before_flush" in content, "before_flush listener missing"
    assert "_emit_audit" in content, "_emit_audit function missing"


def test_listeners_handles_create_update_delete() -> None:
    """Event listener handles session.new, session.dirty, session.deleted."""
    project_dir = create_fixture_project(name="audit_t10_cud")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    listeners_file = project_dir / "app" / "core" / "audit_listeners.py"
    content = listeners_file.read_text()
    assert "session.new" in content, "Listener must handle session.new (create)"
    assert "session.dirty" in content, "Listener must handle session.dirty (update)"
    assert "session.deleted" in content, "Listener must handle session.deleted (delete)"


def test_listeners_hash_chain() -> None:
    """Event listener computes SHA-256 hash chain on each entry."""
    project_dir = create_fixture_project(name="audit_t11_hash_chain")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    listeners_file = project_dir / "app" / "core" / "audit_listeners.py"
    content = listeners_file.read_text()
    assert "sha256" in content, "Hash chain must use SHA-256"
    assert "_compute_entry_hash" in content, "_compute_entry_hash function missing"
    assert "prev_hash" in content, "prev_hash must be set in hash chain"


def test_listeners_classifies_soft_delete_restore() -> None:
    """Listener detects soft_delete and restore actions from is_deleted transitions."""
    project_dir = create_fixture_project(name="audit_t12_soft_del")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    listeners_file = project_dir / "app" / "core" / "audit_listeners.py"
    content = listeners_file.read_text()
    assert "soft_delete" in content, "Must classify soft_delete action"
    assert "restore" in content, "Must classify restore action"
    assert "_classify_action" in content, "_classify_action function missing"


def test_verifier_created() -> None:
    """app/core/audit_verifier.py exists with verify_hash_chain."""
    project_dir = create_fixture_project(name="audit_t13_verifier")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    verifier_file = project_dir / "app" / "core" / "audit_verifier.py"
    assert verifier_file.exists(), "audit_verifier.py not created"
    content = verifier_file.read_text()
    assert "async def verify_hash_chain" in content, "verify_hash_chain missing"
    assert "VerificationResult" in content, "VerificationResult dataclass missing"
    assert "is_intact" in content, "is_intact field missing from VerificationResult"


def test_schemas_created() -> None:
    """app/schemas/audit_log.py exists with AuditLogFilter and AuditLogPage."""
    project_dir = create_fixture_project(name="audit_t14_schemas")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "audit_log.py"
    assert schema_file.exists(), "audit_log schemas not created"
    content = schema_file.read_text()
    assert "AuditLogFilter" in content, "AuditLogFilter schema missing"
    assert "AuditLogPage" in content, "AuditLogPage schema missing"
    assert "VerifyRequest" in content, "VerifyRequest schema missing"


def test_crud_created() -> None:
    """app/crud/audit_log.py exists with query_audit_logs function."""
    project_dir = create_fixture_project(name="audit_t15_crud")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "audit_log.py"
    assert crud_file.exists(), "audit_log crud not created"
    content = crud_file.read_text()
    assert "async def query_audit_logs" in content, "query_audit_logs missing"


def test_routes_created() -> None:
    """app/api/routes/audit_logs.py exists with GET / and POST /verify endpoints."""
    project_dir = create_fixture_project(name="audit_t16_routes")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "audit_logs.py"
    assert route_file.exists(), "audit_logs routes not created"
    content = route_file.read_text()
    assert "async def list_audit_logs" in content, "list_audit_logs endpoint missing"
    assert "async def verify_audit_chain" in content, "verify_audit_chain endpoint missing"
    assert '"/verify"' in content, "Verify endpoint path must be /verify"


def test_routes_use_auditor_dep() -> None:
    """Audit log routes are gated behind CurrentAuditor dependency."""
    project_dir = create_fixture_project(name="audit_t17_auditor_dep")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "audit_logs.py"
    content = route_file.read_text()
    assert "CurrentAuditor" in content, "Routes must require CurrentAuditor"


def test_deps_patched_with_current_auditor() -> None:
    """app/api/deps.py gets CurrentAuditor type alias."""
    project_dir = create_fixture_project(name="audit_t18_deps")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    deps_file = project_dir / "app" / "api" / "deps.py"
    assert deps_file.exists()
    content = deps_file.read_text()
    assert "CurrentAuditor" in content, "CurrentAuditor dep missing from deps.py"


def test_main_imports_listeners() -> None:
    """main.py imports audit_listeners (side-effect import to activate listener)."""
    project_dir = create_fixture_project(name="audit_t19_main_import")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    assert main_file.exists()
    assert "audit_listeners" in main_file.read_text(), "main.py must import audit_listeners"


def test_migration_created() -> None:
    """Alembic migration created with audit_logs table."""
    project_dir = create_fixture_project(name="audit_t20_migration")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*audit_log*"))
    assert len(migration_files) >= 1, "No audit_log migration file created"
    content = migration_files[0].read_text()
    assert "audit_logs" in content, "Migration must create audit_logs table"


def test_migration_has_partitioning() -> None:
    """Migration creates monthly partitioned table."""
    project_dir = create_fixture_project(name="audit_t21_partition")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*audit_log*"))
    assert migration_files, "No audit_log migration file created"
    content = migration_files[0].read_text()
    assert "PARTITION" in content.upper(), "Migration must set up partitioning"


def test_migration_has_immutability_trigger() -> None:
    """Migration creates immutability trigger to prevent UPDATE/DELETE."""
    project_dir = create_fixture_project(name="audit_t22_trigger")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*audit_log*"))
    assert migration_files, "No audit_log migration file created"
    content = migration_files[0].read_text()
    assert "trg_audit_log_immutable" in content or "IMMUTABLE" in content.upper(), \
        "Migration must create immutability trigger"


def test_migration_has_downgrade() -> None:
    """Migration has valid downgrade() that drops the table."""
    project_dir = create_fixture_project(name="audit_t23_downgrade")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*audit_log*"))
    assert migration_files, "No audit_log migration file created"
    content = migration_files[0].read_text()
    assert "def downgrade" in content, "Migration must have downgrade()"
    assert "drop_table" in content or "DROP TABLE" in content.upper(), \
        "downgrade() must drop the audit_logs table"


def test_all_py_files_parse() -> None:
    """All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="audit_t24_parse_all")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="audit_t25_idempotent")
    r1 = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="audit_t26_idempotent_parse")
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    add_audit_log(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="audit_t27_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_audit_log(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="audit_t28_timing")
    result = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="audit_t29_next_steps")
    result = add_audit_log(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_audit_model_created,
        test_audit_model_jsonb_columns,
        test_audit_model_hash_chain_columns,
        test_audit_model_has_check_constraint,
        test_audit_context_created,
        test_audit_listeners_created,
        test_listeners_handles_create_update_delete,
        test_listeners_hash_chain,
        test_listeners_classifies_soft_delete_restore,
        test_verifier_created,
        test_schemas_created,
        test_crud_created,
        test_routes_created,
        test_routes_use_auditor_dep,
        test_deps_patched_with_current_auditor,
        test_main_imports_listeners,
        test_migration_created,
        test_migration_has_partitioning,
        test_migration_has_immutability_trigger,
        test_migration_has_downgrade,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
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
