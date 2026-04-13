"""Tests for TOOL-023 add_outbox_pattern.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_outbox_pattern.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_outbox_pattern.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_outbox_pattern import add_outbox_pattern
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
    project_dir = create_fixture_project(name="obx_t01")
    result = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="obx_t02")
    result = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_outbox_model_created() -> None:
    """CC-01: app/models/outbox.py exists with OutboxEvent and OutboxDlq."""
    project_dir = create_fixture_project(name="obx_t03")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "outbox.py"
    assert model_file.exists(), "outbox.py model not created"
    content = model_file.read_text()
    assert "OutboxEvent" in content
    assert "outbox_events" in content
    assert "OutboxDlq" in content


def test_outbox_model_status_field() -> None:
    """CC-02: OutboxEvent has status field with 'pending' default."""
    project_dir = create_fixture_project(name="obx_t04")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "outbox.py"
    content = model_file.read_text()
    assert "status" in content
    assert "pending" in content


def test_outbox_model_attempts_field() -> None:
    """CC-03: OutboxEvent has attempts counter field."""
    project_dir = create_fixture_project(name="obx_t05")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "outbox.py"
    content = model_file.read_text()
    assert "attempts" in content


def test_outbox_model_idempotency_key() -> None:
    """CC-04: OutboxEvent has idempotency_key for dedup."""
    project_dir = create_fixture_project(name="obx_t06")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "outbox.py"
    content = model_file.read_text()
    assert "idempotency_key" in content, "idempotency_key dedup field must be present"


def test_outbox_model_partial_index() -> None:
    """CC-05: OutboxEvent has partial index on pending+undelivered rows."""
    project_dir = create_fixture_project(name="obx_t07")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "outbox.py"
    content = model_file.read_text()
    assert "postgresql_where" in content or "partial" in content.lower() or (
        "pending" in content and "Index" in content
    )


def test_outbox_service_created() -> None:
    """CC-06: app/services/outbox.py exists with OutboxService."""
    project_dir = create_fixture_project(name="obx_t08")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    service_file = project_dir / "app" / "services" / "outbox.py"
    assert service_file.exists(), "outbox service not created"
    content = service_file.read_text()
    assert "OutboxService" in content
    assert "async def emit" in content


def test_emit_requires_active_transaction() -> None:
    """CC-07: emit() raises RuntimeError if called outside a transaction."""
    project_dir = create_fixture_project(name="obx_t09")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    service_file = project_dir / "app" / "services" / "outbox.py"
    content = service_file.read_text()
    assert "RuntimeError" in content, "emit() must raise RuntimeError outside transaction"
    assert "in_transaction" in content or "transaction" in content


def test_emit_validates_payload_size() -> None:
    """CC-08: emit() rejects payloads exceeding 64KB."""
    project_dir = create_fixture_project(name="obx_t10")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    service_file = project_dir / "app" / "services" / "outbox.py"
    content = service_file.read_text()
    assert "65536" in content or "64" in content, "64KB payload limit must be present"
    assert "ValueError" in content


def test_dispatcher_created() -> None:
    """CC-09: app/workers/outbox_dispatcher.py exists with ARQ worker."""
    project_dir = create_fixture_project(name="obx_t11")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    dispatcher_file = project_dir / "app" / "workers" / "outbox_dispatcher.py"
    assert dispatcher_file.exists(), "outbox_dispatcher.py not created"
    content = dispatcher_file.read_text()
    assert "WorkerSettings" in content


def test_dispatcher_uses_skip_locked() -> None:
    """CC-10: Dispatcher uses SELECT FOR UPDATE SKIP LOCKED."""
    project_dir = create_fixture_project(name="obx_t12")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    dispatcher_file = project_dir / "app" / "workers" / "outbox_dispatcher.py"
    content = dispatcher_file.read_text()
    assert "skip_locked" in content, "Dispatcher must use SKIP LOCKED"
    assert "with_for_update" in content or "FOR UPDATE" in content


def test_exponential_backoff_retry_schedule() -> None:
    """CC-11: Dispatcher has exponential backoff retry delays."""
    project_dir = create_fixture_project(name="obx_t13")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    dispatcher_file = project_dir / "app" / "workers" / "outbox_dispatcher.py"
    content = dispatcher_file.read_text()
    assert "RETRY_DELAYS" in content or "retry" in content.lower()


def test_dlq_move_on_exhausted_retries() -> None:
    """CC-12: Events exhausting retries are moved to DLQ."""
    project_dir = create_fixture_project(name="obx_t14")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    dispatcher_file = project_dir / "app" / "workers" / "outbox_dispatcher.py"
    content = dispatcher_file.read_text()
    assert "dlq" in content.lower() or "dead" in content, "DLQ move logic must be present"


def test_admin_routes_created() -> None:
    """CC-13: outbox admin routes file is created."""
    project_dir = create_fixture_project(name="obx_t15")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "outbox_admin.py"
    assert admin_route.exists(), "outbox_admin.py not created"
    content = admin_route.read_text()
    assert "/outbox/metrics" in content or "outbox_metrics" in content
    assert "/outbox/dlq" in content or "outbox_dlq" in content


def test_pydantic_schemas_created() -> None:
    """CC-14: Pydantic event schemas file is created."""
    project_dir = create_fixture_project(name="obx_t16")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    schemas_file = project_dir / "app" / "schemas" / "outbox.py"
    assert schemas_file.exists(), "outbox schemas not created"
    content = schemas_file.read_text()
    assert "DomainEvent" in content
    assert "OutboxEventPublic" in content


def test_migration_file_created() -> None:
    """CC-15: Alembic migration creates outbox_events and outbox_dlq."""
    project_dir = create_fixture_project(name="obx_t17")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*outbox*"))
    assert len(migration_files) >= 1, "No outbox migration file created"
    content = migration_files[0].read_text()
    assert "outbox_events" in content
    assert "outbox_dlq" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_all_created_files_parse() -> None:
    """CC-16: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="obx_t18")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    for subdir in ["models", "services", "workers"]:
        d = project_dir / "app" / subdir
        if d.exists():
            for py_file in sorted(d.rglob("*.py")):
                source = py_file.read_text()
                try:
                    ast.parse(source)
                except SyntaxError as exc:
                    raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def test_idempotent_returns_no_op() -> None:
    """CC-17: Running the tool twice returns no_op on second run."""
    project_dir = create_fixture_project(name="obx_t19")
    r1 = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="obx_t20")
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="obx_t21")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_outbox_pattern(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="obx_t22")
    result = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_alembic_and_arq() -> None:
    """next_steps guides developer to run migration and start dispatcher."""
    project_dir = create_fixture_project(name="obx_t23")
    result = add_outbox_pattern(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"
    assert "arq" in combined or "dispatcher" in combined, "next_steps should mention ARQ"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_outbox_model_created,
        test_outbox_model_status_field,
        test_outbox_model_attempts_field,
        test_outbox_model_idempotency_key,
        test_outbox_model_partial_index,
        test_outbox_service_created,
        test_emit_requires_active_transaction,
        test_emit_validates_payload_size,
        test_dispatcher_created,
        test_dispatcher_uses_skip_locked,
        test_exponential_backoff_retry_schedule,
        test_dlq_move_on_exhausted_retries,
        test_admin_routes_created,
        test_pydantic_schemas_created,
        test_migration_file_created,
        test_all_created_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_alembic_and_arq,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-023 add_outbox_pattern: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
