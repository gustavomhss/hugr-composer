"""Generator for application configuration (core/config.py)."""

from __future__ import annotations

MCP_TOOL = {
    "name": "fastapi_deployment_generate_config",
    "description": "Generate config.py with pydantic-settings, env parsing, and fail-fast validation.",
    "tags": ["generator", "infra"],
    "entry": "generate_config",
}

import textwrap
from pathlib import Path


def generate_config(
    output_dir: str,
    with_db: bool = True,
    with_redis: bool = False,
    with_smtp: bool = True,
    with_sentry: bool = False,
    prefix: str = "/api/v1",
) -> dict:
    """Generate a production-grade pydantic-settings config module.

    Args:
        output_dir: Directory where core/config.py will be written.
        with_db: Include database URL settings.
        with_redis: Include Redis URL setting.
        with_smtp: Include SMTP email settings.
        with_sentry: Include optional SENTRY_DSN setting. MUST be
            passed through when ``generate_app(with_sentry=True)``
            is also set — otherwise the emitted ``main.py`` would
            reference ``settings.SENTRY_DSN`` on a Settings class
            that doesn't declare it, and boot would fail with
            ``AttributeError``.
        prefix: Initial value for ``Settings.API_V1_STR`` (the
            runtime-adjustable API prefix). Defaults to ``/api/v1``;
            other generators (orchestrator, k8s, env_example,
            readme) thread the same value so the scaffold's
            emit-time prefix is internally consistent. Downstream
            code reads ``settings.API_V1_STR`` at runtime, so the
            prefix can still be changed via .env without
            regenerating.

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

    sentry_section = ""
    if with_sentry:
        # Sentry DSN is opt-in: empty = Sentry disabled, a real URL
        # = init the SDK in app/main.py. No REPLACE_WITH_ placeholder
        # because empty-is-valid here; the app/main.py init path
        # reads `if settings.SENTRY_DSN: sentry_sdk.init(...)`.
        sentry_section = "\n" + textwrap.dedent("""\
            # --- Sentry (opt-in; leave empty to disable) ---
            SENTRY_DSN: str | None = None
        """)
        sentry_section = textwrap.indent(sentry_section, "    ")

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

        from enum import Enum
        from typing import Annotated

        from pydantic import AnyHttpUrl, BeforeValidator, model_validator
        from pydantic_settings import BaseSettings, SettingsConfigDict{extra_import_block}


        class Environment(str, Enum):
            LOCAL = "local"
            STAGING = "staging"
            PRODUCTION = "production"


        def _normalize_credential(value: str) -> str:
            \"\"\"Canonicalise a credential for weak-value comparison.

            Lower-cases and strips separators (spaces, ``-``, ``_``) so that
            cosmetic variants of the same weak value collapse together --
            e.g. ``change-me`` and ``change me`` both reduce to the same
            canonical form as the bare ``changeme`` a careless operator
            might type.
            \"\"\"
            return (
                value.strip()
                .lower()
                .replace(" ", "")
                .replace("-", "")
                .replace("_", "")
            )


        # Known-weak secret / password values that MUST NOT appear in a running
        # settings object. Compared after _normalize_credential(), so each
        # entry below also covers its separator variants (``change-me`` here
        # rejects ``changeme`` / ``change_me`` / ``change me`` too). The set is
        # small because a real credential is indistinguishable from noise; its
        # entropy is what defends you, not the dictionary below. This is a
        # defence-in-depth catch for copy-paste accidents like leaving
        # ``changethis`` from the .env.example template in place.
        _WEAK_CREDENTIALS: frozenset[str] = frozenset(
            _normalize_credential(_c)
            for _c in (
                "",
                "changethis",
                "change-me",
                "password",
                "password123",
                "admin",
                "admin123",
                "secret",
                "12345678",
                "qwertyui",
            )
        )

        # Minimum entropy for SECRET_KEY. 32 bytes = 256 bits, the standard
        # for HMAC-SHA256 session signing.
        _SECRET_KEY_MIN_LEN: int = 32

        # Minimum length for FIRST_SUPERUSER_PASSWORD. 12 chars with mixed
        # classes is a pragmatic baseline; anything real should be longer.
        _SUPERUSER_PASSWORD_MIN_LEN: int = 12


        def _parse_cors(v: str | list[str]) -> list[str]:
            \"\"\"Accept a comma-separated string or a list for CORS origins.\"\"\"
            if isinstance(v, str):
                return [origin.strip() for origin in v.split(",") if origin.strip()]
            return v


        class Settings(BaseSettings):
            \"\"\"Application settings.

            Values are read from environment variables and/or a ``.env`` file.

            Security contract:
              * ``SECRET_KEY`` MUST be set (≥ 32 chars) in every environment,
                including LOCAL. Empty / short / known-weak values raise at
                boot. Generate with: ``openssl rand -hex 32``.
              * ``FIRST_SUPERUSER_EMAIL`` and ``FIRST_SUPERUSER_PASSWORD`` are
                optional: leave both empty to skip superuser seeding. If
                either is set, both MUST be set, the password MUST be
                ≥ 12 chars, and MUST NOT match any known-weak value.
              * ANY setting whose value starts with ``REPLACE_WITH_`` raises
                at boot. This covers every placeholder emitted by the
                scaffold (``.env.example``, the K8s Secret, the Dockerfile
                comments) — so a deployment that forgot to substitute a
                real value fails fast at container start instead of
                silently booting with a placeholder credential.
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
            API_V1_STR: str = "{api_v1_str}"
            DEBUG: bool = False

            # --- Security ---
            # SECRET_KEY has NO Python default: an unset env var surfaces as
            # "" and the validator rejects it. This keeps known-weak strings
            # like "changethis" out of the source tree entirely.
            SECRET_KEY: str = ""
            ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

            # --- CORS ---
            BACKEND_CORS_ORIGINS: Annotated[
                list[AnyHttpUrl],
                BeforeValidator(_parse_cors),
            ] = []

            # --- First Superuser (opt-in; leave empty to skip seeding) ---
            FIRST_SUPERUSER_EMAIL: str = ""
            FIRST_SUPERUSER_PASSWORD: str = ""

            # --- Rate Limiting ---
            # Disable in tests to avoid 429s from sequential test runs.
            RATE_LIMITING_ENABLED: bool = True

            # --- Frontend (used by password reset email links) ---
            FRONTEND_URL: str = "http://localhost:3000"
        {db_section}{redis_section}{smtp_section}{sentry_section}
            @model_validator(mode="after")
            def _enforce_security_contract(self) -> "Settings":
                for _f in type(self).model_fields:
                    _v = getattr(self, _f, None)
                    if isinstance(_v, str) and _v.startswith("REPLACE_WITH_"):
                        raise ValueError(
                            f"{{_f}} still carries scaffold placeholder '{{_v}}'. "
                            "Replace before boot (.env / k8s Secret / Dockerfile)."
                        )
                secret = self.SECRET_KEY or ""
                if (
                    len(secret) < _SECRET_KEY_MIN_LEN
                    or _normalize_credential(secret) in _WEAK_CREDENTIALS
                ):
                    raise ValueError(
                        "SECRET_KEY is empty, too short, or matches a known-weak "
                        f"value (min length {{_SECRET_KEY_MIN_LEN}} chars). "
                        "Generate a real key once and write it to .env:\\n"
                        '    echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env'
                    )
                email = (self.FIRST_SUPERUSER_EMAIL or "").strip()
                password = self.FIRST_SUPERUSER_PASSWORD or ""
                if bool(email) ^ bool(password):
                    raise ValueError(
                        "FIRST_SUPERUSER_EMAIL and FIRST_SUPERUSER_PASSWORD "
                        "must be set together (or both empty to skip seeding)."
                    )
                if password:
                    if len(password) < _SUPERUSER_PASSWORD_MIN_LEN:
                        raise ValueError(
                            "FIRST_SUPERUSER_PASSWORD MUST be at least "
                            f"{{_SUPERUSER_PASSWORD_MIN_LEN}} characters."
                        )
                    if _normalize_credential(password) in _WEAK_CREDENTIALS:
                        raise ValueError(
                            "FIRST_SUPERUSER_PASSWORD matches a known-weak "
                            "value. Choose a real password (≥12 chars)."
                        )
                return self


        # Instantiate at module level -- fail fast on bad config
        settings = Settings()
    """).format(
        extra_import_block=extra_import_block,
        db_section=db_section,
        redis_section=redis_section,
        smtp_section=smtp_section,
        sentry_section=sentry_section,
        api_v1_str=prefix,
    )

    file_path = out / "config.py"
    file_path.write_text(content)

    files = [str(file_path)]
    notes = [
        "Generated core/config.py with pydantic-settings, env parsing, and fail-fast instantiation."
    ]
    if with_db:
        notes.append("Database settings included with PostgresDsn builder.")
    if with_redis:
        notes.append("Redis URL setting included.")
    if with_smtp:
        notes.append("SMTP settings included with emails_enabled computed field.")
    if with_sentry:
        notes.append("SENTRY_DSN setting included (opt-in; empty = disabled).")

    return {"files_created": files, "notes": notes}
