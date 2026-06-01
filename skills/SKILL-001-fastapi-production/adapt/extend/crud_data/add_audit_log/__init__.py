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

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

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

# Sentinel inserted into main.py so idempotency check works correctly.
_MAIN_SENTINEL = "install_audit_log(app)"


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
    render_to(_HERE, "audit_log_glue.py.tmpl", dest=glue_file, substitutions={})
    files_created.append(str(glue_file))

    # R5-S1-F5: emit the durable SQL-backed store (opt-in via AUDIT_LOG_DURABLE).
    store_file = app_dir / "audit_log_store.py"
    render_to(_HERE, "audit_log_store.py.tmpl", dest=store_file, substitutions={})
    files_created.append(str(store_file))

    # Wire install_audit_log(app) into main.py after app = FastAPI(...).
    # Without this the audit log primitives are copied but never activated.
    files_modified: list[str] = []
    if main_file.exists() and _MAIN_SENTINEL not in main_file.read_text():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists() and _patch_config(config_file):
        files_modified.append(str(config_file))

    _emit_project_test(project, files_created)

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
            "Ledger is IN-MEMORY BY DEFAULT (per-process, lost on restart). It is durable "
            "and cross-worker ONLY WHEN you set AUDIT_LOG_DURABLE=true (see next_steps): "
            "app/audit_log_store.py (SqlTamperEvidentAuditLog) then persists the same hash "
            "chain to the audit_log_entries table (created on first use). The hash chain is "
            "tamper-EVIDENT either way.",
            "Audit log is active on startup — no manual wiring required.",
        ],
        next_steps=[
            "Audit HMAC key derives from SECRET_KEY by default; set AUDIT_LOG_HMAC_SECRET to override (KMS-managed in prod).",
            "For durability set AUDIT_LOG_DURABLE=true; PostgreSQL needs a SYNC driver "
            "installed (e.g. `psycopg`) — SQLite works out of the box. The durable store "
            "self-creates audit_log_entries on first append.",
            "The /audit-logs routes are superuser-only and record the actor from the "
            "authenticated principal; in-process code appends via app.state.audit_log.append(...). "
            "POST /audit-logs/verify (superuser) asserts chain integrity.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_main(main_file: Path) -> None:
    """Append install_audit_log(app) wiring to app/main.py — idempotent."""
    src = main_file.read_text()
    if _MAIN_SENTINEL in src:
        return
    patch_block = render(_HERE, "main_patch.py.tmpl", {})
    patched = src.rstrip("\n") + "\n\n" + patch_block
    main_file.write_text(patched)


def _patch_config(config_file: Path) -> bool:
    """Add ``AUDIT_LOG_DURABLE`` to the Settings class body — idempotent (R5-S1-F5).

    Off by default: the audit log stays the in-memory reference unless an
    operator opts into the durable SQL-backed store. Inserted after the standard
    ``ACCESS_TOKEN_EXPIRE_MINUTES`` field when present, else appended.
    """
    src = config_file.read_text()
    if "AUDIT_LOG_DURABLE" in src:
        return False
    field = "    AUDIT_LOG_DURABLE: bool = False\n"
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + field.rstrip(), 1)
    else:
        src = src.rstrip("\n") + "\n" + field + "\n"
    config_file.write_text(src)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_audit_log_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_audit_log_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_audit_log_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
