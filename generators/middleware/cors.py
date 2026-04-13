"""Generator for CORS middleware configuration."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_cors(
    output_dir: str,
    origins: list[str] | None = None,
) -> dict:
    """Generate a CORS configuration module.

    Args:
        output_dir: Directory where middleware/cors_config.py will be written.
        origins: Allowed origins list. Defaults to ``["https://localhost:3000"]``.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    if origins is None:
        origins = ["https://localhost:3000"]

    origins_repr = repr(origins)

    content = textwrap.dedent(f'''\
        """CORS middleware configuration.

        NEVER uses wildcard origins. All origins must be explicitly listed.
        """

        from __future__ import annotations

        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware


        _DEFAULT_ORIGINS: list[str] = {origins_repr}


        def configure_cors(
            app: FastAPI,
            origins: list[str] | None = None,
        ) -> None:
            """Register CORS middleware on the application.

            Args:
                app: FastAPI application instance.
                origins: Allowed origins. Falls back to ``_DEFAULT_ORIGINS``.
            """
            allowed_origins = origins or _DEFAULT_ORIGINS

            app.add_middleware(
                CORSMiddleware,
                allow_origins=[str(o) for o in allowed_origins],
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
    ''')

    file_path = out / "cors_config.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            f"CORS configured with explicit origins: {origins}.",
            "Credentials enabled, explicit methods/headers, max_age=600.",
        ],
    }
