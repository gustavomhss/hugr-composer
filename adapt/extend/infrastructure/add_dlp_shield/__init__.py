"""TOOL-108: add_dlp_shield — DLP response middleware for PII/PHI/PCI detection.

Two-tier DLP system:

* Decorator tier — ``@sensitive(level="pci")`` marks an endpoint's response
  as requiring redaction at a declared sensitivity level.
* Detection tier — regex scanning over outgoing JSON for Luhn card numbers,
  SSNs, email addresses, IBANs, and custom patterns.

Redaction modes: ``full`` (replace with ``***``), ``partial`` (last-4 only),
``tokenize`` (stable opaque token), ``remove`` (delete the field).

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``class DLPMiddleware`` in
``app/middleware/dlp_shield.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_dlp_shield",
    "description": (
        "Add DLP (Data Loss Prevention) response middleware with regex PII/PHI/PCI detection, "
        "decorator-based sensitivity tagging, and configurable redaction modes."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_dlp_shield",
}


def add_dlp_shield(inp: ToolInput) -> ToolResult:
    """Add DLP shield middleware to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first."],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    middleware_file = app_dir / "middleware" / "dlp_shield.py"

    if middleware_file.exists() and "class DLPMiddleware" in middleware_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DLP shield already installed — skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install DLP shield middleware."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    patterns_file = app_dir / "core" / "dlp" / "patterns.py"
    render_to(_HERE, "dlp_patterns.py.tmpl", dest=patterns_file, substitutions={})
    files_created.append(str(patterns_file))

    redactor_file = app_dir / "core" / "dlp" / "redactor.py"
    render_to(_HERE, "dlp_redactor.py.tmpl", dest=redactor_file, substitutions={})
    files_created.append(str(redactor_file))

    decorator_file = app_dir / "core" / "dlp" / "decorator.py"
    render_to(_HERE, "dlp_decorator.py.tmpl", dest=decorator_file, substitutions={})
    files_created.append(str(decorator_file))

    render_to(_HERE, "dlp_middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "DLPMiddleware installed with Luhn, SSN, email, IBAN, phone regex detection.",
            "Use @sensitive(level='pci') on route functions to tag responses.",
            "Redaction modes: full, partial, tokenize, remove.",
            "Per-role bypass: set DLP_BYPASS_ROLES in config.",
            "Set DLP_ENABLED=true to activate (defaults to enabled).",
            "⚠ DLPMiddleware IS NOT auto-wired into app/main.py — you must call "
            "app.add_middleware(DLPMiddleware) yourself for redaction to apply.",
            "⚠ Regex catalogue is sample-only — it covers Visa/MC/Amex/Discover, US SSN, "
            "emails, IBANs, and US/E.164 phones. It does NOT cover passport numbers, "
            "driver's licences, custom internal IDs, or non-US PII formats.",
            "⚠ DLP_BYPASS_ROLES is declared in config but NOT consumed by the emitted "
            "middleware — role-based bypass is advisory only until you wire it.",
        ],
        next_steps=[
            "Set DLP_ENABLED=true in your .env file.",
            "Set DLP_REDACTION_MODE=full|partial|tokenize|remove in .env.",
            "Add app.add_middleware(DLPMiddleware) in app/main.py.",
            "Apply @sensitive(level='pci') to routes returning card data.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject DLP_* fields inside the Settings class body."""
    src = config_file.read_text()
    if "DLP_ENABLED" in src:
        return
    fields = (
        "    DLP_ENABLED: bool = True\n"
        '    DLP_REDACTION_MODE: str = "full"\n'
        "    DLP_SENSITIVE_PATTERNS: list[str] = []\n"
        "    DLP_BYPASS_ROLES: list[str] = []\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        target = "settings = Settings()"
        if target in src:
            src = src.replace(target, fields + "\n" + target)
        else:
            src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_dlp_shield_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_dlp_shield_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
