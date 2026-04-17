"""Tests for TOOL-063 add_notifications.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_notifications.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_notifications.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_notifications import add_notifications
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
    project_dir = create_fixture_project(name="notif_t01")
    result = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="notif_t02")
    r1 = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="notif_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_notifications(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 8 new files (notifications pkg, model, schemas, crud, routes, migration)."""
    project_dir = create_fixture_project(name="notif_t04")
    result = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 8, (
        f"Expected >= 8 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, models init)."""
    project_dir = create_fixture_project(name="notif_t05")
    result = add_notifications(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="notif_t06")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="notif_t07")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """NOTIFICATION_CHANNELS and NOTIFICATION_MAX_PER_PAGE are inside Settings."""
    project_dir = create_fixture_project(name="notif_t08")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("NOTIFICATION_CHANNELS", "NOTIFICATION_MAX_PER_PAGE"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "NOTIFICATION_CHANNELS" in line and ":" in line:
            assert line.startswith("    "), (
                f"NOTIFICATION_CHANNELS not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """Notification model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="notif_t09")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "Notification" in content, "Notification not registered in models __init__"


def test_routes_registered() -> None:
    """Notifications router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="notif_t10")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "notification" in content.lower(), "Notifications router not in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_notification_model_exists() -> None:
    """app/models/notification.py exists with Notification class."""
    project_dir = create_fixture_project(name="notif_t11")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "notification.py"
    assert model_file.exists(), "app/models/notification.py not created"
    content = model_file.read_text()
    assert "Notification" in content, "Notification class not found"


def test_notification_model_fields() -> None:
    """Notification model has all required fields: id, user_id, title, body, channel, read_at."""
    project_dir = create_fixture_project(name="notif_t12")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "notification.py").read_text()
    for field in ("user_id", "title", "body", "channel", "read_at", "created_at"):
        assert field in content, f"Field {field!r} not in Notification model"


def test_notification_schemas_exist() -> None:
    """app/schemas/notification.py has NotificationCreate, NotificationRead, NotificationList."""
    project_dir = create_fixture_project(name="notif_t13")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "notification.py"
    assert schema_file.exists(), "app/schemas/notification.py not created"
    content = schema_file.read_text()
    for cls in ("NotificationCreate", "NotificationRead", "NotificationList", "UnreadCount"):
        assert cls in content, f"{cls} not in notification schemas"


def test_crud_file_exists() -> None:
    """app/crud/notification.py has all required CRUD functions."""
    project_dir = create_fixture_project(name="notif_t14")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "notification.py"
    assert crud_file.exists(), "app/crud/notification.py not created"
    content = crud_file.read_text()
    for fn in ("create_notification", "list_unread", "mark_read", "mark_all_read", "count_unread"):
        assert fn in content, f"CRUD function {fn!r} not found"


def test_routes_file_exists() -> None:
    """app/api/routes/notifications.py has all 4 endpoints."""
    project_dir = create_fixture_project(name="notif_t15")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "notifications.py"
    assert routes_file.exists(), "app/api/routes/notifications.py not created"
    content = routes_file.read_text()
    assert "unread-count" in content or "unread_count" in content, "unread-count endpoint missing"
    assert "read-all" in content or "mark_all_read" in content, "read-all endpoint missing"
    assert "/read" in content or "mark_notification_read" in content, "mark-read endpoint missing"


def test_notification_service_exists() -> None:
    """app/notifications/service.py has NotificationService with all methods."""
    project_dir = create_fixture_project(name="notif_t16")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    service_file = project_dir / "app" / "notifications" / "service.py"
    assert service_file.exists(), "app/notifications/service.py not created"
    content = service_file.read_text()
    for method in ("send", "list_unread", "mark_read", "mark_all_read", "count_unread"):
        assert method in content, f"NotificationService.{method} not found"


def test_channels_file_exists() -> None:
    """app/notifications/channels.py has dispatch function with in_app, push, email handling."""
    project_dir = create_fixture_project(name="notif_t17")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    channels_file = project_dir / "app" / "notifications" / "channels.py"
    assert channels_file.exists(), "app/notifications/channels.py not created"
    content = channels_file.read_text()
    assert "dispatch" in content, "dispatch function missing from channels.py"
    assert "in_app" in content, "in_app channel not handled"
    assert "push" in content, "push channel not handled"


def test_push_channel_lazy_import() -> None:
    """FCM push channel uses lazy import of firebase_admin."""
    project_dir = create_fixture_project(name="notif_t18")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "notifications" / "channels.py").read_text()
    assert "firebase_admin" in content, "firebase_admin not referenced in channels.py"
    assert "ImportError" in content, "No ImportError handler for lazy firebase_admin import"


def test_migration_file_exists() -> None:
    """An Alembic migration for notifications is created."""
    project_dir = create_fixture_project(name="notif_t19")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*notification*.py"))
    assert migration_files, "No notification migration file found in alembic/versions/"
    content = migration_files[0].read_text()
    assert "notifications" in content, "notifications table not in migration"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="notif_t20")
    result = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="notif_t21")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    add_notifications(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should mention alembic."""
    project_dir = create_fixture_project(name="notif_t22")
    result = add_notifications(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"


def test_notifications_init_exports() -> None:
    """app/notifications/__init__.py exports NotificationService and dispatch."""
    project_dir = create_fixture_project(name="notif_t23")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "notifications" / "__init__.py"
    assert init_file.exists(), "app/notifications/__init__.py not created"
    content = init_file.read_text()
    assert "NotificationService" in content, "NotificationService not exported"
    assert "dispatch" in content, "dispatch not exported"


def test_unread_count_is_count_query() -> None:
    """count_unread in crud uses a COUNT query, not a full SELECT."""
    project_dir = create_fixture_project(name="notif_t24")
    add_notifications(ToolInput(project_dir=str(project_dir)))
    crud_content = (project_dir / "app" / "crud" / "notification.py").read_text()
    assert "func.count" in crud_content or "COUNT" in crud_content.upper(), (
        "count_unread should use a COUNT query"
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
        test_notification_model_exists,
        test_notification_model_fields,
        test_notification_schemas_exist,
        test_crud_file_exists,
        test_routes_file_exists,
        test_notification_service_exists,
        test_channels_file_exists,
        test_push_channel_lazy_import,
        test_migration_file_exists,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
        test_notifications_init_exports,
        test_unread_count_is_count_query,
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
    print(f"TOOL-063 add_notifications: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
