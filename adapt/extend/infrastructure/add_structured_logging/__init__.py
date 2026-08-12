"""TOOL-087: add_structured_logging — structlog JSON logging with correlation + redaction.

Migrated to per-tool directory + externalized templates (WP-02a).

Upgrades the project's logging to structlog with JSON renderer, correlation ID
binding per request, log-level configuration from settings, and a Redactor that
strips emails, phone numbers, credit card numbers, and API keys from log output.

The tool is idempotent: a second run detects ``app/logging/setup.py`` and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_structured_logging import add_structured_logging

    result = add_structured_logging(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_observability_add_structured_logging",
    "description": (
        "Upgrade to structlog with JSON renderer, correlation ID binding, "
        "per-request context, and PII redaction for emails, phones, cards, API keys."
    ),
    "tags": ["extend", "infrastructure", "observability"],
    "entry": "add_structured_logging",
    "imports_primitives": [],
    "imports_adapters": [],

}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_structured_logging(inp: ToolInput) -> ToolResult:
    """Add structlog structured logging to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    project = Path(inp.project_dir)

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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first with fastapi_generate_project(...).",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    setup_file = app_dir / "logging" / "setup.py"
    if setup_file.exists() and "configure_structlog" in setup_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["configure_structlog already present — structured logging already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/logging/ package (setup, redactor, context) "
                "and patch config + main."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: logging package via externalized templates -----------------
    logging_dir = app_dir / "logging"
    logging_dir.mkdir(parents=True, exist_ok=True)

    init_file = logging_dir / "__init__.py"
    render_to(_HERE, "logging_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    render_to(_HERE, "logging_setup.py.tmpl", dest=setup_file, substitutions={})
    files_created.append(str(setup_file))

    redactor_file = logging_dir / "redactor.py"
    render_to(_HERE, "logging_redactor.py.tmpl", dest=redactor_file, substitutions={})
    files_created.append(str(redactor_file))

    context_file = logging_dir / "context.py"
    render_to(_HERE, "logging_context.py.tmpl", dest=context_file, substitutions={})
    files_created.append(str(context_file))

    # --- Step 2: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 3: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 4: emit project test (P1 #15) ---------------------------------
    _emit_project_test(project, files_created)

    # --- Step 5: ast.parse validation ----------------------------------------
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
            "structlog configured with JSON renderer and correlation ID binding.",
            "Redactor strips: email, phone (E.164), credit card (PAN), API key patterns.",
            "LOG_FORMAT=console gives human-readable output in local dev.",
            "LOG_REDACTION_ENABLED=false disables PII redaction (not for production).",
        ],
        next_steps=[
            "Set LOG_LEVEL=INFO, LOG_FORMAT=json, LOG_REDACTION_ENABLED=true in .env.",
            "Use 'import structlog; log = structlog.get_logger()' in any module.",
            "Call bind_context(request_id=...) in middleware to enrich all log entries.",
            "structlog is already in requirements.txt — no additional pip install needed.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# In-place patchers (kept inline — small, surgical edits to existing files)
# ---------------------------------------------------------------------------


def _patch_config(config_file: Path) -> None:
    """Inject LOG_* fields into ``class Settings`` in config.py."""
    src = config_file.read_text()
    if "LOG_LEVEL" in src:
        return

    new_fields = (
        "\n"
        "    # Structured logging — added by add_structured_logging tool\n"
        '    LOG_LEVEL: str = "INFO"\n'
        '    LOG_FORMAT: str = "json"\n'
        "    LOG_REDACTION_ENABLED: bool = True\n"
    )
    anchor = '    REDIS_URL: str = "redis://localhost:6379/0"'
    if anchor in src:
        src = src.replace(anchor, anchor + new_fields)
    else:
        for decorator in ("    @computed_field", "    @model_validator", "    @property"):
            if decorator in src:
                first_pos = src.index(decorator)
                src = src[:first_pos] + new_fields + "\n" + src[first_pos:]
                break
        else:
            marker = "settings = Settings()"
            if marker in src:
                src = src.replace(marker, new_fields + "\n" + marker)
            else:
                src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Inject ``configure_structlog()`` call into ``app/main.py``.

    The call is spliced INSIDE ``async def lifespan(...)`` (before the
    ``yield``) — mirrors ``add_arq_worker`` / ``add_bulk_operations``.
    Closes CONTRACT §B0.15 (P6-adjacent — ``_configure_structlog`` is
    not the literal ``configure_logging`` name the spec allowlists, so
    it lands here for shape consistency with the rest of the lifespan
    cluster).

    Trade-off: structlog's bind/contextvars processors are *registry*
    state, NOT import-time state — the global structlog config is
    rewritten on every ``configure_structlog`` call (see
    ``structlog.configure(...)`` semantics). Moving the call from
    module-import to lifespan-startup means log records emitted DURING
    import (a handful of module-level ``logger.info`` calls in scaffold
    code) use stdlib-logging defaults instead of the JSON renderer.
    That's the documented cost of lifespan-gating; the request path is
    unaffected because lifespan-startup completes before the first
    request handler runs.

    When ``async def lifespan(...)`` is NOT present in the host
    ``main.py`` (non-standard shape), the patcher falls back to a
    module-top ``_configure_structlog(...)`` call carrying
    ``# pragma: B0.15: ...`` so the contract rule still allows the
    literal line.
    """
    src = main_file.read_text()
    if "configure_structlog" in src:
        return

    logging_import = (
        "\nfrom app.logging.setup import configure_structlog as _configure_structlog"
        "  # noqa: F401 — logging layer\n"
        "import os as _log_os\n"
    )
    configure_snippet = render(_HERE, "main_configure_snippet.txt.tmpl", {})

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + logging_import,
        )
    else:
        src = logging_import + src

    # Append the (now doc-only) snippet so a downstream reader sees
    # the rationale next to the lifespan-spliced call.
    src = src.rstrip("\n") + "\n" + configure_snippet

    # Splice `_configure_structlog(...)` INSIDE `async def lifespan(...)`
    # before the `yield` — CONTRACT §B0.15.
    lines = src.splitlines()
    yield_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1
    )
    if yield_idx != -1:
        raw = lines[yield_idx]
        indent = raw[: len(raw) - len(raw.lstrip())]
        startup_lines = [
            f"{indent}# --- add_structured_logging: configure structlog (B0.15) ---",
            f"{indent}_configure_structlog(",
            f'{indent}    level=_log_os.getenv("LOG_LEVEL", "INFO"),',
            f'{indent}    fmt=_log_os.getenv("LOG_FORMAT", "json"),',
            f"{indent}    redaction_enabled="
            f'_log_os.getenv("LOG_REDACTION_ENABLED", "true").lower() != "false",',
            f"{indent})",
        ]
        for offset, ln in enumerate(startup_lines):
            lines.insert(yield_idx + offset, ln)
        main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    else:
        # Fallback for non-standard main.py shapes — module-top call
        # carrying the per-line B0.15 pragma. NOTE: the rule keys the
        # pragma lookup off the Call's start line (ast.Call.lineno),
        # so the pragma MUST live on the `_configure_structlog(` line
        # — a single-line call form is the cleanest way to guarantee
        # that. We collapse the kwargs onto one long line; ruff/E501
        # is a project-side concern in the host scaffold, not ours.
        fallback = (
            "\n"
            "# Structured logging — no `async def lifespan(...)` found in "
            "this main.py; fallback retains legacy module-top configure.\n"
            "_configure_structlog("
            'level=_log_os.getenv("LOG_LEVEL", "INFO"), '
            'fmt=_log_os.getenv("LOG_FORMAT", "json"), '
            "redaction_enabled="
            '_log_os.getenv("LOG_REDACTION_ENABLED", "true").lower() != "false"'
            ")"
            "  # pragma: B0.15: non-standard main.py has no `lifespan`; "
            "fallback retains legacy module-top configure\n"
        )
        main_file.write_text(src.rstrip("\n") + fallback)


# ---------------------------------------------------------------------------
# Emitted test (P1 #15)
# ---------------------------------------------------------------------------


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_structured_logging_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_structured_logging_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


