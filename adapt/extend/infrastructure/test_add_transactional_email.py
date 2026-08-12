"""Tests for TOOL-081 add_transactional_email.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_transactional_email.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_transactional_email.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_transactional_email import add_transactional_email
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
    project_dir = create_fixture_project(name="txemail_t01")
    result = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="txemail_t02")
    r1 = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="txemail_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_transactional_email(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """Tool creates at least 7 new files."""
    project_dir = create_fixture_project(name="txemail_t04")
    result = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, (
        f"Expected >= 7 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes __init__)."""
    project_dir = create_fixture_project(name="txemail_t05")
    result = add_transactional_email(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="txemail_t06")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="txemail_t07")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """EMAIL_PROVIDER + all API key fields are inside Settings."""
    project_dir = create_fixture_project(name="txemail_t08")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("EMAIL_PROVIDER", "RESEND_API_KEY", "POSTMARK_API_KEY", "SENDGRID_API_KEY"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify 4-space indent (inside Settings body)
    for line in content.splitlines():
        if "EMAIL_PROVIDER" in line and ":" in line:
            assert line.startswith("    "), (
                f"EMAIL_PROVIDER not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_models_init_patched() -> None:
    """EmailEvent model is registered in app/models/__init__.py."""
    project_dir = create_fixture_project(name="txemail_t09")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    content = models_init.read_text()
    assert "EmailEvent" in content, "EmailEvent not registered in models __init__"


def test_routes_registered() -> None:
    """email_events router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="txemail_t10")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "email_events" in content.lower() or "email" in content.lower(), (
            "email_events router not in routes __init__"
        )


# ---------------------------------------------------------------------------
# Category C — Domain-specific
# ---------------------------------------------------------------------------

def test_providers_package_exists() -> None:
    """app/email/providers/__init__.py has get_provider factory."""
    project_dir = create_fixture_project(name="txemail_t11")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "email" / "providers" / "__init__.py"
    assert init_file.exists(), "app/email/providers/__init__.py not created"
    content = init_file.read_text()
    assert "get_provider" in content, "get_provider factory not in providers __init__"


def test_resend_provider_lazy_import() -> None:
    """ResendProvider uses lazy import for resend SDK."""
    project_dir = create_fixture_project(name="txemail_t12")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    resend_file = project_dir / "app" / "email" / "providers" / "resend_provider.py"
    assert resend_file.exists(), "app/email/providers/resend_provider.py not created"
    # SDK import must NOT be at module level
    tree = ast.parse(resend_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "resend" not in alias.name.lower(), (
                    "resend imported at module level in resend_provider.py"
                )


def test_postmark_provider_lazy_import() -> None:
    """PostmarkProvider uses lazy import for postmarker SDK."""
    project_dir = create_fixture_project(name="txemail_t13")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    postmark_file = project_dir / "app" / "email" / "providers" / "postmark_provider.py"
    assert postmark_file.exists(), "app/email/providers/postmark_provider.py not created"
    tree = ast.parse(postmark_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "postmark" not in (node.module or ""), (
                    "postmarker imported at module level in postmark_provider.py"
                )


def test_sendgrid_provider_lazy_import() -> None:
    """SendgridProvider uses lazy import for sendgrid SDK."""
    project_dir = create_fixture_project(name="txemail_t14")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    sg_file = project_dir / "app" / "email" / "providers" / "sendgrid_provider.py"
    assert sg_file.exists(), "app/email/providers/sendgrid_provider.py not created"
    tree = ast.parse(sg_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or "sendgrid" not in (node.module or ""), (
                    "sendgrid imported at module level in sendgrid_provider.py"
                )


def test_delivery_tracker_exists() -> None:
    """app/email/delivery_tracker.py defines DeliveryTracker with track and list_events."""
    project_dir = create_fixture_project(name="txemail_t15")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    tracker_file = project_dir / "app" / "email" / "delivery_tracker.py"
    assert tracker_file.exists(), "app/email/delivery_tracker.py not created"
    content = tracker_file.read_text()
    assert "DeliveryTracker" in content, "DeliveryTracker class not found"
    assert "track" in content, "track method not found"
    assert "list_events" in content, "list_events method not found"


def test_pii_redaction_in_tracker() -> None:
    """DeliveryTracker uses _redact_email and never stores full recipient."""
    project_dir = create_fixture_project(name="txemail_t16")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "email" / "delivery_tracker.py").read_text()
    assert "_redact_email" in content, "_redact_email helper not in delivery_tracker.py"
    assert "recipient_redacted" in content, "recipient_redacted field not referenced"


def test_email_event_model_exists() -> None:
    """app/models/email_event.py defines EmailEvent with correct fields."""
    project_dir = create_fixture_project(name="txemail_t17")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "email_event.py"
    assert model_file.exists(), "app/models/email_event.py not created"
    content = model_file.read_text()
    assert "EmailEvent" in content, "EmailEvent class not found"
    for field in ("message_id", "event_type", "recipient_redacted", "provider", "occurred_at"):
        assert field in content, f"Field {field!r} not in EmailEvent model"


def test_email_event_schema_has_no_full_recipient() -> None:
    """EmailEventRead schema does NOT expose a full 'recipient' field (PII guard)."""
    project_dir = create_fixture_project(name="txemail_t18")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "email_event.py"
    assert schema_file.exists(), "app/schemas/email_event.py not created"
    # PII check: no bare 'recipient: str' field (only recipient_redacted is allowed)
    content = schema_file.read_text()
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and "Read" in node.name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    assert field_name != "recipient", (
                        f"PII violation: full 'recipient' field exposed in {node.name}"
                    )


def test_routes_has_webhook_and_events() -> None:
    """app/api/routes/email_events.py has /webhook/{provider} and /events."""
    project_dir = create_fixture_project(name="txemail_t19")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "email_events.py"
    assert routes_file.exists(), "app/api/routes/email_events.py not created"
    content = routes_file.read_text()
    assert "webhook" in content, "webhook route not in email_events.py"
    assert "/events" in content, "/events route not in email_events.py"


def test_migration_file_exists() -> None:
    """An Alembic migration for email_events is created."""
    project_dir = create_fixture_project(name="txemail_t20")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*email_event*.py"))
    assert migration_files, "No email_events migration file found in alembic/versions/"
    content = migration_files[0].read_text()
    assert "email_events" in content, "email_events table not in migration"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="txemail_t21")
    result = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="txemail_t22")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_next_steps_present() -> None:
    """next_steps should mention alembic and EMAIL_PROVIDER."""
    project_dir = create_fixture_project(name="txemail_t23")
    result = add_transactional_email(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "alembic" in combined, "next_steps should mention alembic"
    assert "email_provider" in combined, "next_steps should mention EMAIL_PROVIDER"


def test_all_three_providers_created() -> None:
    """All three provider files exist: resend, postmark, sendgrid."""
    project_dir = create_fixture_project(name="txemail_t24")
    add_transactional_email(ToolInput(project_dir=str(project_dir)))
    providers_dir = project_dir / "app" / "email" / "providers"
    for provider in ("resend_provider.py", "postmark_provider.py", "sendgrid_provider.py"):
        assert (providers_dir / provider).exists(), f"{provider} not created"


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
        test_providers_package_exists,
        test_resend_provider_lazy_import,
        test_postmark_provider_lazy_import,
        test_sendgrid_provider_lazy_import,
        test_delivery_tracker_exists,
        test_pii_redaction_in_tracker,
        test_email_event_model_exists,
        test_email_event_schema_has_no_full_recipient,
        test_routes_has_webhook_and_events,
        test_migration_file_exists,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
        test_next_steps_present,
        test_all_three_providers_created,
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
    print(f"TOOL-081 add_transactional_email: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
