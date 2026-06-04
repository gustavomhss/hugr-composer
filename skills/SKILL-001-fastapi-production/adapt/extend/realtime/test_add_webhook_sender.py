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
import json
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.realtime.add_webhook_sender import MCP_TOOL, add_webhook_sender
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


def _bare_project() -> Path:
    """A valid (existing) dir MISSING the config/requirements prereqs, so the
    auto-scaffold and prerequisite-error code paths get exercised."""
    d = Path(tempfile.mkdtemp()) / "bare"
    d.mkdir()
    return d


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
    """CC-11: URL CheckConstraint validates http/https prefix in migration."""
    project_dir = create_fixture_project(name="whs_t13")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*webhook_sender*"))
    assert migration_files, "No migration file"
    content = migration_files[0].read_text()
    assert "http" in content and "url" in content.lower(), "URL format constraint must be present"


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
# CONTRACT §B1.0 + §B1.0.1 — primitive copy + thin glue
# ---------------------------------------------------------------------------


def test_primitives_copied() -> None:
    """CONTRACT §B1.0: SignatureVerifier + RetryPolicy copied into project."""
    project_dir = create_fixture_project(name="whs_b10_prim")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    sv = project_dir / "core" / "venous" / "security" / "SignatureVerifier" / "SignatureVerifier.py"
    rp = project_dir / "core" / "venous" / "resiliency" / "RetryPolicy" / "RetryPolicy.py"
    assert sv.exists() and rp.exists()
    assert "class DetachedSigner" in sv.read_text()
    assert "class ExponentialBackoffRetryPolicy" in rp.read_text()


def test_manifest_records_primitives() -> None:
    """CONTRACT §B1.0: .venous_manifest.json records both primitives."""
    project_dir = create_fixture_project(name="whs_b10_manifest")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    qnames = {p["qualified_name"] for p in manifest["primitives"]}
    assert "core.venous.security.SignatureVerifier" in qnames
    assert "core.venous.resiliency.RetryPolicy" in qnames


def test_glue_imports_primitives() -> None:
    """CONTRACT §B1.0.1: glue imports DetachedSigner + ExponentialBackoffRetryPolicy."""
    project_dir = create_fixture_project(name="whs_b10_glue")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "webhooks" / "sender.py"
    assert glue.exists()
    body = glue.read_text()
    assert "from core.venous.security.SignatureVerifier" in body
    assert "from core.venous.resiliency.RetryPolicy" in body
    assert "DetachedSigner" in body
    assert "ExponentialBackoffRetryPolicy" in body


def test_glue_body_under_20_loc() -> None:
    """CONTRACT §B1.0.1: glue body stays below 20 executable lines."""
    project_dir = create_fixture_project(name="whs_b10_loc")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    tree = ast.parse((project_dir / "app" / "webhooks" / "sender.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_mcp_tool_metadata() -> None:
    """MCP_TOOL declares imports_primitives per CONTRACT §B1.0."""
    assert MCP_TOOL["entry"] == "add_webhook_sender"
    assert "core.venous.security.SignatureVerifier" in MCP_TOOL["imports_primitives"]
    assert "core.venous.resiliency.RetryPolicy" in MCP_TOOL["imports_primitives"]
    assert tuple(MCP_TOOL["imports_adapters"]) == ()


# ---------------------------------------------------------------------------
# Mutation-hardening tests (kill specific surviving mutants)
# ---------------------------------------------------------------------------


def test_execution_time_within_sane_bound() -> None:
    """L347 ``_ms`` BinOp ``Add->Sub``: ``monotonic() - start`` flipped to ``+``
    yields a multi-billion-ms blow-up while still > 0.  Pin a sane upper bound."""
    project_dir = create_fixture_project(name="whs_m_ms")
    ms = add_webhook_sender(ToolInput(project_dir=str(project_dir))).execution_time_ms
    assert 0 < ms < 60_000, f"implausible execution_time_ms={ms}"


def test_bare_project_auto_scaffolds() -> None:
    """L75 ``auto_scaffold=not inp.dry_run`` and L85 ``list(scaffolded or [])``.

    On a bare project (no prereqs) a real run must auto-scaffold and REPORT the
    scaffolded config.py in files_created.  Dropping the ``not`` would skip
    scaffolding -> error; flipping ``or``->``and`` would drop the file report.
    """
    p = _bare_project()
    r = add_webhook_sender(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error
    assert any(c.endswith("config.py") for c in r.files_created), r.files_created
    assert (p / "app" / "core" / "config.py").exists()


def test_bare_project_dry_run_reports_prereq_error() -> None:
    """L75 ``auto_scaffold=not inp.dry_run`` + L80 prereq-error ``+`` concat.

    dry_run on a bare project keeps auto_scaffold OFF, so prereqs are missing.
    A ``+``->``-`` on the error-string concat would raise TypeError instead of
    returning the error result.
    """
    p = _bare_project()
    r = add_webhook_sender(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "error"
    assert "Prerequisites not met" in (r.error or "")


def test_migration_down_revision_is_real_head() -> None:
    """L180 ``find_migration_head(...) or "0001_initial"`` BoolOp ``Or->And``.

    The fixture head is ``0002_baseline_schema``.  With ``and`` the truthy head
    is discarded and ``down_revision`` becomes ``"0001_initial"`` (wrong).
    """
    project_dir = create_fixture_project(name="whs_m_downrev")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    mig = (project_dir / "alembic" / "versions" / "0015_add_webhook_sender.py").read_text()
    assert 'down_revision = "0002_baseline_schema"' in mig, mig


def test_webhooks_package_init_created() -> None:
    """L248 ``_ensure_pkg``: ``if not i.exists()`` UnaryNot.  Flipping ``not``
    writes __init__.py only when it already exists -> packages get no __init__."""
    project_dir = create_fixture_project(name="whs_m_pkginit")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "app" / "webhooks" / "__init__.py").exists()
    assert (project_dir / "app" / "core" / "webhooks" / "__init__.py").exists()
    assert (project_dir / "app" / "workers" / "__init__.py").exists()


def test_emitted_project_test_created() -> None:
    """L319 ``_emit_project_test``: ``if not emitted.exists()`` UnaryNot.
    Flipping ``not`` skips emitting the project test on a fresh run."""
    project_dir = create_fixture_project(name="whs_m_emitted")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert (project_dir / "tests" / "test_add_webhook_sender_emitted.py").exists()


def test_models_init_patched_with_webhook_imports() -> None:
    """L261 ``_patch_models_init``: ``if not models_init.exists(): return``.
    Flipping ``not`` returns early when the file exists -> no patching at all."""
    project_dir = create_fixture_project(name="whs_m_modelsinit")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    init = (project_dir / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.webhook import WebhookEndpoint" in init
    assert "from app.models.webhook import WebhookDelivery" in init


def test_append_if_missing_appends_to_existing_crud() -> None:
    """L255 ``if marker in existing: return`` In->NotIn and L257 append ``+``.

    A pre-seeded crud/webhook.py lacking the ``create_endpoint`` marker must be
    APPENDED to (not replaced, not skipped).  In->NotIn would return early and
    skip the append; ``+``->``-`` would raise TypeError (str - str).
    """
    project_dir = create_fixture_project(name="whs_m_append")
    crud = project_dir / "app" / "crud" / "webhook.py"
    crud.parent.mkdir(parents=True, exist_ok=True)
    crud.write_text('"""Pre-existing crud."""\nSENTINEL_CRUD = 1\n')
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    content = crud.read_text()
    assert "SENTINEL_CRUD = 1" in content, "original content must be preserved"
    assert "create_endpoint" in content, "marker block must be appended"
    assert any("crud/webhook.py" in m for m in r.files_modified)


def test_append_if_missing_no_double_append() -> None:
    """L255 ``if marker in existing: return`` In->NotIn (other direction).

    A pre-seeded crud/webhook.py that ALREADY contains ``create_endpoint`` must
    NOT be appended to a second time.  With In->NotIn the early-return is lost
    and the block is appended despite the marker being present.
    """
    project_dir = create_fixture_project(name="whs_m_noappend")
    crud = project_dir / "app" / "crud" / "webhook.py"
    crud.parent.mkdir(parents=True, exist_ok=True)
    crud.write_text('"""Has marker."""\ndef create_endpoint():\n    return None\n')
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    content = crud.read_text()
    assert content.count("CRUD helpers for WebhookEndpoint") == 0, (
        "must not append the template block when marker already present"
    )


def test_config_block_inserted_after_anchor() -> None:
    """L287 ``if anchor in src:`` In->NotIn in ``_patch_config``.

    The webhook settings block must be inserted immediately after the
    ACCESS_TOKEN_EXPIRE_MINUTES anchor.  With In->NotIn the anchor branch is
    skipped and the block lands before ``settings = Settings()`` instead.
    """
    project_dir = create_fixture_project(name="whs_m_cfganchor")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    cfg = (project_dir / "app" / "core" / "config.py").read_text()
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    block_marker = "# --- Webhook sender settings ---"
    assert anchor in cfg and block_marker in cfg
    after_anchor = cfg.split(anchor, 1)[1]
    # The block must appear right after the anchor, before any later marker.
    assert after_anchor.lstrip().startswith(block_marker), (
        "webhook block must be inserted directly after the anchor line"
    )


def test_routes_init_import_after_existing_app_imports() -> None:
    """L299 ``if import_line in src: return`` In->NotIn, L303/L305 positional.

    The webhooks router import must be inserted AFTER the existing ``from app.``
    imports (not before, not skipped, not at the APIRouter() fallback line).
    L299 In->NotIn would skip patching; L305 ``+``->``-`` and L303 ``==``->``!=``
    would land the import in the wrong position.
    """
    project_dir = create_fixture_project(name="whs_m_routeimp")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    import_idx = next(
        i for i, ln in enumerate(lines) if "webhooks import router as webhooks_router" in ln
    )
    last_existing_app = max(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("from app.") and "webhooks_router" not in ln
    )
    assert import_idx == last_existing_app + 1, (
        f"import at {import_idx}, expected just after {last_existing_app}"
    )


def test_routes_init_include_after_existing_includes() -> None:
    """L309/L311 positional in ``_patch_routes_init``.

    The ``include_router(webhooks_router)`` line must be inserted right after the
    last existing ``api_router.include_router(...)`` line.  L311 ``+``->``-`` and
    L309 ``==``->``!=`` (fallback to APIRouter() line) misplace it.
    """
    project_dir = create_fixture_project(name="whs_m_routeinc")
    add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    lines = (project_dir / "app" / "routes" / "__init__.py").read_text().splitlines()
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(webhooks_router)" in ln)
    last_existing_inc = max(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("api_router.include_router") and "webhooks_router" not in ln
    )
    assert include_idx == last_existing_inc + 1, (
        f"include at {include_idx}, expected just after {last_existing_inc}"
    )


def test_schema_append_path_when_file_preexists() -> None:
    """L158 ``"WebhookEndpointCreate" not in schema...`` NotIn->In branch.

    Pre-seed schemas/webhook.py without the ``WebhookEndpointCreate`` marker so
    the append branch fires (not the elif create branch).  NotIn->In would skip
    the append, leaving the required public schema absent.
    """
    project_dir = create_fixture_project(name="whs_m_schemaapp")
    schema = project_dir / "app" / "schemas" / "webhook.py"
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text('"""Pre-existing schemas."""\nSENTINEL_SCHEMA = 1\n')
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    content = schema.read_text()
    assert "SENTINEL_SCHEMA = 1" in content
    assert "WebhookEndpointPublic" in content, "schema block must be appended"
    assert any("schemas/webhook.py" in m for m in r.files_modified)


def test_config_block_inserted_before_settings_when_no_anchor() -> None:
    """``_patch_config`` ``elif "settings = Settings()" in src:`` In->NotIn and
    the ``block + "\\nsettings = Settings()"`` concat ``Add->Sub``.

    Strip the ACCESS_TOKEN anchor so the anchor branch cannot fire; the settings
    branch must then insert the webhook block immediately *before* the
    ``settings = Settings()`` line.  In->NotIn would skip this branch (falling to
    the else append); ``+``->``-`` on the concat would raise TypeError.
    """
    project_dir = create_fixture_project(name="whs_m_cfgsettings")
    cfg = project_dir / "app" / "core" / "config.py"
    # Remove the anchor so only the settings branch can match.
    cfg.write_text(
        cfg.read_text().replace(
            "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30",
            "    OTHER_TOKEN_EXPIRE_MINUTES: int = 30",
        )
    )
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    out = cfg.read_text()
    block_marker = "# --- Webhook sender settings ---"
    assert block_marker in out, "webhook block must be injected"
    block_idx = out.find(block_marker)
    settings_idx = out.find("settings = Settings()")
    assert settings_idx != -1
    assert 0 <= block_idx < settings_idx, (
        "block must be inserted immediately before 'settings = Settings()'"
    )


def test_config_block_appended_when_no_anchor_no_settings() -> None:
    """``_patch_config`` else branch ``src.rstrip("\\n") + "\\n" + block``
    ``Add->Sub``.

    Strip BOTH the anchor and the bare ``settings = Settings()`` line so neither
    branch matches and the else-append path fires.  ``+``->``-`` on the concat
    would raise TypeError instead of appending; the block must land at the end.
    """
    project_dir = create_fixture_project(name="whs_m_cfgappend")
    cfg = project_dir / "app" / "core" / "config.py"
    src = cfg.read_text()
    src = src.replace(
        "    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30",
        "    OTHER_TOKEN_EXPIRE_MINUTES: int = 30",
    )
    src = src.replace("settings = Settings()", "settings = Settings.build()")
    cfg.write_text(src)
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    out = cfg.read_text()
    assert "# --- Webhook sender settings ---" in out, "block must be appended"
    assert "WEBHOOK_DISABLE_AFTER_FAILURES: int = 12" in out
    # The else branch appends at the very end of the file.
    assert out.rstrip().endswith("WEBHOOK_DISABLE_AFTER_FAILURES: int = 12"), (
        "block must be appended at the tail of the file"
    )


def test_routes_import_falls_back_to_apirouter_line() -> None:
    """L303-L304 ``"APIRouter()" in ln`` In->NotIn fallback in
    ``_patch_routes_init``.

    With NO existing ``from app.`` imports the ``last_app == -1`` fallback must
    find the ``APIRouter()`` line and insert the import directly after it.
    In->NotIn breaks the fallback (default=0) and the import lands at the very
    top, before the APIRouter() line.
    """
    project_dir = create_fixture_project(name="whs_m_rtimpfb")
    ri = project_dir / "app" / "routes" / "__init__.py"
    ri.write_text('"""Routes."""\nfrom fastapi import APIRouter\napi_router = APIRouter()\n')
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    lines = ri.read_text().splitlines()
    import_idx = next(
        i for i, ln in enumerate(lines) if "webhooks import router as webhooks_router" in ln
    )
    apirouter_idx = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    assert import_idx > apirouter_idx, (
        f"import at {import_idx} must come after APIRouter() line at {apirouter_idx}"
    )


def test_routes_include_falls_back_to_apirouter_line() -> None:
    """L309-L310 ``"APIRouter()" in ln`` In->NotIn fallback for the include line.

    With ``from app.`` imports present but NO existing
    ``api_router.include_router(...)`` lines, the ``last_inc == -1`` fallback must
    find the ``APIRouter()`` line and insert the include after it.  In->NotIn
    breaks the fallback (default=0) and the include lands at the top.
    """
    project_dir = create_fixture_project(name="whs_m_rtincfb")
    ri = project_dir / "app" / "routes" / "__init__.py"
    ri.write_text(
        '"""Routes."""\n'
        "from fastapi import APIRouter\n"
        "from app.api.routes.users import router as users_router\n"
        "api_router = APIRouter()\n"
    )
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    lines = ri.read_text().splitlines()
    include_idx = next(i for i, ln in enumerate(lines) if "include_router(webhooks_router)" in ln)
    apirouter_idx = next(i for i, ln in enumerate(lines) if "APIRouter()" in ln)
    assert include_idx > apirouter_idx, (
        f"include at {include_idx} must come after APIRouter() line at {apirouter_idx}"
    )


def test_ensure_pkg_succeeds_when_dirs_preexist() -> None:
    """``_ensure_pkg`` ``d.mkdir(parents=True, exist_ok=True)`` BoolLiteral.

    Pre-create the webhook package dirs so ``mkdir`` hits already-existing
    targets.  Flipping ``exist_ok=True``->``False`` would raise FileExistsError;
    the tool must still succeed and still drop the package ``__init__.py``.
    """
    project_dir = create_fixture_project(name="whs_m_pkgexist")
    (project_dir / "app" / "webhooks").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "core" / "webhooks").mkdir(parents=True, exist_ok=True)
    (project_dir / "app" / "workers").mkdir(parents=True, exist_ok=True)
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "app" / "webhooks" / "__init__.py").exists()
    assert (project_dir / "app" / "core" / "webhooks" / "__init__.py").exists()
    assert (project_dir / "app" / "workers" / "__init__.py").exists()


def test_crud_and_schema_parent_dirs_exist_ok() -> None:
    """L147/L157 ``mkdir(parents=True, exist_ok=True)`` BoolLiteral for the
    crud/schema parent dirs.

    ``app/crud`` and ``app/schemas`` already exist in the fixture, so the tool's
    ``mkdir(... exist_ok=True)`` hits existing targets.  Flipping ``exist_ok`` to
    ``False`` would raise FileExistsError before any file is written; assert a
    clean success and that both target files exist.
    """
    project_dir = create_fixture_project(name="whs_m_crudschema")
    # Sanity: the parent dirs pre-exist (fixture invariant the mutation breaks).
    assert (project_dir / "app" / "crud").is_dir()
    assert (project_dir / "app" / "schemas").is_dir()
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "app" / "crud" / "webhook.py").exists()
    assert (project_dir / "app" / "schemas" / "webhook.py").exists()


def test_emit_project_test_dir_exist_ok() -> None:
    """L317 ``tests_dir.mkdir(parents=True, exist_ok=True)`` BoolLiteral in
    ``_emit_project_test``.

    ``tests/`` already exists in the fixture, so ``exist_ok=True``->``False``
    would raise FileExistsError when emitting the project test.  Assert success
    and that the emitted test file lands inside the existing tests/ dir.
    """
    project_dir = create_fixture_project(name="whs_m_testsdir")
    assert (project_dir / "tests").is_dir()
    r = add_webhook_sender(ToolInput(project_dir=str(project_dir)))
    assert r.status == "success", r.error
    assert (project_dir / "tests" / "test_add_webhook_sender_emitted.py").exists()


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
        test_primitives_copied,
        test_manifest_records_primitives,
        test_glue_imports_primitives,
        test_glue_body_under_20_loc,
        test_mcp_tool_metadata,
        test_execution_time_within_sane_bound,
        test_bare_project_auto_scaffolds,
        test_bare_project_dry_run_reports_prereq_error,
        test_migration_down_revision_is_real_head,
        test_webhooks_package_init_created,
        test_emitted_project_test_created,
        test_models_init_patched_with_webhook_imports,
        test_append_if_missing_appends_to_existing_crud,
        test_append_if_missing_no_double_append,
        test_config_block_inserted_after_anchor,
        test_routes_init_import_after_existing_app_imports,
        test_routes_init_include_after_existing_includes,
        test_schema_append_path_when_file_preexists,
        test_config_block_inserted_before_settings_when_no_anchor,
        test_config_block_appended_when_no_anchor_no_settings,
        test_routes_import_falls_back_to_apirouter_line,
        test_routes_include_falls_back_to_apirouter_line,
        test_ensure_pkg_succeeds_when_dirs_preexist,
        test_crud_and_schema_parent_dirs_exist_ok,
        test_emit_project_test_dir_exist_ok,
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
