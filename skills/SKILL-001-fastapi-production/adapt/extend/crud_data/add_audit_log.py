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

import hashlib
import os

from fastapi import FastAPI

from app.core.config import settings
from core.venous._adapters.fastapi.AuditLogAdapter import install


def _audit_hmac_secret() -> bytes:
    """Resolve the audit-log HMAC key — never hardcoded, never silently absent.

    Precedence:
      1. AUDIT_LOG_HMAC_SECRET env var (prod / KMS-managed), if set; else
      2. a domain-separated key derived from the app's SECRET_KEY.
    SECRET_KEY is required and entropy-checked by Settings (loaded from env or
    .env), so the audit chain always has a real key and the app still boots in
    the standard .env workflow — fail-closed, with no hardcoded placeholder.
    """
    override = os.getenv("AUDIT_LOG_HMAC_SECRET", "").strip()
    if override:
        return override.encode()
    return hashlib.sha256(b"hugr-audit-log:" + settings.SECRET_KEY.encode()).digest()


def install_audit_log(app: FastAPI) -> None:
    """Attach a tamper-evident audit log + /audit-logs router to *app*."""
    install(app, hmac_secret=_audit_hmac_secret())
'''

# Sentinel inserted into main.py so idempotency check works correctly.
_MAIN_SENTINEL = "install_audit_log(app)"

_MAIN_PATCH = '''\


# Audit log — wired by add_audit_log tool
from app.audit_log import install_audit_log  # noqa: E402
install_audit_log(app)
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

    main_file = app_dir / "main.py"
    if (
        glue_file.exists()
        and "AuditLogAdapter" in glue_file.read_text()
        and main_file.exists()
        and _MAIN_SENTINEL in main_file.read_text()
    ):
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

    # Wire install_audit_log(app) into main.py after app = FastAPI(...).
    # Without this the audit log primitives are copied but never activated.
    files_modified: list[str] = []
    main_file = app_dir / "main.py"
    if main_file.exists() and _MAIN_SENTINEL not in main_file.read_text():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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
            "Shipped primitives: AuditEvent, TamperEvidentAuditLog.",
            "Shipped adapter: AuditLogAdapter.",
            "Wrote app/audit_log.py and wired install_audit_log(app) in main.py.",
            "Hash-chained, signed, append-only ledger (TEAL_INV_01..06).",
            "Audit log is active on startup — no manual wiring required.",
        ],
        next_steps=[
            "Audit HMAC key derives from SECRET_KEY by default; set AUDIT_LOG_HMAC_SECRET to override (KMS-managed in prod).",
            "POST /audit-logs/ to append; POST /audit-logs/verify to assert chain integrity.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main(main_file: Path) -> None:
    """Append install_audit_log(app) call to app/main.py after app = FastAPI(...).

    Inserts the call immediately after the ``app = FastAPI(...)`` block so that
    the audit log is active from the first request.  No-op if the sentinel is
    already present.

    Args:
        main_file: Absolute path to ``app/main.py``.
    """
    src = main_file.read_text()
    if _MAIN_SENTINEL in src:
        return
    # Append the wiring block at the end of the file so it runs after
    # app = FastAPI(...) regardless of where that call appears.
    patched = src.rstrip("\n") + "\n" + _MAIN_PATCH
    main_file.write_text(patched)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
