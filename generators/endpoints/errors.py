"""Generator for centralized error handlers."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_error_handlers(output_dir: str) -> dict:
    """Generate a ``register_error_handlers`` function with structured error responses.

    Args:
        output_dir: Directory where core/errors.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent('''\
        """Centralized error handlers.

        Registers exception handlers on the FastAPI app so that every error
        response follows a consistent JSON structure and sensitive details
        are never leaked to the client.
        """

        from __future__ import annotations

        import structlog
        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from starlette.exceptions import HTTPException as StarletteHTTPException

        logger = structlog.get_logger(__name__)


        def register_error_handlers(app: FastAPI) -> None:
            """Attach exception handlers to the application."""

            @app.exception_handler(StarletteHTTPException)
            async def http_exception_handler(
                request: Request,
                exc: StarletteHTTPException,
            ) -> JSONResponse:
                """Handle HTTPException with a structured JSON body."""
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": exc.detail,
                        "status_code": exc.status_code,
                    },
                    headers=getattr(exc, "headers", None),
                )

            @app.exception_handler(RequestValidationError)
            async def validation_exception_handler(
                request: Request,
                exc: RequestValidationError,
            ) -> JSONResponse:
                """Handle Pydantic validation errors with field-level detail."""
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": "Validation Error",
                        "status_code": 422,
                        "detail": exc.errors(),
                    },
                )

            @app.exception_handler(Exception)
            async def unhandled_exception_handler(
                request: Request,
                exc: Exception,
            ) -> JSONResponse:
                """Catch-all for unhandled exceptions.

                Logs the full traceback via structlog but NEVER exposes
                ``str(exc)`` to the client.

                Generates a short ``error_id`` (uuid4 hex[:8]) included in
                both the log entry and the response so support can correlate
                client-reported errors to server logs without leaking
                internal details.
                """
                import uuid as _uuid
                error_id = _uuid.uuid4().hex[:8]
                await logger.aerror(
                    "unhandled_exception",
                    error_id=error_id,
                    exc_type=type(exc).__name__,
                    exc_msg=str(exc),
                    path=str(request.url),
                    method=request.method,
                    exc_info=True,
                )

                return JSONResponse(
                    status_code=500,
                    content={
                        "error": "Internal Server Error",
                        "status_code": 500,
                        "error_id": error_id,
                    },
                )
    ''')

    file_path = out / "errors.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "register_error_handlers() handles HTTPException, RequestValidationError, "
            "and unhandled Exception.",
            "500 responses never expose exception details to the client; "
            "full traceback is logged via structlog.",
            "Phase 0.5 nugget: 500 handler now generates error_id=uuid4().hex[:8] "
            "included in both log (for correlation) and JSON response "
            "(for support lookup). Extracted from scaffold_security.py._exceptions_py().",
        ],
    }
