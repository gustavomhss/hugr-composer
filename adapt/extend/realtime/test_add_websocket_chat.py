"""Tests for TOOL-017 add_websocket_chat.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_websocket_chat.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_websocket_chat.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_websocket_chat import add_websocket_chat
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
    """Return the max LOC of any function in the given subdir."""
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
    project_dir = create_fixture_project(name="wsc_t01")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="wsc_t02")
    r1 = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="wsc_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 7 new files (models, schemas, crud, ws, routes, migration)."""
    project_dir = create_fixture_project(name="wsc_t04")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, (
        f"Expected >= 7 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="wsc_t05")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="wsc_t06")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="wsc_t07")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """Expected WEBSOCKET_CHAT_* settings fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="wsc_t08")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in (
        "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER",
        "WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH",
        "WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE",
    ):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in line:
            assert line.startswith("    "), (
                f"WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER not inside class body "
                f"(no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """ChatRoom and ChatMessage are registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="wsc_t09")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "ChatRoom" in content, "ChatRoom not registered in models __init__"
    assert "ChatMessage" in content, "ChatMessage not registered in models __init__"


def test_routes_registered() -> None:
    """Chat HTTP routes are registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="wsc_t10")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "chat" in content.lower(), "Chat router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_ws_chat_endpoint_file_created() -> None:
    """app/ws/chat.py exists with WebSocketManager references."""
    project_dir = create_fixture_project(name="wsc_t11")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    ws_file = project_dir / "app" / "ws" / "chat.py"
    assert ws_file.exists(), "app/ws/chat.py not created"
    content = ws_file.read_text()
    assert "WebSocketManager" in content


def test_connection_manager_created() -> None:
    """app/ws/connection_manager.py exists with WebSocketManager."""
    project_dir = create_fixture_project(name="wsc_t12")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    manager_file = project_dir / "app" / "ws" / "connection_manager.py"
    assert manager_file.exists(), "connection_manager.py not created"
    content = manager_file.read_text()
    assert "WebSocketManager" in content
    assert "publish" in content or "broadcast" in content


def test_chat_models_created() -> None:
    """app/models/chat.py exists with ChatRoom and ChatMessage classes."""
    project_dir = create_fixture_project(name="wsc_t13")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    assert model_file.exists(), "app/models/chat.py not created"
    content = model_file.read_text()
    assert "ChatRoom" in content, "ChatRoom model not found"
    assert "ChatMessage" in content, "ChatMessage model not found"


def test_chat_schemas_created() -> None:
    """app/schemas/chat.py exists with Pydantic schemas."""
    project_dir = create_fixture_project(name="wsc_t14")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "chat.py"
    assert schema_file.exists(), "app/schemas/chat.py not created"
    content = schema_file.read_text()
    assert "ChatMessageIn" in content or "ChatMessage" in content


def test_chat_crud_created() -> None:
    """app/crud/chat.py exists with CRUD helpers."""
    project_dir = create_fixture_project(name="wsc_t15")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "chat.py"
    assert crud_file.exists(), "app/crud/chat.py not created"
    content = crud_file.read_text()
    assert "async def" in content, "CRUD file must have async functions"


def test_http_companion_routes() -> None:
    """app/api/routes/chat.py exists with HTTP companion routes."""
    project_dir = create_fixture_project(name="wsc_t16")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "chat.py"
    assert route_file.exists(), "app/api/routes/chat.py not created"
    content = route_file.read_text()
    assert "room" in content.lower(), "Chat routes must reference rooms"


def test_tenant_conditional_fk_with_tenants() -> None:
    """When add_multi_tenancy is applied first, ChatRoom has tenant_id FK."""
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy

    project_dir = create_fixture_project(name="wsc_t17")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    content = model_file.read_text()
    assert "tenant" in content.lower(), "ChatRoom must have tenant_id when tenants exist"
    assert "ForeignKey" in content, "tenant_id must be a ForeignKey when tenants exist"


def test_tenant_conditional_fk_without_tenants() -> None:
    """Without multi_tenancy, no FK to tenants.id."""
    project_dir = create_fixture_project(name="wsc_t18")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "chat.py"
    content = model_file.read_text()
    # Should not have ForeignKey("tenants.id") — either no FK at all, or plain column
    assert 'ForeignKey("tenants.id"' not in content, (
        "tenant_id must NOT have ForeignKey to tenants.id when tenants table absent"
    )


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="wsc_t19")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should mention Redis and alembic."""
    project_dir = create_fixture_project(name="wsc_t20")
    result = add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined, "next_steps should mention Redis"
    assert "alembic" in combined, "next_steps should mention alembic"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="wsc_t21")
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    add_websocket_chat(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


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
        test_ws_chat_endpoint_file_created,
        test_connection_manager_created,
        test_chat_models_created,
        test_chat_schemas_created,
        test_chat_crud_created,
        test_http_companion_routes,
        test_tenant_conditional_fk_with_tenants,
        test_tenant_conditional_fk_without_tenants,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
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
    print(f"TOOL-017 add_websocket_chat: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
