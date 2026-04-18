"""Tests for TOOL-079 add_event_sourcing.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_event_sourcing.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_event_sourcing.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_event_sourcing import add_event_sourcing
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="es_t01_success")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files created or modified."""
    project_dir = create_fixture_project(name="es_t02_idempotent")
    r1 = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing to disk."""
    project_dir = create_fixture_project(name="es_t03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 8 files created and all exist on disk."""
    project_dir = create_fixture_project(name="es_t04_created_count")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 8, f"Expected >=8 files, got {len(result.files_created)}"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = create_fixture_project(name="es_t05_modified_count")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, "Expected at least 1 modified file"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="es_t06_parse_all")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="es_t07_func_loc")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    violations: list[str] = []
    for py_file in _all_py_files(project_dir):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions exceeding 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: EVENT_STORE_SNAPSHOT_INTERVAL appears in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="es_t08_config")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "EVENT_STORE_SNAPSHOT_INTERVAL" in content, \
        "EVENT_STORE_SNAPSHOT_INTERVAL not in config"
    for line in content.splitlines():
        if "EVENT_STORE_SNAPSHOT_INTERVAL" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: Event model in models/__init__.py
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: Event is imported in app/models/__init__.py."""
    project_dir = create_fixture_project(name="es_t09_models_init")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert "Event" in models_init.read_text(), "Event not registered in models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: events_router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="es_t10_routes_init")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "events_router" in content or "events" in content, \
            "events router not registered in routes/__init__.py"


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_event_orm_model_created() -> None:
    """Domain: app/models/event.py exists with Event class and required columns."""
    project_dir = create_fixture_project(name="es_t11_orm_model")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "event.py"
    assert model_file.exists(), "models/event.py not created"
    content = model_file.read_text()
    assert "class Event" in content, "Event ORM class missing"
    assert "stream_id" in content, "stream_id column missing"
    assert "event_type" in content, "event_type column missing"
    assert "data_json" in content, "data_json column missing"
    assert "version" in content, "version column missing"
    assert "created_at" in content, "created_at column missing"


def test_event_store_created() -> None:
    """Domain: app/events/store.py exists with EventStore class."""
    project_dir = create_fixture_project(name="es_t12_store")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "events" / "store.py"
    assert store_file.exists(), "events/store.py not created"
    content = store_file.read_text()
    assert "class EventStore" in content, "EventStore class missing"
    assert "async def append" in content, "append method missing"
    assert "async def get_stream" in content, "get_stream method missing"
    assert "async def get_all_since" in content, "get_all_since method missing"


def test_projector_created() -> None:
    """Domain: app/events/projector.py exists with Projector class."""
    project_dir = create_fixture_project(name="es_t13_projector")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    proj_file = project_dir / "app" / "events" / "projector.py"
    assert proj_file.exists(), "events/projector.py not created"
    content = proj_file.read_text()
    assert "class Projector" in content, "Projector class missing"
    assert "def project" in content, "project method missing"
    assert "async def rebuild" in content, "rebuild method missing"
    assert "def handle_event" in content, "handle_event method missing"


def test_append_event_route_exists() -> None:
    """Domain: POST /events/streams/{stream_id}/append endpoint exists."""
    project_dir = create_fixture_project(name="es_t14_append_route")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "events.py"
    assert routes_file.exists(), "events.py routes file not created"
    content = routes_file.read_text()
    assert "append" in content, "append endpoint missing"
    assert "stream_id" in content, "stream_id path param missing"


def test_read_stream_route_exists() -> None:
    """Domain: GET /events/streams/{stream_id} endpoint exists."""
    project_dir = create_fixture_project(name="es_t15_stream_route")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "events.py"
    content = routes_file.read_text()
    assert "get_stream" in content or "read_stream" in content, "stream read endpoint missing"


def test_rebuild_projection_route_exists() -> None:
    """Domain: POST /events/projections/{name}/rebuild endpoint exists."""
    project_dir = create_fixture_project(name="es_t16_rebuild_route")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "events.py"
    content = routes_file.read_text()
    assert "rebuild" in content, "rebuild projection endpoint missing"
    assert "projection_name" in content or "projections" in content, \
        "projection_name param missing"


def test_event_orm_has_unique_stream_version_index() -> None:
    """Domain: Event model has unique (stream_id, version) index."""
    project_dir = create_fixture_project(name="es_t17_unique_idx")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "event.py"
    content = model_file.read_text()
    assert "__table_args__" in content, "__table_args__ not in Event model"
    assert "unique=True" in content, "unique constraint not found in Event model"


def test_migration_created() -> None:
    """Domain: Alembic migration for events table is created."""
    project_dir = create_fixture_project(name="es_t18_migration")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*event_store*"))
    assert len(migration_files) >= 1, "No event_store migration created"


def test_migration_has_upgrade_downgrade() -> None:
    """Domain: Migration has both upgrade() and downgrade()."""
    project_dir = create_fixture_project(name="es_t19_mig_updown")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*event_store*"))
    assert migration_files
    content = migration_files[0].read_text()
    assert "def upgrade" in content, "upgrade() missing"
    assert "def downgrade" in content, "downgrade() missing"
    assert "events" in content, "events table not referenced in migration"


def test_optimistic_concurrency_in_store() -> None:
    """Domain: EventStore.append uses optimistic concurrency (version conflict check)."""
    project_dir = create_fixture_project(name="es_t20_opt_concurrency")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    store_file = project_dir / "app" / "events" / "store.py"
    content = store_file.read_text()
    assert "expected_version" in content, "expected_version param missing from append"
    assert "ValueError" in content, "concurrency conflict ValueError not raised"


def test_events_package_init_exports() -> None:
    """Domain: app/events/__init__.py exports EventStore and Projector."""
    project_dir = create_fixture_project(name="es_t21_pkg_init")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "events" / "__init__.py"
    assert init_file.exists(), "app/events/__init__.py not created"
    content = init_file.read_text()
    assert "EventStore" in content, "EventStore not exported from events package"
    assert "Projector" in content, "Projector not exported from events package"


def test_domain_event_dataclass_created() -> None:
    """Domain: app/events/models.py exists with DomainEvent dataclass."""
    project_dir = create_fixture_project(name="es_t22_domain_event")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    models_file = project_dir / "app" / "events" / "models.py"
    assert models_file.exists(), "events/models.py not created"
    content = models_file.read_text()
    assert "DomainEvent" in content, "DomainEvent dataclass missing"
    assert "stream_id" in content, "stream_id field missing from DomainEvent"
    assert "event_type" in content, "event_type field missing from DomainEvent"


# ---------------------------------------------------------------------------
# CC-N-1: execution time
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    project_dir = create_fixture_project(name="es_t23_timing")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must not be empty on success and mention alembic."""
    project_dir = create_fixture_project(name="es_t24_next_steps")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="es_t25_idem_parse")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional structural tests
# ---------------------------------------------------------------------------

def test_error_return_on_invalid_dir() -> None:
    """Tool returns error status when project_dir does not exist."""
    result = add_event_sourcing(ToolInput(project_dir="/nonexistent/path/xyz"))
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms > 0


def test_dry_run_execution_time_recorded() -> None:
    """execution_time_ms is positive even on dry_run returns."""
    project_dir = create_fixture_project(name="es_t27_dry_timing")
    result = add_event_sourcing(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.execution_time_ms > 0, "execution_time_ms must be positive on dry_run"


def test_snapshot_interval_in_projector() -> None:
    """Domain: Projector uses snapshot_interval configuration."""
    project_dir = create_fixture_project(name="es_t28_snapshot")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    proj_file = project_dir / "app" / "events" / "projector.py"
    content = proj_file.read_text()
    assert "snapshot_interval" in content, "snapshot_interval not in Projector"
    assert "save_snapshot" in content, "save_snapshot method missing from Projector"


def test_event_schema_has_event_read() -> None:
    """Domain: app/schemas/event.py has EventRead with from_attributes=True."""
    project_dir = create_fixture_project(name="es_t29_schema")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "event.py"
    assert schema_file.exists(), "schemas/event.py not created"
    content = schema_file.read_text()
    assert "EventRead" in content, "EventRead schema missing"
    assert "from_attributes=True" in content, "ConfigDict(from_attributes=True) missing"


def test_crud_event_file_created() -> None:
    """Domain: app/crud/event.py exists with event query helpers."""
    project_dir = create_fixture_project(name="es_t30_crud")
    add_event_sourcing(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "event.py"
    assert crud_file.exists(), "crud/event.py not created"
    content = crud_file.read_text()
    assert "async def get_event_by_id" in content, "get_event_by_id missing"
    assert "async def count_stream_events" in content, "count_stream_events missing"


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.crud_data.add_event_sourcing import MCP_TOOL, add_event_sourcing as fn
    assert MCP_TOOL["entry"] == fn.__name__, (
        f"MCP_TOOL entry={MCP_TOOL['entry']!r} != function name={fn.__name__!r}"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_models_init_patched,
        test_routes_registered,
        test_event_orm_model_created,
        test_event_store_created,
        test_projector_created,
        test_append_event_route_exists,
        test_read_stream_route_exists,
        test_rebuild_projection_route_exists,
        test_event_orm_has_unique_stream_version_index,
        test_migration_created,
        test_migration_has_upgrade_downgrade,
        test_optimistic_concurrency_in_store,
        test_events_package_init_exports,
        test_domain_event_dataclass_created,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_error_return_on_invalid_dir,
        test_dry_run_execution_time_recorded,
        test_snapshot_interval_in_projector,
        test_event_schema_has_event_read,
        test_crud_event_file_created,
        test_mcp_tool_entry_matches_function,
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
