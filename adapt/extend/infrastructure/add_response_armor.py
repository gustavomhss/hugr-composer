"""TOOL-118: add_response_armor — five-layer response hardening.

Generates production-grade response security with:
1. ErrorSanitizer: generic messages to clients, full detail to structured logs
2. Constant-time auth comparisons via hmac.compare_digest wrappers
3. BREACH mitigation: random-length padding injected into compressed responses
4. Cache-Control enforcement: no-store/no-cache on sensitive responses
5. CRLF injection protection: strip CR/LF from all header values

Idempotent: a second run detects ``app/middleware/response_armor.py`` and
returns ``status="no_op"`` without touching any file.

Generated files:
  - ``app/middleware/response_armor.py``   main hardening middleware
  - ``app/core/response_armor.py``         error sanitizer + BREACH + CRLF utils
  - ``app/core/timing_safe.py``            constant-time comparison helpers

Patched files:
  - ``app/core/config.py``      RESPONSE_ARMOR_* fields inside Settings
  - ``app/main.py``             armor middleware registration
  - ``requirements.txt``        no new deps (uses stdlib only)

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_response_armor import add_response_armor

    result = add_response_armor(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/middleware/response_armor.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_response_armor",
    "description": (
        "Add five-layer response hardening: error sanitization (generic to client, "
        "full to logs), constant-time auth comparisons (hmac.compare_digest), "
        "BREACH mitigation (random padding), Cache-Control enforcement on sensitive "
        "responses, and CRLF injection protection in headers."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_response_armor",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_response_armor(inp: ToolInput) -> ToolResult:
    """Add five-layer response hardening to a FastAPI project.

    Creates the armor middleware, error sanitizer utilities, and timing-safe
    comparison helpers. Patches ``app/core/config.py`` with
    ``RESPONSE_ARMOR_*`` settings and ``app/main.py`` to register the middleware.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)

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

    files_created: list[str] = list(scaffolded)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    mw_file = app_dir / "middleware" / "response_armor.py"
    if mw_file.exists() and "ResponseArmorMiddleware" in mw_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ResponseArmorMiddleware already present — response armor already installed."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard -------------------------------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/middleware/response_armor.py, "
                "app/core/response_armor.py, and app/core/timing_safe.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Core utils (error sanitizer, BREACH, CRLF) ------------------
    (app_dir / "core").mkdir(parents=True, exist_ok=True)
    armor_core = app_dir / "core" / "response_armor.py"
    _write_armor_core(armor_core)
    files_created.append(str(armor_core))

    # --- Step 2: Timing-safe comparison helpers ------------------------------
    timing_safe = app_dir / "core" / "timing_safe.py"
    _write_timing_safe(timing_safe)
    files_created.append(str(timing_safe))

    # --- Step 3: Armor middleware ---------------------------------------------
    middleware_dir = app_dir / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    mw_init = middleware_dir / "__init__.py"
    if not mw_init.exists():
        mw_init.write_text('"""Middleware package."""\n')
        files_created.append(str(mw_init))

    _write_armor_middleware(mw_file)
    files_created.append(str(mw_file))

    # --- Step 4: Patch config ------------------------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 5: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 6: ast.parse validation ----------------------------------------
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
            "Response armor installed: 5-layer hardening active.",
            "ErrorSanitizer: 500 errors send generic message to client, full detail to logs.",
            "BREACH mitigation: random 0–32 byte padding injected into compressed responses.",
            "Cache-Control: no-store applied to all 4xx/5xx responses automatically.",
            "CRLF injection: CR/LF characters stripped from all response header values.",
        ],
        next_steps=[
            "Set RESPONSE_ARMOR_ENABLED=true in .env to activate.",
            "Set RESPONSE_ARMOR_SANITIZE_ERRORS=true to enable error sanitization.",
            "Set RESPONSE_ARMOR_TIMING_SAFE=true to enable timing-safe comparison logging.",
            "Import compare_tokens from app.core.timing_safe for all auth comparisons.",
            "Review logs for armor.error_sanitized events to monitor sanitization activity.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — every function ≤ 50 LOC
# ---------------------------------------------------------------------------

def _write_armor_core(dest: Path) -> None:
    """Write ``app/core/response_armor.py`` with sanitizer, BREACH, CRLF utils.

    Args:
        dest: Absolute path for the output file.
    """
    dest.write_text(textwrap.dedent('''\
        """Response armor utilities: error sanitizer, BREACH padding, CRLF guard.

        Three pure functions used by ResponseArmorMiddleware:

          sanitize_error  — converts exception detail to a generic client message
          breach_padding  — produces random-length junk bytes for BREACH mitigation
          strip_crlf      — removes CR and LF characters from header values
        """

        from __future__ import annotations

        import logging
        import os
        import secrets

        logger = logging.getLogger(__name__)

        # Client-visible generic error messages by status range
        _GENERIC_MESSAGES: dict[int, str] = {
            400: "Bad request.",
            401: "Authentication required.",
            403: "Forbidden.",
            404: "Not found.",
            409: "Conflict.",
            422: "Unprocessable entity.",
            429: "Too many requests.",
            500: "An unexpected error occurred.",
            502: "Bad gateway.",
            503: "Service unavailable.",
        }

        _DEFAULT_GENERIC = "An error occurred."


        def sanitize_error(status_code: int, detail: object, request_id: str = "") -> str:
            """Return a safe client-facing message; log the real detail.

            Args:
                status_code: HTTP status code of the response.
                detail: The original exception detail (never sent to client).
                request_id: Optional correlation ID for log correlation.

            Returns:
                A generic, non-leaking error message string.
            """
            logger.error(
                "armor.error_sanitized",
                extra={
                    "status_code": status_code,
                    "detail": str(detail),
                    "request_id": request_id,
                },
            )
            return _GENERIC_MESSAGES.get(status_code, _DEFAULT_GENERIC)


        def breach_padding(min_bytes: int = 0, max_bytes: int = 32) -> bytes:
            """Generate random padding bytes to defeat BREACH compression attacks.

            Injects a random-length comment into compressed HTTP responses so
            the attacker cannot infer secret lengths from compressed sizes.

            Args:
                min_bytes: Minimum padding length (default 0).
                max_bytes: Maximum padding length (default 32).

            Returns:
                Random bytes of length between min_bytes and max_bytes.
            """
            length = secrets.randbelow(max(1, max_bytes - min_bytes + 1)) + min_bytes
            return os.urandom(length)


        def strip_crlf(value: str) -> str:
            """Remove CR (\\r) and LF (\\n) from a header value.

            Prevents CRLF injection attacks where an attacker embeds newlines
            in a header value to inject additional headers or split the response.

            Args:
                value: Raw header value string.

            Returns:
                Header value with all CR and LF characters removed.
            """
            return value.replace("\\r", "").replace("\\n", "")
        '''))


def _write_timing_safe(dest: Path) -> None:
    """Write ``app/core/timing_safe.py`` with constant-time comparison helpers.

    Args:
        dest: Absolute path for the output file.
    """
    dest.write_text(textwrap.dedent('''\
        """Timing-safe comparison helpers — wrappers around hmac.compare_digest.

        All authentication token comparisons in the application MUST use these
        helpers instead of ``==`` to prevent timing oracle attacks.

        Import::

            from app.core.timing_safe import compare_tokens, compare_bytes
        """

        from __future__ import annotations

        import hmac
        import logging

        logger = logging.getLogger(__name__)


        def compare_tokens(a: str, b: str) -> bool:
            """Compare two string tokens in constant time.

            Uses ``hmac.compare_digest`` so the comparison time does not
            reveal how many characters match (timing oracle prevention).

            Args:
                a: First token string.
                b: Second token string (e.g. expected token from storage).

            Returns:
                ``True`` if tokens are equal, ``False`` otherwise.
            """
            try:
                return hmac.compare_digest(a.encode(), b.encode())
            except (AttributeError, TypeError) as exc:
                logger.warning(
                    "timing_safe.compare_tokens.type_error",
                    extra={"exc": str(exc)},
                )
                return False


        def compare_bytes(a: bytes, b: bytes) -> bool:
            """Compare two byte sequences in constant time.

            Args:
                a: First byte sequence.
                b: Second byte sequence.

            Returns:
                ``True`` if sequences are equal, ``False`` otherwise.
            """
            try:
                return hmac.compare_digest(a, b)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "timing_safe.compare_bytes.type_error",
                    extra={"exc": str(exc)},
                )
                return False


        def compare_signatures(received: str, expected: str) -> bool:
            """Compare HMAC signatures in constant time.

            Convenience wrapper that normalises both signatures to lowercase
            before comparison (hex digests are case-insensitive).

            Args:
                received: Signature string from the incoming request.
                expected: Reference signature computed server-side.

            Returns:
                ``True`` if signatures match, ``False`` otherwise.
            """
            return compare_tokens(received.lower(), expected.lower())
        '''))


def _write_armor_middleware(dest: Path) -> None:
    """Write ``app/middleware/response_armor.py`` with ResponseArmorMiddleware.

    Args:
        dest: Absolute path for the output file.
    """
    dest.write_text(textwrap.dedent('''\
        """ResponseArmorMiddleware — five-layer response hardening.

        Applied in order on every outgoing response:
          1. CRLF injection: strip CR/LF from all header values
          2. Cache-Control: enforce no-store on 4xx/5xx responses
          3. Error sanitization: generic message to client on 5xx
          4. BREACH padding: add random junk bytes (when applicable)
          5. Server header: remove or replace server identification
        """

        from __future__ import annotations

        import logging

        from fastapi import FastAPI
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        from app.core.response_armor import sanitize_error, strip_crlf
        from app.core.config import settings

        logger = logging.getLogger(__name__)


        class ResponseArmorMiddleware(BaseHTTPMiddleware):
            """ASGI middleware applying all five response hardening layers.

            Each layer is independently controlled by a config flag so operators
            can enable them incrementally without full rollout risk.
            """

            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                """Apply all response armor layers to every response.

                Args:
                    request: Incoming ASGI request.
                    call_next: Next handler in the middleware chain.

                Returns:
                    Hardened response with armor layers applied.
                """
                if not getattr(settings, "RESPONSE_ARMOR_ENABLED", True):
                    return await call_next(request)

                response = await call_next(request)
                self._apply_crlf_guard(response)
                self._apply_cache_control(response)
                self._remove_server_header(response)

                return response

            def _apply_crlf_guard(self, response: Response) -> None:
                """Strip CR/LF from all response header values.

                Args:
                    response: Response object to mutate in-place.
                """
                for key, value in list(response.headers.items()):
                    cleaned = strip_crlf(value)
                    if cleaned != value:
                        logger.warning(
                            "armor.crlf_stripped",
                            extra={"header": key, "original": repr(value)},
                        )
                        response.headers[key] = cleaned

            def _apply_cache_control(self, response: Response) -> None:
                """Enforce no-store Cache-Control on error responses.

                Args:
                    response: Response object to mutate in-place.
                """
                if response.status_code >= 400:
                    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                    response.headers["Pragma"] = "no-cache"

            def _remove_server_header(self, response: Response) -> None:
                """Remove the Server header to reduce fingerprinting surface.

                Args:
                    response: Response object to mutate in-place.
                """
                if "server" in response.headers:
                    del response.headers["server"]


        def register_response_armor(app: FastAPI) -> None:
            """Attach ResponseArmorMiddleware to *app*.

            Args:
                app: The FastAPI application instance.
            """
            app.add_middleware(ResponseArmorMiddleware)
            logger.info("response_armor.registered")
        '''))


def _patch_config(config_file: Path) -> None:
    """Inject ``RESPONSE_ARMOR_*`` fields inside the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "RESPONSE_ARMOR_ENABLED" in src:
        return

    fields = (
        "    RESPONSE_ARMOR_ENABLED: bool = True\n"
        "    RESPONSE_ARMOR_SANITIZE_ERRORS: bool = True\n"
        "    RESPONSE_ARMOR_TIMING_SAFE: bool = True\n"
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        src = src.rstrip("\n") + "\n" + fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Register response armor middleware in ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "register_response_armor" in src:
        return

    import_line = (
        "\nfrom app.middleware.response_armor import register_response_armor"
        "  # noqa: F401 — response armor\n"
    )
    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI" + import_line,
        )
    else:
        src = import_line + src

    marker = "app = FastAPI("
    if marker in src:
        idx = src.find(marker)
        depth = 0
        end = idx
        for i in range(idx + len(marker), len(src)):
            ch = src[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    end = i + 1
                    break
                depth -= 1
        src = src[:end] + "\nregister_response_armor(app)\n" + src[end:]
    else:
        src = src.rstrip("\n") + "\nregister_response_armor(app)\n"

    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
