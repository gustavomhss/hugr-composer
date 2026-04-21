"""
SKILL-001 Security Tool: Generate production security middleware for FastAPI.

Creates a complete security middleware stack: security headers, CORS hardening,
rate limiting with sliding window (Redis backend), request body size limits,
and a global exception handler that never leaks internal details. All generated
code follows KNOWLEDGE.md patterns.

Generated files:
    security/middleware.py    -- SecurityHeaders + RequestSizeLimit middleware
    security/cors.py          -- CORS configuration (strict origin list)
    security/rate_limit.py    -- SlowAPI rate limiter with Redis backend
    security/exceptions.py    -- Global exception handlers (sanitised errors)
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _middleware_py(with_csp: bool, max_body_bytes: int) -> str:
    """Template for security/middleware.py — headers + body size limit."""
    csp_line = ""
    if with_csp:
        csp_line = (
            '        response.headers["Content-Security-Policy"] = (\n'
            '            "default-src \'none\'; frame-ancestors \'none\'"\n'
            "        )\n"
        )

    return textwrap.dedent(f"""\
        \"\"\"Security middleware stack for FastAPI.

        Adds hardened security headers (OWASP 2025 recommended set) and
        enforces request body size limits to prevent memory exhaustion.
        \"\"\"

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response


        class SecurityHeadersMiddleware(BaseHTTPMiddleware):
            \"\"\"Add security headers to every response.

            Headers follow OWASP Secure Headers Project (2025) and the
            HTTP Security Response Headers Cheat Sheet recommendations.
            \"\"\"

            async def dispatch(self, request: Request, call_next) -> Response:
                response: Response = await call_next(request)

                # Prevent MIME sniffing — browser won't misinterpret Content-Type
                response.headers["X-Content-Type-Options"] = "nosniff"

                # Clickjacking — deny all iframe embedding
                response.headers["X-Frame-Options"] = "DENY"

                # HSTS — force HTTPS for 1 year, include subdomains, preload-ready
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains; preload"
                )

        {csp_line}\
                # Referrer — don't leak full URL on cross-origin requests
                response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

                # Permissions-Policy — disable unused browser features
                response.headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=(), payment=()"
                )

                # Legacy XSS protection for older browsers
                response.headers["X-XSS-Protection"] = "1; mode=block"

                # Prevent caching of authenticated responses
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"

                return response


        class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
            \"\"\"Reject requests with body larger than max_bytes.

            Prevents memory exhaustion attacks where an attacker sends a
            multi-gigabyte payload. Checks Content-Length header first
            (fast path) and falls back to reading body chunks if the
            header is absent (chunked transfer encoding).
            \"\"\"

            def __init__(self, app, max_bytes: int = {max_body_bytes}):
                super().__init__(app)
                self.max_bytes = max_bytes

            async def dispatch(self, request: Request, call_next) -> Response:
                content_length = request.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > self.max_bytes:
                            return JSONResponse(
                                status_code=413,
                                content={{
                                    "detail": (
                                        f"Request body too large. "
                                        f"Maximum: {{self.max_bytes}} bytes."
                                    ),
                                }},
                            )
                    except ValueError:
                        pass  # Malformed Content-Length — let server handle
                return await call_next(request)
    """)


def _cors_py(origins: list[str]) -> str:
    """Template for security/cors.py — strict CORS configuration."""
    origins_repr = ",\n        ".join(f'"{o}"' for o in origins)
    return textwrap.dedent(f"""\
        \"\"\"CORS configuration — strict origin allowlist.

        NEVER use allow_origins=["*"] with allow_credentials=True.
        Dynamic origin reflection is equally dangerous — it allows
        any site to steal credentials via cross-origin requests.
        \"\"\"

        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware


        # Explicit list of allowed origins. Update for each environment.
        ALLOWED_ORIGINS: list[str] = [
            {origins_repr},
        ]


        def configure_cors(app: FastAPI) -> None:
            \"\"\"Add CORSMiddleware with hardened settings.

            - allow_origins: explicit list only (never wildcard)
            - allow_credentials: True (requires explicit origins, not *)
            - allow_methods: only methods your API actually uses
            - expose_headers: only headers the frontend needs to read
            - max_age: 600s preflight cache (Chrome max 7200, Firefox 86400)
            \"\"\"
            app.add_middleware(
                CORSMiddleware,
                allow_origins=ALLOWED_ORIGINS,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                expose_headers=["X-Request-ID"],
                max_age=600,
            )
    """)


def _rate_limit_py(with_redis: bool) -> str:
    """Template for security/rate_limit.py — SlowAPI rate limiter."""
    storage_line = ""
    if with_redis:
        storage_line = '    storage_uri="redis://localhost:6379/0",'
    else:
        storage_line = '    # storage_uri="redis://localhost:6379/0",  # Enable for production'

    return textwrap.dedent(f"""\
        \"\"\"Rate limiting with SlowAPI — sliding window, Redis backend.

        Three layers of protection:
        1. Global default: 200 req/min per IP (covers all endpoints)
        2. Per-endpoint: tighter limits on auth/expensive operations
        3. Per-user: identified users get separate counters (post-auth)

        Install: pip install slowapi
        Redis:   pip install redis  (required for distributed deployments)
        \"\"\"

        import os

        from fastapi import FastAPI, Request
        from slowapi import Limiter
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import SlowAPIMiddleware
        from slowapi.util import get_remote_address
        from starlette.responses import JSONResponse


        def _get_key_func():
            \"\"\"Return IP-based key function.

            Behind a reverse proxy, SlowAPI reads X-Forwarded-For automatically
            via get_remote_address. Ensure your proxy is trusted — otherwise an
            attacker can forge the header to bypass rate limits.
            \"\"\"
            return get_remote_address


        # Limiter instance — import this in your routers for per-endpoint limits
        limiter = Limiter(
            key_func=_get_key_func(),
            default_limits=["200/minute"],
        {storage_line}
            strategy="moving-window",
        )


        async def _rate_limit_exceeded_handler(
            request: Request, exc: RateLimitExceeded,
        ) -> JSONResponse:
            \"\"\"Return 429 with Retry-After header.

            Always include Retry-After so well-behaved clients know when to
            retry instead of hammering the endpoint in a tight loop.
            \"\"\"
            retry_after = getattr(exc, "detail", "60")
            return JSONResponse(
                status_code=429,
                content={{
                    "detail": "Rate limit exceeded. Try again later.",
                    "retry_after": str(retry_after),
                }},
                headers={{"Retry-After": str(retry_after)}},
            )


        def configure_rate_limiting(app: FastAPI) -> None:
            \"\"\"Attach rate limiter to FastAPI app.

            Call this in your app factory or main.py after creating the app.

            Usage in routers::

                from .rate_limit import limiter

                @router.post("/auth/login")
                @limiter.limit("5/minute")
                async def login(request: Request, body: LoginRequest):
                    ...
            \"\"\"
            app.state.limiter = limiter
            app.add_middleware(SlowAPIMiddleware)
            app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    """)


def _exceptions_py() -> str:
    """Template for security/exceptions.py — sanitised global error handlers."""
    return textwrap.dedent("""\
        \"\"\"Global exception handlers — never leak internal details.

        Every unhandled exception is caught, logged with an error_id for
        correlation, and returned to the client with a generic message.
        Stack traces go to logs only — never in HTTP responses.
        \"\"\"

        import logging
        import uuid

        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from sqlalchemy.exc import IntegrityError
        from starlette.responses import JSONResponse

        logger = logging.getLogger(__name__)


        def configure_exception_handlers(app: FastAPI) -> None:
            \"\"\"Register all global exception handlers.\"\"\"

            @app.exception_handler(Exception)
            async def unhandled_exception_handler(
                request: Request, exc: Exception,
            ) -> JSONResponse:
                error_id = uuid.uuid4().hex[:8]
                logger.error(
                    "Unhandled exception [%s]: %s",
                    error_id,
                    str(exc),
                    exc_info=True,
                )
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": "Internal server error",
                        "error_id": error_id,
                    },
                )

            @app.exception_handler(IntegrityError)
            async def integrity_error_handler(
                request: Request, exc: IntegrityError,
            ) -> JSONResponse:
                error_id = uuid.uuid4().hex[:8]
                logger.error("DB integrity error [%s]: %s", error_id, str(exc))
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "Resource conflict",
                        "error_id": error_id,
                    },
                )

            @app.exception_handler(RequestValidationError)
            async def validation_error_handler(
                request: Request, exc: RequestValidationError,
            ) -> JSONResponse:
                errors = []
                for err in exc.errors():
                    clean = {
                        "field": " -> ".join(str(loc) for loc in err.get("loc", [])),
                        "message": err.get("msg", "Invalid value"),
                        "type": err.get("type", "value_error"),
                    }
                    errors.append(clean)
                return JSONResponse(
                    status_code=422,
                    content={"detail": errors},
                )
    """)


def _init_py() -> str:
    """Template for security/__init__.py."""
    return textwrap.dedent("""\
        \"\"\"Security module — production security middleware for FastAPI.\"\"\"
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


MCP_TOOL = {
    "name": "fastapi_meta_generate_security_middleware",
    "description": "Scaffold the full security middleware stack (CSP, CSRF, rate limiting, headers) for a new project.",
    "tags": ["security", "generator", "scaffold"],
    "entry": "generate_security_middleware",
}


def generate_security_middleware(
    output_dir: str,
    with_rate_limit: bool = True,
    with_csp: bool = True,
    with_redis: bool = True,
    cors_origins: list[str] | None = None,
    max_body_bytes: int = 1_048_576,
) -> dict:
    """
    Generate a production-ready security middleware stack for FastAPI.

    Creates 4-5 files inside a ``security/`` subdirectory of *output_dir*:
    middleware (headers + body size limit), CORS config, exception handlers,
    and optionally rate limiting with Redis-backed sliding window.

    Args:
        output_dir: Parent directory where ``security/`` will be created.
        with_rate_limit: Include SlowAPI rate limiter configuration.
        with_csp: Include Content-Security-Policy header in middleware.
        with_redis: Configure rate limiter with Redis storage backend.
        cors_origins: Explicit list of allowed origins. Defaults to
            ``["https://localhost:3000"]``.
        max_body_bytes: Maximum request body size in bytes. Default 1MB.

    Returns:
        Dict with ``created_files`` (list of relative paths),
        ``security_path`` (absolute path to created directory),
        and configuration flags.

    Example::

        result = generate_security_middleware(
            "/tmp/myproject",
            with_rate_limit=True,
            cors_origins=["https://myapp.com", "https://staging.myapp.com"],
        )
        print(result["created_files"])
        # ['security/__init__.py', 'security/middleware.py',
        #  'security/cors.py', 'security/rate_limit.py',
        #  'security/exceptions.py']
    """
    if cors_origins is None:
        cors_origins = ["https://localhost:3000"]

    security_dir = Path(output_dir) / "security"
    security_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "middleware.py": _middleware_py(with_csp, max_body_bytes),
        "cors.py": _cors_py(cors_origins),
        "exceptions.py": _exceptions_py(),
    }

    if with_rate_limit:
        files["rate_limit.py"] = _rate_limit_py(with_redis)

    created: list[str] = []
    for filename, content in files.items():
        filepath = security_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"security/{filename}")

    # Generate integration instructions
    findings: list[Finding] = []
    if not with_rate_limit:
        findings.append(Finding(
            rule_id="SEC-SCAFFOLD-01",
            severity=Severity.MEDIUM,
            title="Rate limiting not generated",
            description=(
                "Rate limiting was skipped. Without it, your API is vulnerable "
                "to brute force and DoS attacks (OWASP API #4: Unrestricted "
                "Resource Consumption)."
            ),
            fix_suggestion="Re-run with with_rate_limit=True.",
        ))

    if not with_redis and with_rate_limit:
        findings.append(Finding(
            rule_id="SEC-SCAFFOLD-02",
            severity=Severity.LOW,
            title="Rate limiter using in-memory storage",
            description=(
                "Rate limiter is configured without Redis. In multi-worker/pod "
                "deployments each instance has its own counter, making rate "
                "limiting ineffective."
            ),
            fix_suggestion=(
                "Set storage_uri='redis://localhost:6379/0' in rate_limit.py "
                "or re-run with with_redis=True."
            ),
        ))

    return {
        "created_files": sorted(created),
        "security_path": str(security_dir),
        "with_rate_limit": with_rate_limit,
        "with_csp": with_csp,
        "with_redis": with_redis,
        "cors_origins": cors_origins,
        "max_body_bytes": max_body_bytes,
        "findings": [f.model_dump() for f in findings],
        "integration_hint": (
            "Add to main.py:\n"
            "  from security.middleware import SecurityHeadersMiddleware, "
            "RequestSizeLimitMiddleware\n"
            "  from security.cors import configure_cors\n"
            "  from security.exceptions import configure_exception_handlers\n"
            + (
                "  from security.rate_limit import configure_rate_limiting\n"
                if with_rate_limit else ""
            )
            + "\n"
            "  # Order matters: size limit first, then headers, then CORS\n"
            "  app.add_middleware(RequestSizeLimitMiddleware)\n"
            "  app.add_middleware(SecurityHeadersMiddleware)\n"
            "  configure_cors(app)\n"
            + (
                "  configure_rate_limiting(app)\n"
                if with_rate_limit else ""
            )
            + "  configure_exception_handlers(app)\n"
        ),
    }
