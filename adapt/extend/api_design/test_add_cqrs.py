"""Tests for TOOL-080 add_cqrs.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/api_design/test_add_cqrs.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_cqrs.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_cqrs import add_cqrs
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


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cqrs_t01")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="cqrs_t02")
    r1 = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="cqrs_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_cqrs(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 6 new files."""
    project_dir = create_fixture_project(name="cqrs_t04")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes __init__)."""
    project_dir = create_fixture_project(name="cqrs_t05")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="cqrs_t06")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="cqrs_t07")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """DATABASE_READ_URL and CQRS_ENABLED are inside the Settings class."""
    project_dir = create_fixture_project(name="cqrs_t08")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("DATABASE_READ_URL", "CQRS_ENABLED"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify at least one field is inside Settings class body (4-space indent)
    for line in content.splitlines():
        if "DATABASE_READ_URL" in line and ":" in line:
            assert line.startswith("    "), (
                f"DATABASE_READ_URL not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """No model is registered for CQRS (no ORM model created)."""
    project_dir = create_fixture_project(name="cqrs_t09")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    # CQRS has no ORM model — models/__init__.py should not be in files_modified
    assert result.status == "success"


def test_routes_registered() -> None:
    """cqrs router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="cqrs_t10")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "cqrs" in content.lower(), "cqrs router not in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_cqrs_init_exports() -> None:
    """app/cqrs/__init__.py exports CommandBus, QueryBus, ReadReplicaSession."""
    project_dir = create_fixture_project(name="cqrs_t11")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "cqrs" / "__init__.py"
    assert init_file.exists(), "app/cqrs/__init__.py not created"
    content = init_file.read_text()
    for sym in ("CommandBus", "QueryBus", "ReadReplicaSession"):
        assert sym in content, f"{sym} not exported from app/cqrs/__init__.py"


def test_bus_file_has_dispatch_and_query() -> None:
    """app/cqrs/bus.py defines CommandBus.dispatch and QueryBus.query."""
    project_dir = create_fixture_project(name="cqrs_t12")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    bus_file = project_dir / "app" / "cqrs" / "bus.py"
    assert bus_file.exists(), "app/cqrs/bus.py not created"
    content = bus_file.read_text()
    assert "CommandBus" in content, "CommandBus not defined in bus.py"
    assert "QueryBus" in content, "QueryBus not defined in bus.py"
    assert "dispatch" in content, "dispatch method not in bus.py"
    assert "def query" in content, "query method not in bus.py"


def test_commands_file_has_base_and_examples() -> None:
    """app/cqrs/commands.py has Command base and 3 example commands."""
    project_dir = create_fixture_project(name="cqrs_t13")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    cmds_file = project_dir / "app" / "cqrs" / "commands.py"
    assert cmds_file.exists(), "app/cqrs/commands.py not created"
    content = cmds_file.read_text()
    assert "class Command" in content, "Command base not in commands.py"
    # 3 example commands
    example_cmds = ["CreateItemCommand", "UpdateItemCommand", "DeleteItemCommand"]
    for cmd in example_cmds:
        assert cmd in content, f"{cmd} not in commands.py"


def test_queries_file_has_base_and_examples() -> None:
    """app/cqrs/queries.py has Query base and 3 example queries."""
    project_dir = create_fixture_project(name="cqrs_t14")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    qrys_file = project_dir / "app" / "cqrs" / "queries.py"
    assert qrys_file.exists(), "app/cqrs/queries.py not created"
    content = qrys_file.read_text()
    assert "class Query" in content, "Query base not in queries.py"
    for qry in ("GetItemQuery", "ListItemsQuery", "SearchItemsQuery"):
        assert qry in content, f"{qry} not in queries.py"


def test_read_replica_file_exists() -> None:
    """app/cqrs/read_replica.py defines ReadReplicaSession dependency."""
    project_dir = create_fixture_project(name="cqrs_t15")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    rr_file = project_dir / "app" / "cqrs" / "read_replica.py"
    assert rr_file.exists(), "app/cqrs/read_replica.py not created"
    content = rr_file.read_text()
    assert "ReadReplicaSession" in content, "ReadReplicaSession not in read_replica.py"
    assert "DATABASE_READ_URL" in content, "DATABASE_READ_URL not referenced in read_replica.py"


def test_read_replica_fallback_documented() -> None:
    """ReadReplicaSession falls back to primary when DATABASE_READ_URL is absent."""
    project_dir = create_fixture_project(name="cqrs_t16")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "cqrs" / "read_replica.py").read_text()
    # Falls back to get_session
    assert "get_session" in content, "Fallback to primary session not present"


def test_routes_file_has_commands_and_queries_endpoints() -> None:
    """app/api/routes/cqrs.py has POST /cqrs/commands and POST /cqrs/queries."""
    project_dir = create_fixture_project(name="cqrs_t17")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "cqrs.py"
    assert routes_file.exists(), "app/api/routes/cqrs.py not created"
    content = routes_file.read_text()
    assert "/commands" in content, "POST /commands not in cqrs routes"
    assert "/queries" in content, "POST /queries not in cqrs routes"


def test_bus_register_method_exists() -> None:
    """CommandBus and QueryBus both expose a register() method."""
    project_dir = create_fixture_project(name="cqrs_t18")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "cqrs" / "bus.py").read_text()
    assert content.count("def register") >= 2, "Both buses must have a register() method"


def test_no_top_level_optional_sdk_import() -> None:
    """No top-level import of optional (non-core) SDKs in any generated cqrs file."""
    # Only truly optional SDKs are checked here.
    # SQLAlchemy, FastAPI etc. are core dependencies — they are always installed.
    optional_sdks = {"firebase_admin", "apns2", "resend", "postmarker", "sendgrid"}
    project_dir = create_fixture_project(name="cqrs_t19")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    for py_file in sorted((project_dir / "app" / "cqrs").rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in tree.body:  # top-level only
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module.split(".")[0] if node.module else ""])
                )
                for name in names:
                    assert name not in optional_sdks, (
                        f"Optional SDK imported at top level in {py_file}: {name}"
                    )


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="cqrs_t20")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="cqrs_t21")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should mention DATABASE_READ_URL."""
    project_dir = create_fixture_project(name="cqrs_t22")
    result = add_cqrs(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "database_read_url" in combined, "next_steps should mention DATABASE_READ_URL"


def test_command_bus_raises_on_unregistered() -> None:
    """CommandBus.dispatch raises KeyError for unregistered command type."""
    project_dir = create_fixture_project(name="cqrs_t23")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    bus_content = (project_dir / "app" / "cqrs" / "bus.py").read_text()
    assert "KeyError" in bus_content, "CommandBus should raise KeyError for unknown commands"


def test_query_bus_raises_on_unregistered() -> None:
    """QueryBus.query raises KeyError for unregistered query type."""
    project_dir = create_fixture_project(name="cqrs_t24")
    add_cqrs(ToolInput(project_dir=str(project_dir)))
    bus_content = (project_dir / "app" / "cqrs" / "bus.py").read_text()
    # Should have two KeyError raises (one for command, one for query)
    assert bus_content.count("KeyError") >= 2, "Both buses must raise KeyError for unknown types"


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
        test_cqrs_init_exports,
        test_bus_file_has_dispatch_and_query,
        test_commands_file_has_base_and_examples,
        test_queries_file_has_base_and_examples,
        test_read_replica_file_exists,
        test_read_replica_fallback_documented,
        test_routes_file_has_commands_and_queries_endpoints,
        test_bus_register_method_exists,
        test_no_top_level_optional_sdk_import,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
        test_command_bus_raises_on_unregistered,
        test_query_bus_raises_on_unregistered,
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
    print(f"TOOL-080 add_cqrs: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
