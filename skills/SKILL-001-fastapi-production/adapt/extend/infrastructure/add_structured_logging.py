"""TOOL-087: add_structured_logging — add structlog JSON logging with correlation and redaction.

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
    print(result.files_created) # [.../app/logging/setup.py, ...]
    print(result.next_steps)    # ["Set LOG_LEVEL=INFO in .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_structured_logging",
    "description": (
        "Upgrade to structlog with JSON renderer, correlation ID binding, "
        "per-request context, and PII redaction for emails, phones, cards, API keys."
    ),
    "tags": ["extend", "infrastructure", "observability"],
    "entry": "add_structured_logging",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_structured_logging(inp: ToolInput) -> ToolResult:
    """Add structlog structured logging to a FastAPI project.

    Writes ``app/logging/`` package (setup, redactor, context), patches
    ``app/core/config.py`` with ``LOG_LEVEL`` / ``LOG_FORMAT`` /
    ``LOG_REDACTION_ENABLED`` fields, and patches ``app/main.py`` to call
    ``configure_structlog()`` at startup. No new pip deps required — structlog
    is already present in the base project's requirements.

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

    # --- Prerequisite check --------------------------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    # --- Step 1: logging package ---------------------------------------------
    logging_dir = app_dir / "logging"
    logging_dir.mkdir(parents=True, exist_ok=True)

    init_file = logging_dir / "__init__.py"
    _write_logging_init(init_file)
    files_created.append(str(init_file))

    _write_logging_setup(setup_file)
    files_created.append(str(setup_file))

    redactor_file = logging_dir / "redactor.py"
    _write_logging_redactor(redactor_file)
    files_created.append(str(redactor_file))

    context_file = logging_dir / "context.py"
    _write_logging_context(context_file)
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

    # --- Step 4: ast.parse validation ----------------------------------------
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
# File writers — each <= 50 LOC
# ---------------------------------------------------------------------------

def _write_logging_init(dest: Path) -> None:
    """Write ``app/logging/__init__.py`` re-exporting public symbols.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Structured logging layer — public API.\"\"\"

        from app.logging.context import bind_context, get_correlation_id
        from app.logging.redactor import Redactor
        from app.logging.setup import configure_structlog

        __all__ = [
            "configure_structlog",
            "Redactor",
            "get_correlation_id",
            "bind_context",
        ]
        """))


def _write_logging_setup(dest: Path) -> None:
    """Write ``app/logging/setup.py`` with configure_structlog.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"configure_structlog: JSON renderer, correlation binding, redaction.\"\"\"

        from __future__ import annotations

        import logging
        import sys
        from typing import Any

        import structlog

        from app.logging.redactor import Redactor


        def configure_structlog(
            level: str = "INFO",
            fmt: str = "json",
            redaction_enabled: bool = True,
        ) -> None:
            \"\"\"Configure structlog for the application.

            Sets up JSON (production) or console (development) renderer,
            correlation ID injection, and optional PII redaction.

            Args:
                level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                fmt: Output format — ``"json"`` or ``"console"``.
                redaction_enabled: When ``True``, apply PII redaction processor.
            \"\"\"
            processors: list[Any] = [
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
            ]
            if redaction_enabled:
                redactor = Redactor()
                processors.append(redactor)
            if fmt == "json":
                processors.append(structlog.processors.JSONRenderer())
            else:
                processors.append(structlog.dev.ConsoleRenderer())

            structlog.configure(
                processors=processors,
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )
            logging.basicConfig(
                format="%(message)s",
                stream=sys.stdout,
                level=getattr(logging, level.upper(), logging.INFO),
            )
        """))


def _write_logging_redactor(dest: Path) -> None:
    """Write ``app/logging/redactor.py`` with PII redaction processor.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Redactor: structlog processor that strips PII from log events.

        Patterns scrubbed:
        - Email addresses
        - Phone numbers (E.164 and common formats)
        - Credit card PANs (13-19 digit sequences)
        - API keys / bearer tokens (common env-var patterns)
        \"\"\"

        from __future__ import annotations

        import logging
        import re
        from typing import Any

        logger = logging.getLogger(__name__)

        _EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+")
        _PHONE_RE = re.compile(r"\\+?\\d[\\d\\s\\-().]{7,}\\d")
        _CARD_RE = re.compile(r"\\b(?:\\d[ -]?){13,19}\\b")
        _APIKEY_RE = re.compile(
            r"(?i)(api[_-]?key|token|secret|bearer)[=:\\s]+[\\w\\-\\.]{8,}"
        )


        class Redactor:
            \"\"\"Structlog processor that redacts PII patterns in log event strings.\"\"\"

            def __call__(
                self,
                logger: Any,
                method: str,
                event_dict: dict[str, Any],
            ) -> dict[str, Any]:
                \"\"\"Redact PII from all string values in *event_dict*.

                Args:
                    logger: structlog logger instance (unused).
                    method: Log method name (unused).
                    event_dict: Mutable log event dictionary.

                Returns:
                    event_dict with PII replaced by ``[REDACTED]``.
                \"\"\"
                for key, value in list(event_dict.items()):
                    if isinstance(value, str):
                        event_dict[key] = _redact_string(value)
                return event_dict


        def _redact_string(text: str) -> str:
            \"\"\"Apply all PII redaction patterns to *text*.

            Args:
                text: Input string that may contain PII.

            Returns:
                String with PII replaced by ``[REDACTED]``.
            \"\"\"
            text = _EMAIL_RE.sub("[REDACTED]", text)
            text = _PHONE_RE.sub("[REDACTED]", text)
            text = _CARD_RE.sub("[REDACTED]", text)
            text = _APIKEY_RE.sub(r"\\1=[REDACTED]", text)
            return text
        """))


def _write_logging_context(dest: Path) -> None:
    """Write ``app/logging/context.py`` with correlation ID helpers.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Correlation ID helpers for structlog context binding.

        Uses structlog's ``contextvars`` so each async request gets an isolated
        log context without thread-safety concerns.
        \"\"\"

        from __future__ import annotations

        import uuid
        from typing import Any

        import structlog


        def get_correlation_id() -> str:
            \"\"\"Return the current request's correlation ID, or a fresh UUID.

            Returns:
                Correlation ID string from structlog context vars, or a new UUID4
                when no correlation ID has been bound yet.
            \"\"\"
            ctx = structlog.contextvars.get_contextvars()
            return str(ctx.get("correlation_id") or uuid.uuid4())


        def bind_context(**kwargs: Any) -> None:
            \"\"\"Bind key-value pairs into the structlog request context.

            Bound values are included in every log entry for the current
            async task. Call this in request middleware after extracting
            headers (e.g. ``X-Request-ID``).

            Args:
                **kwargs: Key-value pairs to bind (e.g. ``request_id="abc"``).
            \"\"\"
            structlog.contextvars.bind_contextvars(**kwargs)


        def clear_context() -> None:
            \"\"\"Clear all structlog context vars (call at request teardown).\"\"\"
            structlog.contextvars.clear_contextvars()
        """))


def _patch_config(config_file: Path) -> None:
    """Inject LOG_* fields into ``class Settings`` in config.py.

    Inserts fields inside the class body using the REDIS_URL field as an
    anchor (or falls back to the first decorator inside the class).

    Args:
        config_file: Path to ``app/core/config.py``.
    """
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
    """Inject configure_structlog() call into app/main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "configure_structlog" in src:
        return

    logging_import = (
        "\nfrom app.logging.setup import configure_structlog as _configure_structlog"
        "  # noqa: F401 — logging layer\n"
        "import os as _log_os\n"
    )
    configure_snippet = textwrap.dedent("""\

        # Structured logging startup — added by add_structured_logging tool
        _configure_structlog(
            level=_log_os.getenv("LOG_LEVEL", "INFO"),
            fmt=_log_os.getenv("LOG_FORMAT", "json"),
            redaction_enabled=_log_os.getenv("LOG_REDACTION_ENABLED", "true").lower() != "false",
        )
    """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + logging_import,
        )
    else:
        src = logging_import + src

    src = src.rstrip("\n") + "\n" + configure_snippet
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
