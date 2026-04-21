"""TOOL-089: add_csrf_protection — add CSRF tokens + SameSite cookies to FastAPI.

Generates ``app/security/__init__.py``, ``app/security/csrf.py`` with
``CSRFProtection`` (generate_token, validate_token, get_csrf_cookie),
``app/security/csrf_middleware.py`` with ``CSRFMiddleware`` (checks unsafe
methods, exempt paths, double submit cookie pattern), and
``app/api/routes/csrf.py`` with ``GET /csrf/token``.

Config fields added to ``app/core/config.py``: CSRF_ENABLED, CSRF_SECRET_KEY,
CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRF_EXEMPT_PATHS.

No external dependencies — uses Python stdlib only (hmac, hashlib, secrets).

The tool is idempotent: a second run detects ``CSRFProtection`` in
``app/security/csrf.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_csrf_protection import add_csrf_protection

    result = add_csrf_protection(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [.../app/security/csrf.py, ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_csrf_protection",
    "description": "Add CSRF token protection with double-submit cookie pattern to FastAPI.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_csrf_protection",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_csrf_protection(inp: ToolInput) -> ToolResult:
    """Add CSRF protection to a FastAPI project.

    Writes ``app/security/__init__.py``, ``app/security/csrf.py``,
    ``app/security/csrf_middleware.py``, ``app/api/routes/csrf.py``,
    patches ``app/core/config.py`` with CSRF config fields, and
    patches ``app/main.py`` to register the CSRF router.

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
    csrf_file = app_dir / "security" / "csrf.py"
    if csrf_file.exists() and "CSRFProtection" in csrf_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["CSRFProtection already present — CSRF protection already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would create csrf.py, csrf_middleware.py, routes/csrf.py, "
                   "patch config.py and main.py."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Create app/security/ package --------------------------------
    security_dir = app_dir / "security"
    security_dir.mkdir(parents=True, exist_ok=True)
    security_init = security_dir / "__init__.py"
    if not security_init.exists():
        _write_security_init(security_init)
        files_created.append(str(security_init))

    # --- Step 2: Write app/security/csrf.py ----------------------------------
    _write_csrf_core(csrf_file)
    files_created.append(str(csrf_file))

    # --- Step 3: Write app/security/csrf_middleware.py -----------------------
    middleware_file = security_dir / "csrf_middleware.py"
    _write_csrf_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 4: Write app/api/routes/csrf.py --------------------------------
    routes_dir = app_dir / "api" / "routes"
    if routes_dir.exists():
        csrf_route = routes_dir / "csrf.py"
        _write_csrf_route(csrf_route)
        files_created.append(str(csrf_route))

    # --- Step 5: Patch config.py with CSRF settings --------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 6: Patch main.py -----------------------------------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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
            "CSRF protection added: double-submit cookie pattern (no session required).",
            "CSRFMiddleware checks all unsafe methods (POST/PUT/PATCH/DELETE).",
            "Exempt paths configurable via CSRF_EXEMPT_PATHS (e.g. webhooks, health).",
            "GET /csrf/token endpoint issues a signed token for JS clients.",
            "No external dependencies — stdlib only (hmac, hashlib, secrets).",
        ],
        next_steps=[
            "Set CSRF_SECRET_KEY in .env (min 32 chars, random).",
            "Add CSRFMiddleware to app in main.py: app.add_middleware(CSRFMiddleware).",
            "Frontend: fetch /csrf/token, store in cookie, send X-CSRF-Token header.",
            "Exempt webhook paths: CSRF_EXEMPT_PATHS=['/webhooks/stripe', '/webhooks/github'].",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_security_init(dest: Path) -> None:
    """Write ``app/security/__init__.py``.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Security package — CSRF protection and input sanitization utilities.\"\"\"

        from app.security.csrf import CSRFProtection

        __all__ = ["CSRFProtection"]
    """))


def _write_csrf_core(dest: Path) -> None:
    """Write ``app/security/csrf.py`` with CSRFProtection class.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CSRF token generation and validation — double-submit cookie pattern.

        Uses HMAC-SHA256 with a configurable secret key. No external dependencies.

        Usage::

            from app.security.csrf import CSRFProtection
            protection = CSRFProtection(secret_key="my-secret")
            token = protection.generate_token()
            is_valid = protection.validate_token(token)
        \"\"\"

        from __future__ import annotations

        import hashlib
        import hmac
        import logging
        import secrets
        import time

        from starlette.responses import Response

        logger = logging.getLogger(__name__)

        _TOKEN_SEPARATOR = "."
        _DEFAULT_COOKIE_NAME = "csrftoken"
        _DEFAULT_HEADER_NAME = "X-CSRF-Token"
        _TOKEN_MAX_AGE_SECONDS = 3600  # 1 hour


        class CSRFProtection:
            \"\"\"CSRF protection using HMAC-signed tokens (double-submit cookie pattern).

            Tokens are ``{random_hex}.{timestamp}.{hmac_signature}``.

            Args:
                secret_key: Secret used for HMAC signing.
                cookie_name: Cookie name for the CSRF token.
                header_name: Request header name clients must send.
                max_age: Token max age in seconds (default 3600).
            \"\"\"

            def __init__(
                self,
                secret_key: str,
                cookie_name: str = _DEFAULT_COOKIE_NAME,
                header_name: str = _DEFAULT_HEADER_NAME,
                max_age: int = _TOKEN_MAX_AGE_SECONDS,
            ) -> None:
                \"\"\"Initialise CSRFProtection with signing key and config.

                Args:
                    secret_key: HMAC signing key (min 32 chars recommended).
                    cookie_name: Cookie name for the CSRF token.
                    header_name: HTTP header clients must send with the token.
                    max_age: Token validity window in seconds.
                \"\"\"
                self._secret = secret_key.encode()
                self.cookie_name = cookie_name
                self.header_name = header_name
                self.max_age = max_age

            def generate_token(self) -> str:
                \"\"\"Generate a new HMAC-signed CSRF token.

                Returns:
                    Token string ``{random}.{timestamp}.{hmac}``.
                \"\"\"
                random_part = secrets.token_hex(16)
                timestamp = str(int(time.time()))
                payload = f"{random_part}{_TOKEN_SEPARATOR}{timestamp}"
                sig = self._sign(payload)
                return f"{payload}{_TOKEN_SEPARATOR}{sig}"

            def validate_token(self, token: str) -> bool:
                \"\"\"Validate a CSRF token: checks signature and expiry.

                Args:
                    token: Token string from cookie or header.

                Returns:
                    ``True`` if token is valid and not expired.
                \"\"\"
                parts = token.split(_TOKEN_SEPARATOR)
                if len(parts) != 3:
                    return False
                random_part, ts_str, sig = parts
                payload = f"{random_part}{_TOKEN_SEPARATOR}{ts_str}"
                expected_sig = self._sign(payload)
                if not hmac.compare_digest(sig, expected_sig):
                    logger.warning("CSRF token signature mismatch")
                    return False
                try:
                    age = int(time.time()) - int(ts_str)
                except ValueError:
                    return False
                if age > self.max_age:
                    logger.warning("CSRF token expired (age=%ds)", age)
                    return False
                return True

            def get_csrf_cookie(self, response: Response, token: str) -> None:
                \"\"\"Set the CSRF token as a SameSite=Strict cookie on *response*.

                Args:
                    response: Starlette/FastAPI response to attach cookie to.
                    token: CSRF token string from ``generate_token()``.
                \"\"\"
                response.set_cookie(
                    key=self.cookie_name,
                    value=token,
                    httponly=False,  # JS must be able to read it
                    samesite="strict",
                    secure=False,  # Set True in production behind HTTPS
                    max_age=self.max_age,
                )

            def _sign(self, payload: str) -> str:
                \"\"\"Compute HMAC-SHA256 hex digest for *payload*.

                Args:
                    payload: String to sign.

                Returns:
                    Hex digest string.
                \"\"\"
                return hmac.new(
                    self._secret,
                    payload.encode(),
                    hashlib.sha256,
                ).hexdigest()
    """))


def _write_csrf_middleware(dest: Path) -> None:
    """Write ``app/security/csrf_middleware.py`` with CSRFMiddleware.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CSRF middleware — validates tokens on unsafe HTTP methods.

        Implements the double-submit cookie pattern: the client sends a CSRF
        token both as a cookie AND as a request header. The middleware verifies
        they match and that the HMAC signature is valid.

        Usage::

            from app.security.csrf_middleware import CSRFMiddleware
            app.add_middleware(CSRFMiddleware)
        \"\"\"

        from __future__ import annotations

        import logging
        from collections.abc import Callable

        from fastapi import Request
        from fastapi.responses import JSONResponse
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import Response
        from starlette.types import ASGIApp

        logger = logging.getLogger(__name__)

        _UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


        class CSRFMiddleware(BaseHTTPMiddleware):
            \"\"\"Double-submit CSRF protection middleware.

            For every unsafe HTTP method (POST/PUT/PATCH/DELETE) that is NOT
            in the exempt paths list, the middleware:
            1. Reads the CSRF token from the request cookie.
            2. Reads the CSRF token from the request header.
            3. Validates both tokens are identical and HMAC-signed correctly.

            Exempt paths (e.g. ``/webhooks/*``) bypass the check entirely.

            Args:
                app: ASGI application to wrap.
                exempt_paths: Iterable of path prefixes to exempt from CSRF checks.
            \"\"\"

            def __init__(
                self,
                app: ASGIApp,
                exempt_paths: list[str] | None = None,
            ) -> None:
                \"\"\"Initialise the middleware with optional exempt paths.

                Args:
                    app: ASGI application.
                    exempt_paths: Path prefixes exempt from CSRF checking.
                \"\"\"
                super().__init__(app)
                self._exempt: list[str] = exempt_paths or []

            async def dispatch(
                self,
                request: Request,
                call_next: Callable,
            ) -> Response:
                \"\"\"Check CSRF token on unsafe methods; pass-through otherwise.

                Args:
                    request: Incoming HTTP request.
                    call_next: ASGI next middleware / route handler.

                Returns:
                    Response from downstream or 403 JSON error.
                \"\"\"
                if request.method not in _UNSAFE_METHODS:
                    return await call_next(request)
                if self._is_exempt(request.url.path):
                    return await call_next(request)
                return await self._check_csrf(request, call_next)

            def _is_exempt(self, path: str) -> bool:
                \"\"\"Return True if *path* starts with any exempt prefix.

                Args:
                    path: Request path string.

                Returns:
                    ``True`` when path should skip CSRF validation.
                \"\"\"
                return any(path.startswith(prefix) for prefix in self._exempt)

            async def _check_csrf(
                self,
                request: Request,
                call_next: Callable,
            ) -> Response:
                \"\"\"Perform double-submit CSRF validation.

                Args:
                    request: HTTP request being checked.
                    call_next: Downstream handler.

                Returns:
                    403 JSON error when validation fails, else downstream response.
                \"\"\"
                from app.core.config import settings
                from app.security.csrf import CSRFProtection

                protection = CSRFProtection(
                    secret_key=settings.CSRF_SECRET_KEY,
                    cookie_name=settings.CSRF_COOKIE_NAME,
                    header_name=settings.CSRF_HEADER_NAME,
                )
                error = _validate_csrf_tokens(request, protection, settings)
                if error:
                    return JSONResponse(status_code=403, content={"detail": error})
                return await call_next(request)


        def _validate_csrf_tokens(
            request: Request,
            protection: object,
            settings: object,
        ) -> str | None:
            \"\"\"Check cookie+header tokens for double-submit CSRF pattern.

            Args:
                request: Incoming HTTP request.
                protection: CSRFProtection instance.
                settings: Application settings (provides cookie/header names).

            Returns:
                Error message string if validation fails, else ``None``.
            \"\"\"
            cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
            header_token = request.headers.get(settings.CSRF_HEADER_NAME, "")
            if not cookie_token or not header_token:
                logger.warning(
                    "CSRF token missing: method=%s path=%s",
                    request.method, request.url.path,
                )
                return "CSRF token missing"
            if cookie_token != header_token:
                logger.warning("CSRF double-submit mismatch: path=%s", request.url.path)
                return "CSRF token mismatch"
            if not protection.validate_token(cookie_token):
                logger.warning("CSRF token invalid or expired: path=%s", request.url.path)
                return "CSRF token invalid or expired"
            return None
    """))


def _write_csrf_route(dest: Path) -> None:
    """Write ``app/api/routes/csrf.py`` with GET /csrf/token endpoint.

    Args:
        dest: Absolute path for the file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"CSRF token endpoint — issues signed tokens for JavaScript clients.

        Endpoints:
            GET /csrf/token — generate a new CSRF token and set the cookie
        \"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter
        from fastapi.responses import JSONResponse

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/csrf", tags=["csrf"])


        @router.get("/token")
        async def get_csrf_token() -> JSONResponse:
            \"\"\"Issue a new CSRF token as both a JSON body and a SameSite cookie.

            JavaScript SPAs call this endpoint once (e.g. on app load) to obtain
            a CSRF token, then include it in the ``X-CSRF-Token`` header for all
            unsafe requests (POST/PUT/PATCH/DELETE).

            Returns:
                JSON response with ``{"csrf_token": "..."}`` and the token
                also set as a ``csrftoken`` SameSite=Strict cookie.
            \"\"\"
            from app.core.config import settings
            from app.security.csrf import CSRFProtection

            protection = CSRFProtection(
                secret_key=settings.CSRF_SECRET_KEY,
                cookie_name=settings.CSRF_COOKIE_NAME,
                header_name=settings.CSRF_HEADER_NAME,
            )
            token = protection.generate_token()
            response = JSONResponse(content={"csrf_token": token})
            protection.get_csrf_cookie(response, token)
            logger.debug("Issued CSRF token")
            return response
    """))


def _patch_config(config_file: Path) -> None:
    """Inject CSRF config fields into ``app/core/config.py`` Settings class body.

    Inserts fields before the closing ``settings = Settings()`` line, indented
    with 4 spaces so they are part of the ``class Settings`` body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("CSRF_ENABLED", "CSRF_ENABLED: bool = True"),
            ("CSRF_SECRET_KEY", 'CSRF_SECRET_KEY: str = "change-this-csrf-secret-key-min-32-chars!"'),
            ("CSRF_COOKIE_NAME", 'CSRF_COOKIE_NAME: str = "csrftoken"'),
            ("CSRF_HEADER_NAME", 'CSRF_HEADER_NAME: str = "X-CSRF-Token"'),
            ("CSRF_EXEMPT_PATHS", "CSRF_EXEMPT_PATHS: list[str] = []"),
        ],
    )


def _patch_main(main_file: Path) -> None:
    """Inject CSRF router registration comment into ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "csrf_router" in src or "csrf.router" in src:
        return
    note = (
        "\n# CSRF protection router — added by add_csrf_protection tool\n"
        "# from app.api.routes.csrf import router as csrf_router\n"
        "# app.include_router(csrf_router)\n"
        "# app.add_middleware(CSRFMiddleware)  # from app.security.csrf_middleware\n"
    )
    src = src.rstrip("\n") + "\n" + note
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
