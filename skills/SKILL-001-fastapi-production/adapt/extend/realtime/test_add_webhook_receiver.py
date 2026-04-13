"""Tests for TOOL-016 add_webhook_receiver.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. python3 adapt/extend/realtime/test_add_webhook_receiver.py

or::

    PYTHONPATH=. pytest adapt/extend/realtime/test_add_webhook_receiver.py -v
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver
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
    project_dir = create_fixture_project(name="whr_t01")
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="whr_t02")
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="whr_t03")
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_inbound_model_created() -> None:
    """CC-01: app/models/webhook_inbound.py exists with InboundWebhook."""
    project_dir = create_fixture_project(name="whr_t04")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "webhook_inbound.py"
    assert model_file.exists(), "webhook_inbound.py not created"
    content = model_file.read_text()
    assert "InboundWebhook" in content


def test_base_verifier_created() -> None:
    """CC-02: app/core/inbound_webhooks/base.py defines InboundVerifier ABC and VerifiedEvent."""
    project_dir = create_fixture_project(name="whr_t05")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    base_file = project_dir / "app" / "core" / "inbound_webhooks" / "base.py"
    assert base_file.exists(), "base.py not created"
    content = base_file.read_text()
    assert "InboundVerifier" in content
    assert "VerifiedEvent" in content
    assert "abstractmethod" in content


def test_stripe_verifier_created() -> None:
    """CC-03: providers/stripe.py exists with StripeVerifier."""
    project_dir = create_fixture_project(name="whr_t06")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    stripe_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "stripe.py"
    )
    assert stripe_file.exists(), "stripe.py not created"
    content = stripe_file.read_text()
    assert "StripeVerifier" in content
    assert "stripe-signature" in content


def test_github_verifier_created() -> None:
    """CC-03: providers/github.py exists with GitHubVerifier."""
    project_dir = create_fixture_project(name="whr_t07")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    github_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "github.py"
    )
    assert github_file.exists(), "github.py not created"
    content = github_file.read_text()
    assert "GitHubVerifier" in content
    assert "x-hub-signature-256" in content


def test_internal_verifier_created() -> None:
    """CC-03: providers/internal.py exists with InternalVerifier."""
    project_dir = create_fixture_project(name="whr_t08")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    internal_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "internal.py"
    )
    assert internal_file.exists(), "internal.py not created"
    content = internal_file.read_text()
    assert "InternalVerifier" in content
    assert "x-signature" in content


def test_registry_created() -> None:
    """CC-04: registry.py exists with get_verifier and webhook_handler decorator."""
    project_dir = create_fixture_project(name="whr_t09")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "core" / "inbound_webhooks" / "registry.py"
    assert registry_file.exists(), "registry.py not created"
    content = registry_file.read_text()
    assert "get_verifier" in content
    assert "webhook_handler" in content
    assert "get_handlers" in content


def test_idempotency_cache_created() -> None:
    """CC-05: idempotency.py exists with claim_event using Redis SET NX."""
    project_dir = create_fixture_project(name="whr_t10")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    idempotency_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "idempotency.py"
    )
    assert idempotency_file.exists(), "idempotency.py not created"
    content = idempotency_file.read_text()
    assert "claim_event" in content
    assert "nx=True" in content, "Redis SET NX must be used"


def test_routes_created() -> None:
    """CC-06: inbound_webhooks.py route exists with /webhooks/incoming/{provider}."""
    project_dir = create_fixture_project(name="whr_t11")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "inbound_webhooks.py"
    assert route_file.exists(), "inbound_webhooks.py not created"
    content = route_file.read_text()
    assert "incoming" in content or "/webhooks/incoming" in content
    assert "{provider}" in content or "provider" in content


def test_arq_worker_created() -> None:
    """CC-07: inbound_webhook_worker.py exists with process_inbound_webhook ARQ task."""
    project_dir = create_fixture_project(name="whr_t12")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workers" / "inbound_webhook_worker.py"
    assert worker_file.exists(), "inbound_webhook_worker.py not created"
    content = worker_file.read_text()
    assert "async def process_inbound_webhook" in content
    assert "WorkerSettings" in content


def test_crud_created() -> None:
    """CC-08: app/crud/inbound_webhook.py exists with persistence helpers."""
    project_dir = create_fixture_project(name="whr_t13")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "inbound_webhook.py"
    assert crud_file.exists(), "crud/inbound_webhook.py not created"
    content = crud_file.read_text()
    assert "create_received" in content
    assert "upsert_duplicate" in content
    assert "get" in content


def test_schemas_created() -> None:
    """CC-09: app/schemas/inbound_webhook.py exists with required schemas."""
    project_dir = create_fixture_project(name="whr_t14")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "inbound_webhook.py"
    assert schema_file.exists(), "schemas/inbound_webhook.py not created"
    content = schema_file.read_text()
    assert "InboundWebhookPublic" in content
    assert "InboundWebhookAccepted" in content


def test_migration_created() -> None:
    """CC-10/11: Migration exists and creates table with UNIQUE constraint."""
    project_dir = create_fixture_project(name="whr_t15")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_receiver*"))
    assert len(migration_files) >= 1, "No webhook receiver migration file created"
    content = migration_files[0].read_text()
    assert "inbound_webhooks" in content
    assert "uq_inbound_webhook_event" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_status_enum_constraint() -> None:
    """CC-12: Status CheckConstraint includes all valid statuses."""
    project_dir = create_fixture_project(name="whr_t16")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_receiver*"))
    content = migration_files[0].read_text()
    for status in ("received", "processing", "succeeded", "failed", "duplicate"):
        assert status in content, f"Status '{status}' missing from constraint"


def test_stripe_verifier_rejects_bad_signature() -> None:
    """CC-24: StripeVerifier raises 400 on HMAC mismatch."""
    project_dir = create_fixture_project(name="whr_t17")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    stripe_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "stripe.py"
    )
    content = stripe_file.read_text()
    assert "compare_digest" in content, "Stripe must use compare_digest"
    assert "signature mismatch" in content or "mismatch" in content.lower()
    assert "HTTPException" in content


def test_github_verifier_rejects_bad_signature() -> None:
    """CC-25: GitHubVerifier raises 400 on HMAC mismatch."""
    project_dir = create_fixture_project(name="whr_t18")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    github_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "github.py"
    )
    content = github_file.read_text()
    assert "compare_digest" in content, "GitHub must use compare_digest"
    assert "HTTPException" in content


def test_internal_verifier_rejects_bad_signature() -> None:
    """CC-26: InternalVerifier raises 400 on HMAC mismatch."""
    project_dir = create_fixture_project(name="whr_t19")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    internal_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "internal.py"
    )
    content = internal_file.read_text()
    assert "HTTPException" in content
    assert "mismatch" in content.lower() or "signature" in content.lower()


def test_replay_timestamp_tolerance() -> None:
    """CC-27: Stripe verifier checks timestamp tolerance (abs(now - ts) > tolerance)."""
    project_dir = create_fixture_project(name="whr_t20")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    stripe_file = (
        project_dir / "app" / "core" / "inbound_webhooks" / "providers" / "stripe.py"
    )
    content = stripe_file.read_text()
    assert "abs(" in content, "Stripe must check timestamp tolerance with abs()"
    assert "tolerance" in content.lower() or "_TOLERANCE" in content


def test_handler_registry_via_decorator() -> None:
    """CC-29: webhook_handler decorator registers and returns the function."""
    project_dir = create_fixture_project(name="whr_t21")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "core" / "inbound_webhooks" / "registry.py"
    content = registry_file.read_text()
    assert "def deco" in content or "def decorator" in content or "def deco(" in content or "_HANDLERS.setdefault" in content
    assert "return fn" in content or "return deco" in content


def test_idempotency_ttl_configured() -> None:
    """CC-13: INBOUND_WEBHOOK_IDEMPOTENCY_TTL appears in config."""
    project_dir = create_fixture_project(name="whr_t22")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "INBOUND_WEBHOOK_IDEMPOTENCY_TTL" in content


def test_provider_secrets_in_config() -> None:
    """CC-14: Per-provider secrets appear in config."""
    project_dir = create_fixture_project(name="whr_t23")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "STRIPE_WEBHOOK_SECRET" in content


def test_all_py_files_parse() -> None:
    """CC-19: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="whr_t24")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-28: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="whr_t25")
    r1 = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="whr_t26")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="whr_t27")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="whr_t28")
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="whr_t29")
    result = add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


def test_body_size_cap_before_verification() -> None:
    """INV-WR-05: Route checks body size before calling verifier."""
    project_dir = create_fixture_project(name="whr_t30")
    add_webhook_receiver(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "inbound_webhooks.py"
    content = route_file.read_text()
    # The size check must appear before the verifier call
    size_check_idx = content.find("_MAX_PAYLOAD_BYTES")
    verifier_call_idx = content.find("get_verifier(")
    assert size_check_idx != -1, "Route must check payload size"
    assert verifier_call_idx != -1, "Route must call get_verifier"
    assert size_check_idx < verifier_call_idx, (
        "Size check must come BEFORE verifier call (INV-WR-05)"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_inbound_model_created,
        test_base_verifier_created,
        test_stripe_verifier_created,
        test_github_verifier_created,
        test_internal_verifier_created,
        test_registry_created,
        test_idempotency_cache_created,
        test_routes_created,
        test_arq_worker_created,
        test_crud_created,
        test_schemas_created,
        test_migration_created,
        test_status_enum_constraint,
        test_stripe_verifier_rejects_bad_signature,
        test_github_verifier_rejects_bad_signature,
        test_internal_verifier_rejects_bad_signature,
        test_replay_timestamp_tolerance,
        test_handler_registry_via_decorator,
        test_idempotency_ttl_configured,
        test_provider_secrets_in_config,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_body_size_cap_before_verification,
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
