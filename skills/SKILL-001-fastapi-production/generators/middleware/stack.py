"""Generator for the unified middleware stack registration."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_middleware_stack(
    output_dir: str,
    cors_origins: list[str] | None = None,
    with_gzip: bool = False,
) -> dict:
    """Generate a ``register_middleware`` function that wires all middleware in correct order.

    Args:
        output_dir: Directory where middleware/__init__.py will be written.
        cors_origins: CORS origins to pass through. Defaults to settings-based.
        with_gzip: Include GZipMiddleware.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    gzip_import = ""
    gzip_block = ""
    if with_gzip:
        gzip_import = "from starlette.middleware.gzip import GZipMiddleware\n"
        gzip_block = textwrap.dedent("""\
            # GZip (outermost -- compresses final response body)
            app.add_middleware(GZipMiddleware, minimum_size=500)

        """)
        gzip_block = textwrap.indent(gzip_block, "    ")

    # Always read origins from settings — callers configure the list
    # via ``BACKEND_CORS_ORIGINS`` in the environment / .env file.
    # The *cors_origins* argument is retained for API compatibility and
    # simply marks the source; it is no longer baked into the generated
    # code.
    _ = cors_origins  # acknowledged but unused (see docstring)
    origins_line = "origins = [str(o) for o in settings.BACKEND_CORS_ORIGINS]"

    # Build flow diagram
    if with_gzip:
        req_flow = "Request  ->  Correlation  ->  CORS  ->  Security  ->  Logging  -> GZip  ->  App"
        res_flow = "Response <-  Correlation  <-  CORS  <-  Security  <-  Logging  <- GZip  <-  App"
    else:
        req_flow = "Request  ->  Correlation  ->  CORS  ->  Security  ->  Logging  ->  App"
        res_flow = "Response <-  Correlation  <-  CORS  <-  Security  <-  Logging  <-  App"

    content = textwrap.dedent("""\
        \"\"\"Middleware stack -- correct registration order.

        Starlette processes middleware in reverse registration order:
        the **last** middleware added is the **first** to execute on an
        incoming request.  The order below is therefore intentional::

            {req_flow}
            {res_flow}
        \"\"\"

        from __future__ import annotations

        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        {gzip_import}
        from app.core.config import Settings
        from app.middleware.body_size import BodySizeLimitMiddleware
        from app.middleware.correlation import CorrelationMiddleware
        from app.middleware.idempotency import IdempotencyMiddleware
        from app.middleware.request_logging import RequestLoggingMiddleware
        from app.middleware.security_headers import SecurityHeadersMiddleware


        def register_middleware(app: FastAPI, settings: Settings) -> None:
            \"\"\"Register all middleware in the correct order.

            ORDER MATTERS: last added = first to execute on incoming request.
            \"\"\"
            {origins_line}

        {gzip_block}    # Request logging (outermost after optional gzip)
            app.add_middleware(RequestLoggingMiddleware)

            # Body size limit — block oversized payloads ASAP
            app.add_middleware(BodySizeLimitMiddleware)

            # Idempotency — cache responses keyed by Idempotency-Key header
            app.add_middleware(IdempotencyMiddleware)

            # Security headers
            app.add_middleware(SecurityHeadersMiddleware)

            # CORS (must be before security headers so preflight works)
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "Accept",
                    "X-Correlation-ID",
                    "X-Request-ID",
                ],
                expose_headers=["X-Correlation-ID"],
                max_age=600,
            )

            # Correlation ID (innermost -- runs first on request)
            app.add_middleware(CorrelationMiddleware)
    """).format(
        req_flow=req_flow,
        res_flow=res_flow,
        gzip_import=gzip_import,
        origins_line=origins_line,
        gzip_block=gzip_block,
    )

    file_path = out / "__init__.py"
    file_path.write_text(content)

    files = [str(file_path)]
    notes = [
        "register_middleware() wires Correlation -> CORS -> SecurityHeaders -> Logging"
        + (" -> GZip" if with_gzip else "")
        + " in correct Starlette order.",
    ]

    return {"files_created": files, "notes": notes}
