"""Generator for .env.example with all required environment variables."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_env_example(
    output_dir: str,
    with_db: bool = True,
    with_redis: bool = False,
    with_smtp: bool = True,
) -> dict:
    """Generate a .env.example showing all required env vars with safe placeholders.

    Args:
        output_dir: Directory where .env.example will be written.
        with_db: Include database connection variables.
        with_redis: Include Redis URL variable.
        with_smtp: Include SMTP email variables.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []

    # --- Application ---
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # Application
        # =============================================================================
        # Secret key for JWT signing and CSRF. MUST be changed in production.
        # Generate with: openssl rand -hex 32
        SECRET_KEY=changethis-generate-with-openssl-rand-hex-32

        # Environment: local | staging | production
        # Controls debug mode, CORS strictness, and secret-key validation.
        ENVIRONMENT=local

        # Display name used in API docs and email templates.
        PROJECT_NAME=my-app

        # URL prefix for all API routes.
        API_V1_STR=/api/v1

        # Enable debug mode (never true in production).
        DEBUG=false
    """))

    # --- Database ---
    if with_db:
        sections.append(textwrap.dedent("""\
            # =============================================================================
            # Database (PostgreSQL)
            # =============================================================================
            # These are combined into:
            #   postgresql+asyncpg://POSTGRES_USER:POSTGRES_PASSWORD@POSTGRES_SERVER:POSTGRES_PORT/POSTGRES_DB
            POSTGRES_USER=postgres
            POSTGRES_PASSWORD=changethis
            POSTGRES_SERVER=localhost
            POSTGRES_PORT=5432
            POSTGRES_DB=app
        """))

    # --- CORS ---
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # CORS
        # =============================================================================
        # Comma-separated list of allowed origins, or JSON array.
        # Example: http://localhost:3000,http://localhost:8080
        CORS_ORIGINS=["http://localhost:3000"]
    """))

    # --- SMTP ---
    if with_smtp:
        sections.append(textwrap.dedent("""\
            # =============================================================================
            # SMTP (optional — leave blank to disable email features)
            # =============================================================================
            SMTP_HOST=
            SMTP_PORT=587
            SMTP_TLS=true
            SMTP_SSL=false
            SMTP_USER=
            SMTP_PASSWORD=
            EMAILS_FROM_EMAIL=noreply@example.com
            EMAILS_FROM_NAME=
        """))

    # --- First Superuser ---
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # First Superuser (created on initial startup)
        # =============================================================================
        FIRST_SUPERUSER_EMAIL=admin@example.com
        FIRST_SUPERUSER_PASSWORD=changethis
    """))

    # --- Redis ---
    if with_redis:
        sections.append(textwrap.dedent("""\
            # =============================================================================
            # Redis (optional — used for caching / rate-limiting)
            # =============================================================================
            REDIS_URL=redis://localhost:6379/0
        """))

    content = "\n".join(sections)

    file_path = out / ".env.example"
    file_path.write_text(content)

    files = [str(file_path)]
    notes = ["Generated .env.example with safe placeholder values for all required variables."]
    if with_db:
        notes.append("Database (PostgreSQL) variables included.")
    if with_smtp:
        notes.append("SMTP variables included (blank = disabled).")
    if with_redis:
        notes.append("Redis URL included.")

    return {"files_created": files, "notes": notes}
