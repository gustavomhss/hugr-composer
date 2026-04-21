"""TOOL-005: add_audit_log — tamper-evident audit log for FastAPI.

CONTRACT §B1.3 refactor — copies the framework-agnostic
``AuditEvent`` + ``TamperEvidentAuditLog`` primitives and the FastAPI
``AuditLogAdapter`` into the generated project, then emits a ≤20-line
glue module at ``app/audit_log.py`` that wires them via
``install(app, hmac_secret=...)``.

Idempotent: a second run detects the import chain in ``app/audit_log.py``
and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_data_add_audit_log",
    "description": (
        "Copy AuditEvent + TamperEvidentAuditLog primitives and the "
        "AuditLogAdapter into the project, then wire a ≤20-line "
        "app/audit_log.py caller."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_audit_log",
    "imports_primitives": [
        "core.venous.compliance.AuditEvent",
        "core.venous.compliance.TamperEvidentAuditLog",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.AuditLogAdapter",
    ],
}


_GLUE = '''\
"""Wire the tamper-evident audit log into the FastAPI app.

Delegates to the primitive + FastAPI adapter copied under `core/venous/`
by the `add_audit_log` tool. Re-emitted idempotently.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from core.venous._adapters.fastapi.AuditLogAdapter import install


def install_audit_log(app: FastAPI) -> None:
    """Attach a tamper-evident audit log + /audit-logs router to *app*."""
    install(
        app,
        hmac_secret=os.getenv(
            "AUDIT_LOG_HMAC_SECRET",
            "change-me-to-a-real-kms-key-xxxx",
        ).encode(),
    )
'''


def add_audit_log(inp: ToolInput) -> ToolResult:
    """Add a tamper-evident audit log by delegating to primitives + adapter."""
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
    glue_file = app_dir / "audit_log.py"

    if glue_file.exists() and "AuditLogAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Audit log already wired via the FastAPI adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy AuditEvent + TamperEvidentAuditLog primitives + adapter "
                "and write app/audit_log.py."
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
            "Shipped primitives: AuditEvent, TamperEvidentAuditLog.",
            "Shipped adapter: AuditLogAdapter.",
            "Wrote app/audit_log.py — call install_audit_log(app) from main.py.",
            "Hash-chained, signed, append-only ledger (TEAL_INV_01..06).",
        ],
        next_steps=[
            "Set AUDIT_LOG_HMAC_SECRET in .env (≥16 bytes); rotate via KMS in prod.",
            "Import install_audit_log in app/main.py and invoke it after FastAPI() construction.",
            "POST /audit-logs/ to append; POST /audit-logs/verify to assert chain integrity.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
