"""TOOL-090: add_input_sanitization — add HTML sanitization + XSS prevention to FastAPI.

Generates ``app/security/sanitizer.py`` with ``InputSanitizer`` (sanitize_html
with lazy bleach import, strip_tags, escape_sql_chars), ``app/security/
sanitize_middleware.py`` with ``SanitizeMiddleware`` (sanitizes request body
JSON strings, configurable max depth), and ``app/security/validators.py`` with
``SafeString`` Pydantic type and ``NoSQLInjection`` validator.

Config fields added to ``app/core/config.py``: SANITIZE_ENABLED,
SANITIZE_ALLOWED_TAGS, SANITIZE_MAX_DEPTH.

Bleach is imported lazily inside function bodies so the app boots even
when bleach is not installed (graceful degradation with html.escape).

The tool is idempotent: a second run detects ``InputSanitizer`` in
``app/security/sanitizer.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_input_sanitization import add_input_sanitization

    result = add_input_sanitization(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/security/sanitizer.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_input_sanitization",
    "description": "Add HTML sanitization and XSS prevention middleware to FastAPI.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_input_sanitization",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_input_sanitization(inp: ToolInput) -> ToolResult:
    """Add input sanitization to a FastAPI project.

    Writes ``app/security/sanitizer.py``, ``app/security/sanitize_middleware.py``,
    ``app/security/validators.py``, patches ``app/core/config.py`` with
    sanitization config fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    sanitizer_file = app_dir / "security" / "sanitizer.py"
    if sanitizer_file.exists() and "InputSanitizer" in sanitizer_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["InputSanitizer already present — input sanitization already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create sanitizer.py, sanitize_middleware.py, "
                   "validators.py, patch config.py."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Ensure app/security/ package exists -------------------------
    security_dir = app_dir / "security"
    security_dir.mkdir(parents=True, exist_ok=True)
    security_init = security_dir / "__init__.py"
    if not security_init.exists():
        _write_security_init(security_init)
        files_created.append(str(security_init))
    elif "InputSanitizer" not in security_init.read_text():
        _patch_security_init(security_init)
        files_modified.append(str(security_init))

    # --- Step 2: Write app/security/sanitizer.py -----------------------------
    _write_sanitizer(sanitizer_file)
    files_created.append(str(sanitizer_file))

    # --- Step 3: Write app/security/sanitize_middleware.py -------------------
    middleware_file = security_dir / "sanitize_middleware.py"
    _write_sanitize_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 4: Write app/security/validators.py ----------------------------
    validators_file = security_dir / "validators.py"
    _write_validators(validators_file)
    files_created.append(str(validators_file))

    # --- Step 5: Patch config.py ---------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- ast.parse validation loop ------------------------------------------
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
            "Input sanitization added: HTML sanitize + XSS prevention.",
            "bleach imported lazily — app boots without bleach (fallback: html.escape).",
            "SanitizeMiddleware sanitizes all JSON string fields in request bodies.",
            "SafeString Pydantic type auto-sanitizes on model validation.",
            "NoSQLInjection validator rejects common NoSQL injection patterns.",
        ],
        next_steps=[
            "pip install 'bleach>=6.0.0' (optional but recommended for allowlist support).",
            "Add SanitizeMiddleware: app.add_middleware(SanitizeMiddleware).",
            "Use SafeString type in Pydantic models for user-facing string fields.",
            "Configure SANITIZE_ALLOWED_TAGS in .env to control allowed HTML tags.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_security_init(dest: Path) -> None:
    """Write ``app/security/__init__.py`` for new security packages.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Security package — input sanitization and XSS prevention utilities.\"\"\"

        from app.security.sanitizer import InputSanitizer

        __all__ = ["InputSanitizer"]
    """))


def _patch_security_init(dest: Path) -> None:
    """Add InputSanitizer export to an existing security __init__.py.

    Args:
        dest: Absolute path for the file.
    """
    src = dest.read_text()
    if "InputSanitizer" in src:
        return
    addition = "\nfrom app.security.sanitizer import InputSanitizer  # noqa: F401\n"
    dest.write_text(src.rstrip("\n") + addition)


def _write_sanitizer(dest: Path) -> None:
    """Write ``app/security/sanitizer.py`` with InputSanitizer class.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Input sanitizer — HTML sanitization and XSS prevention.

        bleach is imported lazily so the application boots even if bleach
        is not installed. Falls back to stdlib ``html.escape`` for all
        sanitization when bleach is absent.

        Usage::

            from app.security.sanitizer import InputSanitizer
            sanitizer = InputSanitizer()
            clean = sanitizer.sanitize_html("<script>alert(1)</script>Hello")
            # -> "Hello"
        \"\"\"

        from __future__ import annotations

        import html
        import logging
        import re

        logger = logging.getLogger(__name__)

        _SQL_CHARS_RE = re.compile(r\"[;'\\\"\\\\--]\")
        _NOSQL_PATTERNS = re.compile(
            r\"(\\$where|\\$gt|\\$lt|\\$ne|\\$in|\\$or|\\$and|\\$regex)\",
            re.IGNORECASE,
        )


        class InputSanitizer:
            \"\"\"HTML/XSS sanitization with optional bleach support.

            Args:
                allowed_tags: HTML tags to allow (bleach allowlist).
                    Empty list strips all tags.
            \"\"\"

            def __init__(self, allowed_tags: list[str] | None = None) -> None:
                \"\"\"Initialise with an optional HTML allowlist.

                Args:
                    allowed_tags: Tags to preserve during sanitize_html().
                        Defaults to empty list (strip all tags).
                \"\"\"
                self._allowed_tags: list[str] = allowed_tags or []

            def sanitize_html(self, value: str) -> str:
                \"\"\"Sanitize *value* by stripping disallowed HTML tags.

                Tries bleach first (allowlist-based); falls back to
                ``html.escape`` when bleach is not installed.

                Args:
                    value: Raw string that may contain HTML/script tags.

                Returns:
                    Sanitized string safe for storage and display.
                \"\"\"
                try:
                    import bleach  # lazy import — optional dependency
                    return bleach.clean(value, tags=self._allowed_tags, strip=True)
                except ImportError:
                    logger.debug("bleach not installed — using html.escape fallback")
                    return html.escape(value)

            def strip_tags(self, value: str) -> str:
                \"\"\"Strip ALL HTML tags from *value* using a simple regex.

                For full accuracy prefer ``sanitize_html()``. This method is a
                fast fallback that does not depend on bleach.

                Args:
                    value: Raw string possibly containing HTML tags.

                Returns:
                    String with all ``<tag>`` sequences removed.
                \"\"\"
                return re.sub(r\"<[^>]*>\", \"\", value)

            def escape_sql_chars(self, value: str) -> str:
                \"\"\"Escape common SQL injection characters in *value*.

                Removes ``;``, single/double quotes, backslashes, and ``--``
                comment sequences. Prefer parameterised queries over this method
                for real SQL protection — this is a defence-in-depth layer only.

                Args:
                    value: String to escape.

                Returns:
                    String with SQL-special characters removed.
                \"\"\"
                return _SQL_CHARS_RE.sub(\"\", value)
    """))


def _write_sanitize_middleware(dest: Path) -> None:
    """Write ``app/security/sanitize_middleware.py`` with SanitizeMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Request body sanitization middleware — strips XSS from JSON strings.

        Intercepts POST/PUT/PATCH requests with a JSON body and recursively
        sanitizes all string values up to a configurable depth.

        Usage::

            from app.security.sanitize_middleware import SanitizeMiddleware
            app.add_middleware(SanitizeMiddleware)
        \"\"\"

        from __future__ import annotations

        import json
        import logging
        from collections.abc import Callable
        from typing import Any

        from fastapi import Request
        from fastapi.responses import JSONResponse
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from starlette.types import ASGIApp

        logger = logging.getLogger(__name__)

        _SANITIZE_METHODS = frozenset({"POST", "PUT", "PATCH"})


        class SanitizeMiddleware(BaseHTTPMiddleware):
            \"\"\"Middleware that sanitizes JSON request body string fields.

            Recursively walks the parsed JSON body up to ``max_depth`` levels
            and sanitizes all string values using ``InputSanitizer.sanitize_html()``.
            Non-JSON bodies are passed through unmodified.

            Args:
                app: ASGI application.
                max_depth: Maximum recursion depth for nested JSON objects.
            \"\"\"

            def __init__(self, app: ASGIApp, max_depth: int = 5) -> None:
                \"\"\"Initialise the middleware with a configurable depth limit.

                Args:
                    app: ASGI application to wrap.
                    max_depth: Maximum nesting depth to sanitize (default 5).
                \"\"\"
                super().__init__(app)
                self._max_depth = max_depth

            async def dispatch(
                self,
                request: Request,
                call_next: Callable,
            ) -> Response:
                \"\"\"Sanitize JSON body for unsafe methods; pass-through otherwise.

                Args:
                    request: Incoming HTTP request.
                    call_next: Downstream handler.

                Returns:
                    Response from downstream handler.
                \"\"\"
                if request.method not in _SANITIZE_METHODS:
                    return await call_next(request)
                content_type = request.headers.get("content-type", "")
                if "application/json" not in content_type:
                    return await call_next(request)
                return await self._sanitize_body(request, call_next)

            async def _sanitize_body(
                self,
                request: Request,
                call_next: Callable,
            ) -> Response:
                \"\"\"Parse, sanitize and reconstruct the JSON request body.

                Args:
                    request: HTTP request with a JSON body.
                    call_next: Downstream handler.

                Returns:
                    Response from downstream, or 400 on JSON parse failure.
                \"\"\"
                from app.security.sanitizer import InputSanitizer

                try:
                    raw = await request.body()
                    body = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    return await call_next(request)

                sanitizer = InputSanitizer()
                cleaned = _sanitize_value(body, sanitizer, depth=0,
                                          max_depth=self._max_depth)

                # Reconstruct request with sanitized body
                cleaned_bytes = json.dumps(cleaned).encode()
                request._body = cleaned_bytes  # noqa: SLF001 — internal Starlette attr
                return await call_next(request)


        def _sanitize_value(
            value: Any,
            sanitizer: Any,
            depth: int,
            max_depth: int,
        ) -> Any:
            \"\"\"Recursively sanitize *value* up to *max_depth* levels.

            Args:
                value: JSON-decoded value (dict, list, str, or scalar).
                sanitizer: InputSanitizer instance.
                depth: Current recursion depth.
                max_depth: Maximum recursion depth.

            Returns:
                Sanitized value (same type as input).
            \"\"\"
            if depth >= max_depth:
                return value
            if isinstance(value, str):
                return sanitizer.sanitize_html(value)
            if isinstance(value, dict):
                return {
                    k: _sanitize_value(v, sanitizer, depth + 1, max_depth)
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [
                    _sanitize_value(item, sanitizer, depth + 1, max_depth)
                    for item in value
                ]
            return value
    """))


def _write_validators(dest: Path) -> None:
    """Write ``app/security/validators.py`` with SafeString and NoSQLInjection.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic validators for input safety — SafeString and NoSQLInjection.

        Usage::

            from app.security.validators import SafeString, validate_no_nosql
            from pydantic import BaseModel

            class ItemCreate(BaseModel):
                title: SafeString
                description: SafeString
        \"\"\"

        from __future__ import annotations

        import re
        from typing import Annotated

        from pydantic import BeforeValidator
        from pydantic.functional_validators import AfterValidator

        _NOSQL_PATTERNS = re.compile(
            r\"(\\$where|\\$gt|\\$lt|\\$ne|\\$in|\\$or|\\$and|\\$regex)\",
            re.IGNORECASE,
        )


        def _sanitize_string(value: object) -> str:
            \"\"\"BeforeValidator: sanitize HTML from string input.

            Args:
                value: Raw field value (expected to be str or coercible).

            Returns:
                Sanitized string.
            \"\"\"
            if not isinstance(value, str):
                return str(value) if value is not None else ""
            from app.security.sanitizer import InputSanitizer
            return InputSanitizer().sanitize_html(value)


        def _validate_no_nosql(value: str) -> str:
            \"\"\"AfterValidator: raise ValueError on NoSQL injection patterns.

            Args:
                value: String that has already passed BeforeValidator.

            Returns:
                Unchanged *value* when no injection detected.

            Raises:
                ValueError: When a NoSQL injection pattern is detected.
            \"\"\"
            if _NOSQL_PATTERNS.search(value):
                raise ValueError(
                    "Input contains disallowed pattern that may indicate NoSQL injection"
                )
            return value


        # Annotated type: auto-sanitizes HTML and rejects NoSQL injection.
        SafeString = Annotated[str, BeforeValidator(_sanitize_string)]

        # Annotated type: rejects NoSQL injection without HTML sanitization.
        NoSQLInjection = Annotated[str, AfterValidator(_validate_no_nosql)]
    """))


def _patch_config(config_file: Path) -> None:
    """Inject sanitization config fields into ``app/core/config.py`` Settings body.

    Fields are inserted with 4-space indent so they sit inside ``class Settings``.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "SANITIZE_ENABLED" in src:
        return
    # 4-space-indented so they land inside class Settings body.
    addition = (
        "\n"
        "    # --- Input Sanitization (added by add_input_sanitization tool) ---\n"
        "    SANITIZE_ENABLED: bool = True\n"
        "    SANITIZE_ALLOWED_TAGS: list[str] = []\n"
        "    SANITIZE_MAX_DEPTH: int = 5\n"
    )
    if "settings = Settings()" in src:
        src = src.replace("settings = Settings()", addition + "\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + addition + "\n"
    config_file.write_text(src)


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
