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
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

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


_GLUE = '''\
"""Wire the inbound-webhook pipeline into the FastAPI app.

Delegates to the primitives + FastAPI adapter copied under `core/venous/`
by the `add_webhook_receiver` tool. Re-emitted idempotently on subsequent
tool runs; hand-editing is safe.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.WebhookReceiverAdapter import install


def install_webhook_receiver(app: FastAPI) -> None:
    """Attach the verify → dedup → audit pipeline to *app*."""
    install(
        app,
        hmac_key=os.getenv("WEBHOOK_HMAC_KEY", "change-me-hmac-secret-bytes").encode(),
        key_id=os.getenv("WEBHOOK_KEY_ID", "default"),
        path=os.getenv("WEBHOOK_PATH", "/webhooks/in"),
    )
'''


def add_webhook_receiver(inp: ToolInput) -> ToolResult:
    """Add a webhook receiver by delegating to shipped primitives + adapter."""
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
    # NOTE: app/webhook_receiver.py, NOT app/webhooks.py. add_webhook_sender
    # emits an app/webhooks/ PACKAGE; a sibling app/webhooks.py MODULE would be
    # shadowed by that package on import (packages win), making
    # install_webhook_receiver unreachable when both tools are applied. The
    # distinct filename keeps send + receive composable.
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
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

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


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
