"""Generator for security headers middleware."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_security_headers(output_dir: str) -> dict:
    """Generate a SecurityHeadersMiddleware with all 7 production headers.

    Args:
        output_dir: Directory where middleware/security_headers.py will be written.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent("""\
        \"\"\"Security headers middleware.

        Adds defensive HTTP headers to every response. These headers protect
        against common web vulnerabilities (clickjacking, MIME sniffing,
        XSS, downgrade attacks).
        \"\"\"

        from __future__ import annotations

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import Response


        class SecurityHeadersMiddleware(BaseHTTPMiddleware):
            \"\"\"Inject security headers into every HTTP response.

            Args:
                content_security_policy: CSP directive string.
                    Defaults to ``default-src 'self'``.
            \"\"\"

            def __init__(
                self,
                app,  # noqa: ANN001
                content_security_policy: str = "default-src 'self'",
            ) -> None:
                super().__init__(app)
                self._headers: dict[str, str] = {
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "X-XSS-Protection": "1; mode=block",
                    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                    "Referrer-Policy": "strict-origin-when-cross-origin",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                    "Content-Security-Policy": content_security_policy,
                }

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                response = await call_next(request)
                for header, value in self._headers.items():
                    response.headers[header] = value
                return response
    """)

    file_path = out / "security_headers.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "SecurityHeadersMiddleware with 7 headers: X-Content-Type-Options, "
            "X-Frame-Options, X-XSS-Protection, HSTS, Referrer-Policy, "
            "Permissions-Policy, CSP.",
            "CSP is configurable via constructor param (default: \"default-src 'self'\").",
        ],
    }
