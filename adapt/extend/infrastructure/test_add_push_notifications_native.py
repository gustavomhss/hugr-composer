"""Tests for TOOL-082 add_push_notifications_native.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_push_notifications_native.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_push_notifications_native.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_push_notifications_native import add_push_notifications_native
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
    project_dir = create_fixture_project(name="push_t01")
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="push_t02")
    r1 = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="push_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 8 new files."""
    project_dir = create_fixture_project(name="push_t04")
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 8, (
        f"Expected >= 8 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 3 files (config, models __init__, routes __init__)."""
    project_dir = create_fixture_project(name="push_t05")
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 3, (
        f"Expected >= 3 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="push_t06")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="push_t07")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """FCM_CREDENTIALS_PATH + APNS_* fields are inside Settings."""
    project_dir = create_fixture_project(name="push_t08")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("FCM_CREDENTIALS_PATH", "APNS_KEY_PATH", "APNS_KEY_ID", "APNS_TEAM_ID"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent
    for line in content.splitlines():
        if "FCM_CREDENTIALS_PATH" in line and ":" in line:
            assert line.startswith("    "), (
                f"FCM_CREDENTIALS_PATH not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """DeviceToken model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="push_t09")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "DeviceToken" in content, "DeviceToken not registered in models __init__"


def test_routes_registered() -> None:
    """push router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="push_t10")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "push" in content.lower(), "push router not in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_push_init_exports_push_service() -> None:
    """app/push/__init__.py exports PushService."""
    project_dir = create_fixture_project(name="push_t11")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "push" / "__init__.py"
    assert init_file.exists(), "app/push/__init__.py not created"
    content = init_file.read_text()
    assert "PushService" in content, "PushService not exported from app/push/__init__.py"


def test_push_service_has_send_to_device_and_topic() -> None:
    """PushService has send_to_device and send_to_topic methods."""
    project_dir = create_fixture_project(name="push_t12")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    service_file = project_dir / "app" / "push" / "service.py"
    assert service_file.exists(), "app/push/service.py not created"
    content = service_file.read_text()
    assert "send_to_device" in content, "send_to_device not in PushService"
    assert "send_to_topic" in content, "send_to_topic not in PushService"


def test_fcm_provider_lazy_import() -> None:
    """FCMProvider uses lazy import for firebase_admin."""
    project_dir = create_fixture_project(name="push_t13")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    fcm_file = project_dir / "app" / "push" / "providers" / "fcm.py"
    assert fcm_file.exists(), "app/push/providers/fcm.py not created"
    # firebase_admin must NOT be at module level
    tree = ast.parse(fcm_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "firebase_admin" not in alias.name, (
                        "firebase_admin imported at module level in fcm.py"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "firebase_admin" not in (node.module or ""), (
                    "firebase_admin imported at module level in fcm.py"
                )


def test_apns_provider_lazy_import() -> None:
    """APNsProvider uses lazy import for apns2."""
    project_dir = create_fixture_project(name="push_t14")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    apns_file = project_dir / "app" / "push" / "providers" / "apns.py"
    assert apns_file.exists(), "app/push/providers/apns.py not created"
    tree = ast.parse(apns_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "apns2" not in alias.name, (
                        "apns2 imported at module level in apns.py"
                    )
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "apns2" not in (node.module or ""), (
                    "apns2 imported at module level in apns.py"
                )


def test_device_token_model_fields() -> None:
    """DeviceToken model has user_id, platform, token, created_at fields."""
    project_dir = create_fixture_project(name="push_t15")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "device_token.py"
    assert model_file.exists(), "app/models/device_token.py not created"
    content = model_file.read_text()
    for field in ("user_id", "platform", "token", "created_at"):
        assert field in content, f"Field {field!r} not in DeviceToken model"


def test_push_schemas_exist() -> None:
    """app/schemas/push.py has DeviceTokenCreate, DeviceTokenRead, PushSendRequest."""
    project_dir = create_fixture_project(name="push_t16")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "push.py"
    assert schema_file.exists(), "app/schemas/push.py not created"
    content = schema_file.read_text()
    for cls in ("DeviceTokenCreate", "DeviceTokenRead", "PushSendRequest", "PushSendResult"):
        assert cls in content, f"{cls} not in push schemas"


def test_crud_file_exists() -> None:
    """app/crud/device_token.py has all required CRUD functions."""
    project_dir = create_fixture_project(name="push_t17")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "device_token.py"
    assert crud_file.exists(), "app/crud/device_token.py not created"
    content = crud_file.read_text()
    for fn in ("create_device_token", "get_device_token", "list_tokens_for_user", "delete_device_token"):
        assert fn in content, f"CRUD function {fn!r} not found"


def test_routes_file_has_all_endpoints() -> None:
    """app/api/routes/push.py has register-device, send, and delete endpoints."""
    project_dir = create_fixture_project(name="push_t18")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "push.py"
    assert routes_file.exists(), "app/api/routes/push.py not created"
    content = routes_file.read_text()
    assert "register-device" in content or "register_device" in content, (
        "register-device endpoint missing"
    )
    assert "/send" in content or "send_push" in content, "/send endpoint missing"
    assert "/devices" in content or "delete_device" in content, "delete device endpoint missing"


def test_migration_file_exists() -> None:
    """An Alembic migration for device_tokens is created."""
    project_dir = create_fixture_project(name="push_t19")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*device_token*.py"))
    assert migration_files, "No device_tokens migration file found in alembic/versions/"
    content = migration_files[0].read_text()
    assert "device_tokens" in content, "device_tokens table not in migration"


def test_fcm_provider_handles_import_error() -> None:
    """FCMProvider returns False and logs warning when firebase_admin is absent."""
    project_dir = create_fixture_project(name="push_t20")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "push" / "providers" / "fcm.py").read_text()
    assert "ImportError" in content, "FCMProvider must handle ImportError gracefully"
    assert "False" in content, "FCMProvider must return False when firebase_admin absent"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="push_t21")
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="push_t22")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should mention alembic and firebase-admin."""
    project_dir = create_fixture_project(name="push_t23")
    result = add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"
    assert "firebase" in combined, "next_steps should mention firebase-admin"


def test_platform_routing_in_service() -> None:
    """PushService routes 'ios' to APNs and 'android' to FCM."""
    project_dir = create_fixture_project(name="push_t24")
    add_push_notifications_native(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "push" / "service.py").read_text()
    assert '"ios"' in content or "'ios'" in content, "iOS platform routing not in service.py"
    assert '"android"' in content or "'android'" in content, "Android platform routing not in service.py"
    assert "APNsProvider" in content, "APNsProvider not referenced in service.py"
    assert "FCMProvider" in content, "FCMProvider not referenced in service.py"


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
        test_push_init_exports_push_service,
        test_push_service_has_send_to_device_and_topic,
        test_fcm_provider_lazy_import,
        test_apns_provider_lazy_import,
        test_device_token_model_fields,
        test_push_schemas_exist,
        test_crud_file_exists,
        test_routes_file_has_all_endpoints,
        test_migration_file_exists,
        test_fcm_provider_handles_import_error,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
        test_platform_routing_in_service,
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
    print(f"TOOL-082 add_push_notifications_native: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
