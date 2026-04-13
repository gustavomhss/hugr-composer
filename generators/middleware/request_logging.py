"""Generator for request logging middleware."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_request_logging(
    output_dir: str,
    redact_headers: list[str] | None = None,
) -> dict:
    """Generate a RequestLoggingMiddleware that logs every request with timing.

    Args:
        output_dir: Directory where middleware/request_logging.py will be written.
        redact_headers: Header names to redact from logs.
            Defaults to ``["authorization", "cookie", "x-api-key"]``.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    if redact_headers is None:
        redact_headers = ["authorization", "cookie", "x-api-key"]

    redact_repr = repr({h.lower() for h in redact_headers})

    content = textwrap.dedent(f'''\
        """Request logging middleware.

        Logs method, path, status code, duration, and client IP for every
        request using structlog.  Sensitive headers are automatically redacted.
        """

        from __future__ import annotations

        import time

        import structlog
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        logger = structlog.get_logger(__name__)

        _REDACT_HEADERS: set[str] = {redact_repr}


        class RequestLoggingMiddleware(BaseHTTPMiddleware):
            """Log every HTTP request with timing and metadata.

            Redacts values for headers listed in ``_REDACT_HEADERS`` so
            credentials never leak into log sinks.
            """

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                """Log method, path, status, timing, and client IP for the request.

                Args:
                    request: Incoming Starlette request.
                    call_next: Next middleware / route handler in the chain.

                Returns:
                    The unmodified response from downstream.
                """
                start = time.perf_counter()

                response = await call_next(request)

                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                client_ip = request.client.host if request.client else "unknown"

                await logger.ainfo(
                    "request",
                    method=request.method,
                    path=str(request.url.path),
                    status=response.status_code,
                    duration_ms=duration_ms,
                    client_ip=client_ip,
                )

                return response
    ''')

    file_path = out / "request_logging.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "RequestLoggingMiddleware with perf_counter timing and structlog.",
            f"Redacted headers: {redact_headers}.",
        ],
    }
