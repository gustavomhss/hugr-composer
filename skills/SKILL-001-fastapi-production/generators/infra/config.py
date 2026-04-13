"""Generator for application configuration (core/config.py)."""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_config(
    output_dir: str,
    with_db: bool = True,
    with_redis: bool = False,
    with_smtp: bool = True,
) -> dict:
    """Generate a production-grade pydantic-settings config module.

    Args:
        output_dir: Directory where core/config.py will be written.
        with_db: Include database URL settings.
        with_redis: Include Redis URL setting.
        with_smtp: Include SMTP email settings.

    Returns:
        Dict with files_created and notes.
    """
    out = Path(output_dir) / "core"
    out.mkdir(parents=True, exist_ok=True)

    # Build optional class-body sections (indented 4 spaces for class body)
    db_section = ""
    if with_db:
        db_section = "\n" + textwrap.dedent("""\
            # --- Database ---
            POSTGRES_SERVER: str = "localhost"
            POSTGRES_PORT: int = 5432
            POSTGRES_USER: str = "postgres"
            POSTGRES_PASSWORD: str = ""
            POSTGRES_DB: str = "app"

            @computed_field  # type: ignore[prop-decorator]
            @property
            def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
                return MultiHostUrl.build(
                    scheme="postgresql+asyncpg",
                    username=self.POSTGRES_USER,
                    password=self.POSTGRES_PASSWORD,
                    host=self.POSTGRES_SERVER,
                    port=self.POSTGRES_PORT,
                    path=self.POSTGRES_DB,
                )

            @computed_field  # type: ignore[prop-decorator]
            @property
            def database_url(self) -> str:
                \"\"\"Lowercase alias for SQLALCHEMY_DATABASE_URI.

                Some integrations (e.g. Alembic env.py templates, third-party
                libraries) expect a lowercase ``database_url`` attribute.
                This forwards to the canonical SQLALCHEMY_DATABASE_URI.
                \"\"\"
                return str(self.SQLALCHEMY_DATABASE_URI)
        """)
        # Indent to class body level (4 spaces)
        db_section = textwrap.indent(db_section, "    ")

    redis_section = ""
    if with_redis:
        redis_section = "\n" + textwrap.dedent("""\
            # --- Redis ---
            REDIS_URL: str = "redis://localhost:6379/0"
        """)
        redis_section = textwrap.indent(redis_section, "    ")

    smtp_section = ""
    if with_smtp:
        smtp_section = "\n" + textwrap.dedent("""\
            # --- SMTP ---
            SMTP_TLS: bool = True
            SMTP_SSL: bool = False
            SMTP_PORT: int = 587
            SMTP_HOST: str | None = None
            SMTP_USER: str | None = None
            SMTP_PASSWORD: str | None = None
            EMAILS_FROM_EMAIL: str | None = None
            EMAILS_FROM_NAME: str | None = None

            @computed_field  # type: ignore[prop-decorator]
            @property
            def emails_enabled(self) -> bool:
                return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)
        """)
        smtp_section = textwrap.indent(smtp_section, "    ")

    # Build imports
    extra_imports = []
    if with_db:
        extra_imports.append("from pydantic import PostgresDsn, computed_field")
        extra_imports.append("from pydantic_core import MultiHostUrl")
    elif with_smtp:
        extra_imports.append("from pydantic import computed_field")

    extra_import_block = "\n".join(extra_imports)
    if extra_import_block:
        extra_import_block = "\n" + extra_import_block

    content = textwrap.dedent("""\
        \"\"\"Application settings -- loaded once at import time (fail-fast).\"\"\"

        from __future__ import annotations

        import warnings
        from enum import Enum
        from typing import Annotated

        from pydantic import AnyHttpUrl, BeforeValidator, model_validator
        from pydantic_settings import BaseSettings, SettingsConfigDict{extra_import_block}


        class Environment(str, Enum):
            LOCAL = "local"
            STAGING = "staging"
            PRODUCTION = "production"


        def _parse_cors(v: str | list[str]) -> list[str]:
            \"\"\"Accept a comma-separated string or a list for CORS origins.\"\"\"
            if isinstance(v, str):
                return [origin.strip() for origin in v.split(",") if origin.strip()]
            return v


        class Settings(BaseSettings):
            \"\"\"Application settings.

            Values are read from environment variables and/or a ``.env`` file.
            \"\"\"

            model_config = SettingsConfigDict(
                env_file=".env",
                env_file_encoding="utf-8",
                env_ignore_empty=True,
                extra="ignore",
            )

            # --- General ---
            ENVIRONMENT: Environment = Environment.LOCAL
            PROJECT_NAME: str = "app"
            API_V1_STR: str = "/api/v1"
            DEBUG: bool = False

            # --- Security ---
            SECRET_KEY: str = "changethis"
            ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

            # --- CORS ---
            BACKEND_CORS_ORIGINS: Annotated[
                list[AnyHttpUrl],
                BeforeValidator(_parse_cors),
            ] = []

            # --- First Superuser ---
            FIRST_SUPERUSER_EMAIL: str = "admin@example.com"
            FIRST_SUPERUSER_PASSWORD: str = "changethis"

            # --- Rate Limiting ---
            # Disable in tests to avoid 429s from sequential test runs.
            RATE_LIMITING_ENABLED: bool = True

            # --- Frontend (used by password reset email links) ---
            FRONTEND_URL: str = "http://localhost:3000"
        {db_section}{redis_section}{smtp_section}
            @model_validator(mode="after")
            def _validate_secret_key(self) -> "Settings":
                if self.ENVIRONMENT != Environment.LOCAL and self.SECRET_KEY == "changethis":
                    raise ValueError(
                        "SECRET_KEY must be changed from default in non-local environments. "
                        "Generate one with: openssl rand -hex 32"
                    )
                if self.SECRET_KEY == "changethis":
                    warnings.warn(
                        "SECRET_KEY is set to the default value. "
                        "Generate a proper key with: openssl rand -hex 32",
                        UserWarning,
                        stacklevel=1,
                    )
                return self


        # Instantiate at module level -- fail fast on bad config
        settings = Settings()
    """).format(
        extra_import_block=extra_import_block,
        db_section=db_section,
        redis_section=redis_section,
        smtp_section=smtp_section,
    )

    file_path = out / "config.py"
    file_path.write_text(content)

    files = [str(file_path)]
    notes = ["Generated core/config.py with pydantic-settings, env parsing, and fail-fast instantiation."]
    if with_db:
        notes.append("Database settings included with PostgresDsn builder.")
    if with_redis:
        notes.append("Redis URL setting included.")
    if with_smtp:
        notes.append("SMTP settings included with emails_enabled computed field.")

    return {"files_created": files, "notes": notes}
