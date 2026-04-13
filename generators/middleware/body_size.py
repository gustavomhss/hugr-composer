"""Generator for a request body-size limit middleware.

Rejects requests whose ``Content-Length`` header exceeds a configured
limit with HTTP 413 before the body is read.  This prevents trivial
memory-exhaustion attacks from uploading gigabyte-sized JSON bodies.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_body_size_middleware(
    output_dir: str,
    max_bytes: int = 10 * 1024 * 1024,
) -> dict:
    """Generate ``middleware/body_size.py`` with ``BodySizeLimitMiddleware``.

    Args:
        output_dir: The app package directory (``out/app``).
        max_bytes: Maximum allowed request body size in bytes.
            Defaults to 10 MiB.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f'''\
        """Request body-size limit middleware.

        Rejects requests whose ``Content-Length`` header exceeds the
        configured limit with HTTP 413 *Payload Too Large* before the
        body is even read.
        """

        from __future__ import annotations

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        MAX_BODY_BYTES = {max_bytes}


        class BodySizeLimitMiddleware(BaseHTTPMiddleware):
            """Reject oversized request bodies with HTTP 413."""

            def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
                super().__init__(app)
                self.max_bytes = max_bytes

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                # Fast path: reject by declared Content-Length.
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > self.max_bytes:
                            return JSONResponse(
                                status_code=413,
                                content={{
                                    "detail": "Request body too large",
                                    "max_bytes": self.max_bytes,
                                }},
                            )
                    except ValueError:
                        return JSONResponse(
                            status_code=400,
                            content={{"detail": "Invalid Content-Length header"}},
                        )
                return await call_next(request)
    ''')

    file_path = out / "body_size.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"Generated middleware/body_size.py (limit: {max_bytes} bytes).",
        ],
    }
