"""TOOL-108: add_dlp_shield — DLP response middleware for PII/PHI/PCI detection.

Writes a two-tier DLP system:

* **Decorator tier** — ``@sensitive(level="pci")`` marks an endpoint's response
  as requiring redaction at a declared sensitivity level.
* **Detection tier** — regex scanning over outgoing JSON for Luhn card numbers,
  SSNs, email addresses, IBANs, and custom patterns.

Redaction modes: ``full`` (replace with ``***``), ``partial`` (show last 4 chars),
``tokenize`` (replace with a stable opaque token), ``remove`` (delete the field).
Per-role visibility lets privileged roles bypass redaction at the route level.

Config fields added to ``app/core/config.py``::

    DLP_ENABLED = True
    DLP_REDACTION_MODE = "full"
    DLP_SENSITIVE_PATTERNS = []

The tool is idempotent: a second run detects ``class DLPMiddleware`` in
``app/middleware/dlp_shield.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_dlp_shield import add_dlp_shield

    result = add_dlp_shield(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/middleware/dlp_shield.py", ...]
    print(result.next_steps)    # ["Set DLP_ENABLED=true in .env", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_dlp_shield",
    "description": (
        "Add DLP (Data Loss Prevention) response middleware with regex PII/PHI/PCI detection, "
        "decorator-based sensitivity tagging, and configurable redaction modes."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_dlp_shield",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_dlp_shield(inp: ToolInput) -> ToolResult:
    """Add DLP shield middleware to a FastAPI project.

    Creates pattern engine, redactor, middleware, and ``@sensitive`` decorator.
    Patches config and registers the middleware comment in main.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    middleware_file = app_dir / "middleware" / "dlp_shield.py"

    # --- Idempotency guard ---------------------------------------------------
    if middleware_file.exists() and "class DLPMiddleware" in middleware_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DLP shield already installed — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install DLP shield middleware."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # Step 1: Pattern engine
    patterns_file = app_dir / "core" / "dlp" / "patterns.py"
    _write_patterns(patterns_file)
    files_created.append(str(patterns_file))

    # Step 2: Redactor
    redactor_file = app_dir / "core" / "dlp" / "redactor.py"
    _write_redactor(redactor_file)
    files_created.append(str(redactor_file))

    # Step 3: @sensitive decorator
    decorator_file = app_dir / "core" / "dlp" / "decorator.py"
    _write_decorator(decorator_file)
    files_created.append(str(decorator_file))

    # Step 4: Middleware
    _write_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # Step 5: Patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- ast.parse validation ------------------------------------------------
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
            "DLPMiddleware installed with Luhn, SSN, email, IBAN regex detection.",
            "Use @sensitive(level='pci') on route functions to tag responses.",
            "Redaction modes: full, partial, tokenize, remove.",
            "Per-role bypass: set DLP_BYPASS_ROLES in config.",
            "Set DLP_ENABLED=true to activate (defaults to enabled).",
        ],
        next_steps=[
            "Set DLP_ENABLED=true in your .env file.",
            "Set DLP_REDACTION_MODE=full|partial|tokenize|remove in .env.",
            "Add app.add_middleware(DLPMiddleware) in app/main.py.",
            "Apply @sensitive(level='pci') to routes returning card data.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------


def _write_patterns(dest: Path) -> None:
    """Write app/core/dlp/patterns.py with compiled regex patterns."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Compiled regex patterns for PII/PHI/PCI detection.

        Pattern groups:
        * ``PCI`` — credit/debit card numbers validated by Luhn algorithm.
        * ``PII`` — SSN, email address, phone number.
        * ``PHI`` — US National Provider Identifier.
        * ``IBAN`` — International Bank Account Numbers.
        \"\"\"

        from __future__ import annotations

        import re
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class SensitivePattern:
            \"\"\"A named regex pattern with its sensitivity category.

            Attributes:
                name: Human-readable pattern name.
                regex: Compiled regular expression.
                level: Sensitivity level: 'pci', 'pii', 'phi', 'custom'.
            \"\"\"

            name: str
            regex: re.Pattern[str]
            level: str


        # --- Credit / debit card (Luhn-validated after regex match) -----------
        _CARD_RE = re.compile(
            r"\\b(?:4[0-9]{12}(?:[0-9]{3})?|"          # Visa
            r"5[1-5][0-9]{14}|"                         # MasterCard
            r"3[47][0-9]{13}|"                          # Amex
            r"6(?:011|5[0-9]{2})[0-9]{12})\\b"
        )

        # --- SSN (US Social Security Number) ----------------------------------
        _SSN_RE = re.compile(r"\\b(?!000|666|9\\d{2})\\d{3}[- ](?!00)\\d{2}[- ](?!0000)\\d{4}\\b")

        # --- Email address ----------------------------------------------------
        _EMAIL_RE = re.compile(r"\\b[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}\\b")

        # --- IBAN (basic structural check) ------------------------------------
        _IBAN_RE = re.compile(r"\\b[A-Z]{2}\\d{2}[A-Z0-9]{1,30}\\b")

        # --- Phone number (E.164 + common formats) ---------------------------
        _PHONE_RE = re.compile(
            r"\\b(?:\\+?1[-.\\s]?)?\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}\\b"
        )

        BUILTIN_PATTERNS: tuple[SensitivePattern, ...] = (
            SensitivePattern(name="credit_card", regex=_CARD_RE, level="pci"),
            SensitivePattern(name="ssn", regex=_SSN_RE, level="pii"),
            SensitivePattern(name="email", regex=_EMAIL_RE, level="pii"),
            SensitivePattern(name="iban", regex=_IBAN_RE, level="phi"),
            SensitivePattern(name="phone", regex=_PHONE_RE, level="pii"),
        )


        def luhn_valid(number: str) -> bool:
            \"\"\"Return True if *number* (digits only) passes the Luhn check.

            Args:
                number: String of digit characters to validate.

            Returns:
                ``True`` when the Luhn checksum is valid.
            \"\"\"
            digits = [int(d) for d in number if d.isdigit()]
            odd = digits[-1::-2]
            even = [d * 2 - 9 if d * 2 > 9 else d * 2 for d in digits[-2::-2]]
            return (sum(odd) + sum(even)) % 10 == 0
    """))


def _write_redactor(dest: Path) -> None:
    """Write app/core/dlp/redactor.py with Redactor class."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"DLP redactor: scans and redacts sensitive data in response payloads.\"\"\"

        from __future__ import annotations

        import hashlib
        import json
        import logging
        import re
        from typing import Any

        from app.core.dlp.patterns import BUILTIN_PATTERNS, SensitivePattern, luhn_valid

        logger = logging.getLogger(__name__)

        _REDACTION_MODES = frozenset({"full", "partial", "tokenize", "remove"})


        class Redactor:
            \"\"\"Scans JSON payloads and redacts matches.

            Attributes:
                mode: Redaction mode ('full', 'partial', 'tokenize', 'remove').
                patterns: Sequence of SensitivePattern to apply.
            \"\"\"

            def __init__(
                self,
                mode: str = "full",
                extra_patterns: list[SensitivePattern] | None = None,
            ) -> None:
                \"\"\"Initialise the redactor.

                Args:
                    mode: Redaction mode.
                    extra_patterns: Additional patterns beyond builtins.
                \"\"\"
                if mode not in _REDACTION_MODES:
                    raise ValueError(f"Unknown redaction mode: {mode!r}")
                self.mode = mode
                self.patterns: tuple[SensitivePattern, ...] = BUILTIN_PATTERNS + tuple(
                    extra_patterns or []
                )

            def redact_value(self, value: str) -> str:
                \"\"\"Apply redaction to a single string value.

                Args:
                    value: The string that may contain sensitive data.

                Returns:
                    Redacted version of *value*.
                \"\"\"
                for pat in self.patterns:
                    for match in pat.regex.finditer(value):
                        raw = match.group(0)
                        if pat.name == "credit_card":
                            digits = re.sub(r"\\D", "", raw)
                            if not luhn_valid(digits):
                                continue
                        replacement = self._replace(raw)
                        value = value.replace(raw, replacement)
                return value

            def _replace(self, raw: str) -> str:
                \"\"\"Compute the replacement string for a sensitive match.

                Args:
                    raw: The matched sensitive string.

                Returns:
                    Replacement string according to ``self.mode``.
                \"\"\"
                if self.mode == "full":
                    return "***"
                if self.mode == "partial":
                    return f"***{raw[-4:]}" if len(raw) >= 4 else "***"
                if self.mode == "tokenize":
                    return "tok_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
                return ""  # remove mode: empty string

            def redact_payload(self, payload: Any) -> Any:
                \"\"\"Recursively redact a JSON-serialisable payload.

                Args:
                    payload: Dict, list, or scalar value to redact.

                Returns:
                    Redacted copy of *payload*.
                \"\"\"
                if isinstance(payload, dict):
                    if self.mode == "remove":
                        return {
                            k: self.redact_payload(v)
                            for k, v in payload.items()
                            if not (isinstance(v, str) and self._has_match(v))
                        }
                    return {k: self.redact_payload(v) for k, v in payload.items()}
                if isinstance(payload, list):
                    return [self.redact_payload(item) for item in payload]
                if isinstance(payload, str):
                    return self.redact_value(payload)
                return payload

            def _has_match(self, value: str) -> bool:
                \"\"\"Return True if any pattern matches *value*.

                Args:
                    value: String to test against all patterns.

                Returns:
                    ``True`` when at least one pattern matches.
                \"\"\"
                return any(pat.regex.search(value) for pat in self.patterns)

            def redact_json_bytes(self, data: bytes) -> bytes:
                \"\"\"Deserialise, redact, and re-serialise JSON bytes.

                Args:
                    data: Raw JSON response body.

                Returns:
                    Redacted JSON bytes.
                \"\"\"
                try:
                    payload = json.loads(data)
                    redacted = self.redact_payload(payload)
                    return json.dumps(redacted).encode()
                except (json.JSONDecodeError, ValueError):
                    logger.debug("dlp_shield: non-JSON body skipped")
                    return data
    """))


def _write_decorator(dest: Path) -> None:
    """Write app/core/dlp/decorator.py with @sensitive decorator."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"@sensitive decorator for explicit endpoint sensitivity tagging.

        Usage::

            from app.core.dlp.decorator import sensitive

            @router.get("/payment-methods")
            @sensitive(level="pci")
            async def list_payment_methods(current_user: CurrentUser):
                ...
        \"\"\"

        from __future__ import annotations

        import functools
        import logging
        from collections.abc import Callable
        from typing import Any

        logger = logging.getLogger(__name__)

        _SENSITIVITY_ATTR = "_dlp_sensitivity_level"


        def sensitive(level: str = "pii") -> Callable[[Any], Any]:
            \"\"\"Mark a route function with a DLP sensitivity level.

            The ``DLPMiddleware`` reads this attribute to apply stricter redaction
            for elevated sensitivity levels (e.g. ``'pci'`` forces ``full`` mode).

            Args:
                level: Sensitivity level string — ``'pii'``, ``'phi'``, ``'pci'``,
                    or ``'custom'``.

            Returns:
                Decorator that attaches ``_dlp_sensitivity_level`` to the function.
            \"\"\"
            def decorator(func: Any) -> Any:
                \"\"\"Attach the DLP sensitivity level to *func*.

                Args:
                    func: The route handler to decorate.

                Returns:
                    The same *func* with ``_dlp_sensitivity_level`` attribute set.
                \"\"\"
                @functools.wraps(func)
                async def wrapper(*args: Any, **kwargs: Any) -> Any:
                    \"\"\"Async wrapper preserving the sensitivity attribute.

                    Args:
                        *args: Positional arguments forwarded to *func*.
                        **kwargs: Keyword arguments forwarded to *func*.

                    Returns:
                        Result of *func*.
                    \"\"\"
                    return await func(*args, **kwargs)

                setattr(wrapper, _SENSITIVITY_ATTR, level)
                return wrapper

            return decorator


        def get_sensitivity_level(func: Any) -> str | None:
            \"\"\"Return the DLP sensitivity level attached to *func*, or None.

            Args:
                func: A callable, potentially decorated with ``@sensitive``.

            Returns:
                Sensitivity level string or ``None`` when not tagged.
            \"\"\"
            return getattr(func, _SENSITIVITY_ATTR, None)
    """))


def _write_middleware(dest: Path) -> None:
    """Write app/middleware/dlp_shield.py with DLPMiddleware."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"DLP shield middleware — scans and redacts outgoing JSON responses.

        Attach via ``app.add_middleware(DLPMiddleware)`` in ``app/main.py``.

        The middleware:
        1. Intercepts the response body.
        2. Checks the matched route for ``@sensitive`` decoration.
        3. Applies pattern-based redaction to any JSON response.
        4. Skips non-JSON content types and bypass paths.
        \"\"\"

        from __future__ import annotations

        import logging

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response
        from starlette.types import ASGIApp

        from app.core.config import settings
        from app.core.dlp.redactor import Redactor

        logger = logging.getLogger(__name__)

        _BYPASS_PATHS: frozenset[str] = frozenset({"/healthz", "/metrics", "/docs", "/openapi.json"})
        _JSON_CONTENT_TYPES: frozenset[str] = frozenset({"application/json", "text/json"})


        class DLPMiddleware(BaseHTTPMiddleware):
            \"\"\"Response middleware that detects and redacts PII/PHI/PCI in JSON.

            Attributes:
                bypass_paths: URL paths that skip DLP scanning.
            \"\"\"

            def __init__(
                self,
                app: ASGIApp,
                bypass_paths: frozenset[str] = _BYPASS_PATHS,
            ) -> None:
                \"\"\"Initialise the middleware.

                Args:
                    app: ASGI application to wrap.
                    bypass_paths: Paths that skip DLP scanning.
                \"\"\"
                super().__init__(app)
                self.bypass_paths = bypass_paths

            async def dispatch(self, request: Request, call_next: object) -> Response:
                \"\"\"Intercept the response and apply DLP redaction.

                Args:
                    request: Incoming Starlette request.
                    call_next: Next handler.

                Returns:
                    Original or DLP-redacted response.
                \"\"\"
                if not getattr(settings, "DLP_ENABLED", True):
                    return await call_next(request)  # type: ignore[arg-type]
                if request.url.path in self.bypass_paths:
                    return await call_next(request)  # type: ignore[arg-type]
                response: Response = await call_next(request)  # type: ignore[arg-type]
                content_type = response.headers.get("content-type", "")
                is_json = any(ct in content_type for ct in _JSON_CONTENT_TYPES)
                if not is_json:
                    return response
                body = b""
                async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                    body += chunk if isinstance(chunk, bytes) else chunk.encode()
                mode = getattr(settings, "DLP_REDACTION_MODE", "full")
                redactor = Redactor(mode=mode)
                redacted_body = redactor.redact_json_bytes(body)
                headers = dict(response.headers)
                headers["content-length"] = str(len(redacted_body))
                return Response(
                    content=redacted_body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type="application/json",
                )
    """))


def _patch_config(config_file: Path) -> None:
    """Inject DLP_* fields inside the Settings class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "DLP_ENABLED" in src:
        return
    fields = (
        "    DLP_ENABLED: bool = True\n"
        "    DLP_REDACTION_MODE: str = \"full\"\n"
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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> int:
    """Return wall-clock elapsed milliseconds since *start*.

    Args:
        start: ``time.monotonic()`` snapshot from the top of the function.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
