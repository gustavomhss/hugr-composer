"""TOOL-016: add_webhook_receiver — inbound webhook handling for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic
``SignatureVerifier`` + ``IdempotentConsumer`` + ``AuditEvent`` primitives
and the FastAPI ``WebhookReceiverAdapter`` into the generated project,
then emits a ≤20-line glue module at ``app/webhook_receiver.py`` that wires
them via ``install(app, ...)``. (Distinct from add_webhook_sender's
``app/webhooks/`` package, which would otherwise shadow it on import.)

Security guarantees (delivered by the primitives, NOT re-implemented here):

* HMAC signature is verified BEFORE any other work (``SignatureVerifier``).
* Redeliveries are deduped by ``X-Event-Id`` header (``IdempotentConsumer``).
* Every first delivery is recorded in a tamper-evident chain (``AuditEvent``).

Idempotent: a second run detects the import chain in
``app/webhook_receiver.py`` and returns ``status="no_op"``.

Templates in ``templates/`` emit all generated source; this file contains only
orchestration.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_realtime_add_webhook_receiver",
    "description": (
        "Copy SignatureVerifier+IdempotentConsumer+AuditEvent primitives and "
        "the WebhookReceiverAdapter into the project, then wire a ≤20-line "
        "app/webhook_receiver.py caller."
    ),
    "tags": ["extend", "realtime"],
    "entry": "add_webhook_receiver",
    "imports_primitives": [
        "core.venous.security.SignatureVerifier",
        "core.venous.events.IdempotentConsumer",
        "core.venous.events.InboxDeduplicator",
        "core.venous.events.TransactionalOutbox",
        "core.venous.compliance.AuditEvent",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.WebhookReceiverAdapter",
    ],
}


def add_webhook_receiver(inp: ToolInput) -> ToolResult:
    """Add a webhook receiver by delegating to shipped primitives + adapter.

    Warnings:
        HMAC verification and replay deduplication are enforced by the copied
        primitives; this tool does not re-implement them.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "webhook_receiver.py"

    if glue_file.exists() and "WebhookReceiverAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Webhook receiver already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy SignatureVerifier + IdempotentConsumer + "
                "AuditEvent primitives + WebhookReceiverAdapter and write app/webhook_receiver.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=MCP_TOOL["imports_primitives"],
        adapters=MCP_TOOL["imports_adapters"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    _emit_project_test(project, files_created)

    files_modified: list[str] = []
    env_example = project / ".env.example"
    if env_example.exists() and _patch_env_example(env_example):
        files_modified.append(str(env_example))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Shipped primitives: SignatureVerifier, IdempotentConsumer (+ Inbox/Outbox siblings), AuditEvent.",
            "Shipped adapter: WebhookReceiverAdapter.",
            "Wrote app/webhook_receiver.py — call install_webhook_receiver(app) from main.py.",
        ],
        next_steps=[
            "Import install_webhook_receiver in app/main.py and invoke it after FastAPI() construction.",
            "Set WEBHOOK_HMAC_KEY / WEBHOOK_KEY_ID / WEBHOOK_PATH in .env.",
            "POST signed deliveries with X-Signature + X-Event-Id headers.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_env_example(env_example: Path) -> bool:
    """Document the env vars the webhook glue reads. Returns True if patched.

    ``app/webhook_receiver.py`` reads ``WEBHOOK_HMAC_KEY`` / ``WEBHOOK_KEY_ID``
    / ``WEBHOOK_PATH`` via ``os.getenv``; surfacing them in ``.env.example``
    keeps generated config self-consistent.
    """
    src = env_example.read_text()
    if "WEBHOOK_HMAC_KEY" in src:
        return False
    trailing = "" if src.endswith("\n") else "\n"
    block = (
        "\n"
        "# --- Webhook receiver (add_webhook_receiver) ---\n"
        "# HMAC key used to verify inbound webhook signatures (set a real value).\n"
        "WEBHOOK_HMAC_KEY=\n"
        "# Key identifier advertised to senders (default: 'default').\n"
        "WEBHOOK_KEY_ID=default\n"
        "# Path the inbound webhook endpoint is mounted at.\n"
        "WEBHOOK_PATH=/webhooks/in\n"
    )
    env_example.write_text(src + trailing + block)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    emitted = tests_dir / "test_add_webhook_receiver_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_webhook_receiver_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
