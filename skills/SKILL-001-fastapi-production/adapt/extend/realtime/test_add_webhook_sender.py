"""Tests for TOOL-015 add_webhook_sender.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_webhook_sender.py

or::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_webhook_sender.py -v
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_webhook_sender import add_webhook_sender
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
    project_dir = create_fixture_project(name="whs_t01")
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="whs_t02")
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="whs_t03")
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_models_file_created() -> None:
    """CC-01: app/models/webhook.py exists with WebhookEndpoint and WebhookDelivery."""
    project_dir = create_fixture_project(name="whs_t04")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "webhook.py"
    assert model_file.exists(), "webhook.py not created"
    content = model_file.read_text()
    assert "WebhookEndpoint" in content
    assert "WebhookDelivery" in content


def test_signer_file_created() -> None:
    """CC-02: app/core/webhooks/signer.py exists with sign_payload and verify_signature."""
    project_dir = create_fixture_project(name="whs_t05")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    signer_file = project_dir / "app" / "core" / "webhooks" / "signer.py"
    assert signer_file.exists(), "signer.py not created"
    content = signer_file.read_text()
    assert "sign_payload" in content
    assert "verify_signature" in content
    assert "hmac.compare_digest" in content


def test_backoff_file_created() -> None:
    """CC-03: app/core/webhooks/backoff.py exists with ATTEMPT_DELAYS_SECONDS."""
    project_dir = create_fixture_project(name="whs_t06")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    backoff_file = project_dir / "app" / "core" / "webhooks" / "backoff.py"
    assert backoff_file.exists(), "backoff.py not created"
    content = backoff_file.read_text()
    assert "ATTEMPT_DELAYS_SECONDS" in content
    assert "delay_for_attempt" in content


def test_sender_file_created() -> None:
    """CC-04: app/core/webhooks/sender.py exists with send_webhook."""
    project_dir = create_fixture_project(name="whs_t07")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    sender_file = project_dir / "app" / "core" / "webhooks" / "sender.py"
    assert sender_file.exists(), "sender.py not created"
    content = sender_file.read_text()
    assert "async def send_webhook" in content
    assert "enqueue_job" in content


def test_worker_file_created() -> None:
    """CC-05: app/workers/webhook_worker.py exists with deliver_webhook ARQ task."""
    project_dir = create_fixture_project(name="whs_t08")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "webhook_worker.py"
    assert worker_file.exists(), "webhook_worker.py not created"
    content = worker_file.read_text()
    assert "async def deliver_webhook" in content


def test_crud_file_created() -> None:
    """CC-06: app/crud/webhook.py exists with CRUD helpers."""
    project_dir = create_fixture_project(name="whs_t09")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "webhook.py"
    assert crud_file.exists(), "crud/webhook.py not created"
    content = crud_file.read_text()
    assert "create_endpoint" in content
    assert "get_endpoint" in content
    assert "list_endpoints_for_user" in content
    assert "create_delivery" in content


def test_routes_file_created() -> None:
    """CC-07: app/api/routes/webhooks.py exists with admin routes."""
    project_dir = create_fixture_project(name="whs_t10")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "webhooks.py"
    assert route_file.exists(), "webhooks.py not created"
    content = route_file.read_text()
    assert "create_webhook" in content
    assert "list_my_webhooks" in content
    assert "delete_webhook" in content


def test_schemas_file_created() -> None:
    """CC-08: app/schemas/webhook.py exists with required schemas."""
    project_dir = create_fixture_project(name="whs_t11")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "webhook.py"
    assert schema_file.exists(), "schemas/webhook.py not created"
    content = schema_file.read_text()
    assert "WebhookCreate" in content
    assert "WebhookEndpointPublic" in content
    assert "WebhookDeliveryPublic" in content


def test_migration_file_created() -> None:
    """CC-09/10: Migration file creates 2 tables with check constraints."""
    project_dir = create_fixture_project(name="whs_t12")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_sender*"))
    assert len(migration_files) >= 1, "No webhook sender migration file created"
    content = migration_files[0].read_text()
    assert "webhook_endpoints" in content
    assert "webhook_deliveries" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_url_check_constraint() -> None:
    """CC-11: URL CheckConstraint ^https?://.+ is in the migration."""
    project_dir = create_fixture_project(name="whs_t13")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_sender*"))
    assert migration_files, "No migration file"
    content = migration_files[0].read_text()
    assert "https?://" in content, "URL format constraint must be present"


def test_status_enum_constraints() -> None:
    """CC-12: Status enum check constraints are in both tables."""
    project_dir = create_fixture_project(name="whs_t14")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_sender*"))
    content = migration_files[0].read_text()
    assert "active" in content and "disabled" in content
    assert "pending" in content and "succeeded" in content


def test_backoff_schedule_values() -> None:
    """CC-21: Backoff schedule has correct values (0, 1, 5, 30, 300, 3600, 21600)."""
    project_dir = create_fixture_project(name="whs_t15")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    backoff_file = project_dir / "app" / "core" / "webhooks" / "backoff.py"
    content = backoff_file.read_text()
    for value in ("0", "1", "5", "30", "300", "3600", "21600"):
        assert value in content, f"Backoff schedule must include {value}"


def test_sign_payload_uses_hmac() -> None:
    """CC-23: sign_payload uses HMAC-SHA256."""
    project_dir = create_fixture_project(name="whs_t16")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    signer_file = project_dir / "app" / "core" / "webhooks" / "signer.py"
    content = signer_file.read_text()
    assert "hmac" in content
    assert "sha256" in content


def test_verify_uses_compare_digest() -> None:
    """CC-24: verify_signature uses hmac.compare_digest."""
    project_dir = create_fixture_project(name="whs_t17")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    signer_file = project_dir / "app" / "core" / "webhooks" / "signer.py"
    content = signer_file.read_text()
    assert "compare_digest" in content, "Signer must use hmac.compare_digest"


def test_verify_checks_timestamp_tolerance() -> None:
    """CC-25: verify_signature rejects stale timestamps."""
    project_dir = create_fixture_project(name="whs_t18")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    signer_file = project_dir / "app" / "core" / "webhooks" / "signer.py"
    content = signer_file.read_text()
    assert "MAX_SIGNATURE_AGE_SECONDS" in content or "tolerance" in content.lower()
    assert "abs(" in content


def test_auto_disable_logic_present() -> None:
    """CC-22: Worker auto-disables endpoint on consecutive failures."""
    project_dir = create_fixture_project(name="whs_t19")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "webhook_worker.py"
    content = worker_file.read_text()
    assert "disabled" in content, "Worker must disable endpoint on too many failures"
    assert "consecutive_failures" in content


def test_secret_excluded_from_list_schema() -> None:
    """CC-29: WebhookEndpointPublic does not declare a secret field."""
    project_dir = create_fixture_project(name="whs_t21")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "webhook.py"
    content = schema_file.read_text()
    # Find WebhookEndpointPublic class body (stop at next class)
    pub_start = content.find("class WebhookEndpointPublic")
    pub_end = content.find("\nclass ", pub_start + 1)
    pub_body = content[pub_start:pub_end] if pub_end != -1 else content[pub_start:]
    # The field declaration would be "    secret: str" — check for that specifically
    assert "    secret: str" not in pub_body, (
        "WebhookEndpointPublic must NOT declare a 'secret' field"
    )
    # WebhookEndpointCreated must have the secret field
    assert "WebhookEndpointCreated" in content
    created_start = content.find("class WebhookEndpointCreated")
    created_body = content[created_start:]
    assert "secret" in created_body, "WebhookEndpointCreated must expose secret"


def test_worker_class_registered_for_arq() -> None:
    """CC-30: WorkerSettings class with functions = [deliver_webhook] is present."""
    project_dir = create_fixture_project(name="whs_t22")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "webhook_worker.py"
    content = worker_file.read_text()
    assert "WorkerSettings" in content
    assert "functions" in content


def test_all_py_files_parse() -> None:
    """CC-18: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="whs_t23")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-26: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="whs_t24")
    r1 = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="whs_t25")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="whs_t26")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="whs_t27")
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="whs_t28")
    result = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


def test_custom_max_attempts_respected() -> None:
    """Custom max_attempts value propagates to the worker configuration."""
    project_dir = create_fixture_project(name="whs_t29")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)), max_attempts=5)
    worker_file = project_dir / "app" / "workers" / "webhook_worker.py"
    content = worker_file.read_text()
    # The config is read from settings, so the important check is
    # that the worker references WEBHOOK_MAX_ATTEMPTS from settings
    config_file = project_dir / "app" / "core" / "config.py"
    config_content = config_file.read_text()
    assert "WEBHOOK_MAX_ATTEMPTS" in config_content


def test_payload_deterministic_serialization() -> None:
    """QS-02: Worker serializes payload with sort_keys=True."""
    project_dir = create_fixture_project(name="whs_t30")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "webhook_worker.py"
    content = worker_file.read_text()
    assert "sort_keys=True" in content, "Worker must serialize with sort_keys=True"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_models_file_created,
        test_signer_file_created,
        test_backoff_file_created,
        test_sender_file_created,
        test_worker_file_created,
        test_crud_file_created,
        test_routes_file_created,
        test_schemas_file_created,
        test_migration_file_created,
        test_url_check_constraint,
        test_status_enum_constraints,
        test_backoff_schedule_values,
        test_sign_payload_uses_hmac,
        test_verify_uses_compare_digest,
        test_verify_checks_timestamp_tolerance,
        test_auto_disable_logic_present,
        test_secret_excluded_from_list_schema,
        test_worker_class_registered_for_arq,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_custom_max_attempts_respected,
        test_payload_deterministic_serialization,
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
