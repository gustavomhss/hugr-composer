"""Generator for correlation ID middleware."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_correlation_id(output_dir: str) -> dict:
    """Generate a CorrelationMiddleware that threads a request ID through logs.

    Args:
        output_dir: Directory where middleware/correlation.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent("""\
        \"\"\"Correlation ID middleware.

        Extracts or generates a unique correlation ID per request, binds it
        to structlog context vars so every log line includes it, and returns
        it to the caller via the ``X-Correlation-ID`` response header.
        \"\"\"

        from __future__ import annotations

        import uuid

        import structlog
        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response

        _HEADER = "X-Correlation-ID"


        class CorrelationMiddleware(BaseHTTPMiddleware):
            \"\"\"Thread a correlation ID through the request lifecycle.

            If the incoming request carries an ``X-Correlation-ID`` header its
            value is reused; otherwise a new UUID4 is generated.  The ID is
            bound to structlog context vars so every log message produced
            during the request automatically includes it.
            \"\"\"

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                correlation_id = request.headers.get(_HEADER) or str(uuid.uuid4())

                # Bind to structlog so all downstream logs include it
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

                try:
                    response = await call_next(request)
                    response.headers[_HEADER] = correlation_id
                    return response
                finally:
                    structlog.contextvars.unbind_contextvars("correlation_id")
    """)

    file_path = out / "correlation.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "CorrelationMiddleware: reads X-Correlation-ID from request or generates UUID4.",
            "Binds to structlog contextvars, sets on response header, unbinds in finally block.",
        ],
    }
