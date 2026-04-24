"""Generator for .env.example with all required environment variables."""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_deployment_generate_env_example',
    'description': 'Generate .env.example with all required environment variables and safe placeholders.',
    'tags': ['generator', 'infra'],
    'entry': 'generate_env_example',
}

import textwrap
from pathlib import Path


def generate_env_example(
    output_dir: str,
    with_db: bool = True,
    with_redis: bool = False,
    with_smtp: bool = True,
    with_sentry: bool = False,
) -> dict:
    """Generate a .env.example showing all required env vars with safe placeholders.

    Args:
        output_dir: Directory where .env.example will be written.
        with_db: Include database connection variables.
        with_redis: Include Redis URL variable.
        with_smtp: Include SMTP email variables.
        with_sentry: Include optional `SENTRY_DSN=` row. Must match
            the `with_sentry` flag on ``generate_config`` —
            otherwise the emitted Settings class and env template
            disagree on whether SENTRY_DSN is a real field.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []

    # --- Header ---
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # .env.example — TEMPLATE; NEVER commit a copy named .env
        # =============================================================================
        # Every value marked REPLACE_WITH_* is a placeholder. The generated
        # config.py REFUSES to boot while any REPLACE_WITH_* value is still
        # in place (known-weak credential check). Fill each one before first
        # run.
        #
        # Quick-start for local dev (generates a real SECRET_KEY):
        #     cp .env.example .env
        #     sed -i '' "s/REPLACE_WITH_openssl_rand_hex_32/$(openssl rand -hex 32)/" .env
        #     # then set POSTGRES_PASSWORD + (optionally) FIRST_SUPERUSER_*
        #
        # The first superuser is OPT-IN: leave both FIRST_SUPERUSER_* empty
        # to skip seeding. If set, password must be ≥ 12 chars and not a
        # known-weak value.
    """))

    # --- Application ---
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # Application
        # =============================================================================
        # Secret key for JWT signing and CSRF. Required in every environment
        # (config.py fails fast if empty, < 32 chars, or matches a known-
        # weak value). Generate with: openssl rand -hex 32
        SECRET_KEY=REPLACE_WITH_openssl_rand_hex_32

        # Environment: local | staging | production
        # Controls debug mode, CORS strictness, and cookie flags.
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
            POSTGRES_PASSWORD=REPLACE_WITH_strong_db_password
            POSTGRES_SERVER=localhost
            POSTGRES_PORT=5432
            POSTGRES_DB=app
        """))

    # --- CORS ---
    # Field name must match `Settings.BACKEND_CORS_ORIGINS` in
    # app/core/config.py; the middleware reads it via
    # `settings.BACKEND_CORS_ORIGINS`. Emitting `CORS_ORIGINS` here
    # (the pre-fix name) would silently leave the setting unset and
    # the allow-list empty at runtime.
    sections.append(textwrap.dedent("""\
        # =============================================================================
        # CORS
        # =============================================================================
        # Comma-separated list of allowed origins, or JSON array.
        # Example: http://localhost:3000,http://localhost:8080
        # Matches Settings.BACKEND_CORS_ORIGINS (app/core/config.py).
        BACKEND_CORS_ORIGINS=["http://localhost:3000"]
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
        # First Superuser (OPT-IN — leave both empty to skip seeding)
        # =============================================================================
        # When SET: the startup script `python -m app.initial_data` creates
        # the superuser if they don't exist. Both must be set together;
        # password must be ≥ 12 chars and not a known-weak value.
        # When EMPTY: seeding is skipped with a warning log line.
        FIRST_SUPERUSER_EMAIL=
        FIRST_SUPERUSER_PASSWORD=
    """))

    # --- Redis ---
    if with_redis:
        sections.append(textwrap.dedent("""\
            # =============================================================================
            # Redis (optional — used for caching / rate-limiting)
            # =============================================================================
            REDIS_URL=redis://localhost:6379/0
        """))
    # --- Sentry ---
    if with_sentry:
        sections.append(textwrap.dedent("""\
            # =============================================================================
            # Sentry (opt-in — leave empty to disable error tracking)
            # =============================================================================
            # Set to a real Sentry DSN to enable; app/main.py initialises
            # the SDK only when this value is non-empty.
            SENTRY_DSN=
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
    if with_sentry:
        notes.append("SENTRY_DSN row included (blank = disabled).")

    return {"files_created": files, "notes": notes}
