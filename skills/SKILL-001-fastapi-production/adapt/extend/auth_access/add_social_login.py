"""TOOL-074: add_social_login — Google/GitHub/Apple OAuth2 social login with account linking.

Generates all files required for social login via Google, GitHub, and Apple OAuth2:
a ``SocialAccount`` SQLAlchemy model (provider + provider_user_id + user_id FK),
a ``SocialAuthProvider`` enum with lazy httpx calls, Pydantic schemas, route handlers
(GET /auth/{provider}/login → redirect, GET /auth/{provider}/callback → JWT),
and an Alembic migration.

Account linking: if the email returned by the provider matches an existing user, the
social account is linked to that user; otherwise a new user is auto-provisioned.

The tool is idempotent: a second run detects the ``SocialAccount`` model fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_social_login import add_social_login

    result = add_social_login(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/auth/social.py, ...]
    print(result.next_steps)     # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_auth_add_social_login",
    "description": (
        "Add Google/GitHub/Apple OAuth2 social login with account linking to a FastAPI project."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_social_login",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_social_login(inp: ToolInput) -> ToolResult:
    """Add social login (Google, GitHub, Apple) to a FastAPI project.

    Writes all necessary files for OAuth2 social login: SocialAuthProvider
    with lazy httpx, SocialAccount model, schemas, routes, and Alembic migration.
    Account linking matches by verified email; falls back to creating a new user.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    model_file = app_dir / "models" / "social_account.py"
    if model_file.exists() and "SocialAccount" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SocialAccount model already present — social login already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) ----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create social login files (Google, GitHub, Apple).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: SocialAccount model
    _write_model(model_file)
    files_created.append(str(model_file))

    # Register in app/models/__init__.py
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("social_account", "SocialAccount")],
    )

    # Step 2: social_config.py
    social_config_file = app_dir / "auth" / "social_config.py"
    _write_social_config(social_config_file)
    files_created.append(str(social_config_file))

    # Step 3: social.py — SocialAuthProvider with lazy httpx
    social_file = app_dir / "auth" / "social.py"
    _write_social_auth(social_file)
    files_created.append(str(social_file))

    # Ensure app/auth/__init__.py exists
    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    # Step 4: Schemas
    schema_file = app_dir / "schemas" / "social.py"
    _write_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 5: Routes
    routes_file = app_dir / "api" / "routes" / "social_auth.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 6: Register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 7: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration = _write_migration(versions_dir)
        files_created.append(str(migration))

    # Step 8: Patch config with new settings fields
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        if str(config_file) not in files_modified:
            files_modified.append(str(config_file))

    # --- ast.parse validation (BEFORE success return) -----------------------
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Providers enabled: Google, GitHub, Apple.",
            "Account linking: email-based — matches existing user by verified email.",
            "New users auto-provisioned when no email match found.",
            "httpx imported lazily inside provider methods (no top-level SDK import).",
            "Tokens never stored; only JWT issued after successful OAuth exchange.",
        ],
        next_steps=[
            "Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GITHUB_CLIENT_ID, "
            "GITHUB_CLIENT_SECRET, APPLE_CLIENT_ID, APPLE_CLIENT_SECRET, "
            "APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY to settings.",
            "alembic upgrade head",
            "Set SOCIAL_LOGIN_CALLBACK_BASE_URL to your public domain.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return wall-clock milliseconds elapsed since *start*.

    Args:
        start: Value from ``time.monotonic()`` captured at function entry.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to the models __init__.py file.
        class_imports: List of (module_name, ClassName) pairs to import.
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject social login config fields into Settings class idempotently.

    Args:
        config_file: Path to app/core/config.py.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("GOOGLE_CLIENT_ID", 'GOOGLE_CLIENT_ID: str = ""'),
            ("GOOGLE_CLIENT_SECRET", 'GOOGLE_CLIENT_SECRET: str = ""'),
            ("GITHUB_CLIENT_ID", 'GITHUB_CLIENT_ID: str = ""'),
            ("GITHUB_CLIENT_SECRET", 'GITHUB_CLIENT_SECRET: str = ""'),
            ("APPLE_CLIENT_ID", 'APPLE_CLIENT_ID: str = ""'),
            ("APPLE_CLIENT_SECRET", 'APPLE_CLIENT_SECRET: str = ""'),
            ("APPLE_TEAM_ID", 'APPLE_TEAM_ID: str = ""'),
            ("APPLE_KEY_ID", 'APPLE_KEY_ID: str = ""'),
            ("APPLE_PRIVATE_KEY", 'APPLE_PRIVATE_KEY: str = ""'),
            ("SOCIAL_LOGIN_CALLBACK_BASE_URL", 'SOCIAL_LOGIN_CALLBACK_BASE_URL: str = "http://localhost:8000"'),
        ],
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register social_auth router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Path to app/routes/__init__.py.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.social_auth import router as social_auth_router"
    include_line = "api_router.include_router(social_auth_router)"
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _write_model(dest: Path) -> None:
    """Write app/models/social_account.py with the SocialAccount SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for linked social login accounts.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            CheckConstraint,
            DateTime,
            ForeignKey,
            String,
            UniqueConstraint,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class SocialAccount(Base):
            \"\"\"Linked social provider account for a user.

            One user may have multiple rows (one per provider).  Tokens are
            never persisted; only the provider user ID and email are stored.

            Attributes:
                id: Primary key UUID.
                provider: Provider name (google | github | apple).
                provider_user_id: Stable unique ID issued by the provider.
                provider_email: Email reported by provider at last login.
                user_id: FK to users.id (CASCADE DELETE).
                created_at: Immutable creation timestamp.
                updated_at: Updated on every login.
            \"\"\"

            __tablename__ = "social_accounts"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            provider: Mapped[str] = mapped_column(String(32), nullable=False)
            provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
            provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
            )

            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            updated_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )

            __table_args__ = (
                UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_user"),
                CheckConstraint(
                    "provider IN ('google','github','apple')",
                    name="ck_social_provider",
                ),
            )
    """)
    dest.write_text(content)


def _write_social_config(dest: Path) -> None:
    """Write app/auth/social_config.py with provider configuration dataclasses.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Social login provider configuration.\"\"\"

        from __future__ import annotations

        from dataclasses import dataclass


        @dataclass(frozen=True)
        class ProviderConfig:
            \"\"\"OAuth2 provider configuration.

            Attributes:
                name: Provider identifier (google, github, apple).
                auth_url: Provider's authorization endpoint.
                token_url: Provider's token endpoint.
                userinfo_url: Provider's userinfo endpoint.
                scopes: List of OAuth2 scopes to request.
            \"\"\"

            name: str
            auth_url: str
            token_url: str
            userinfo_url: str
            scopes: list[str]


        PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
            "google": ProviderConfig(
                name="google",
                auth_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
                scopes=["openid", "email", "profile"],
            ),
            "github": ProviderConfig(
                name="github",
                auth_url="https://github.com/login/oauth/authorize",
                token_url="https://github.com/login/oauth/access_token",
                userinfo_url="https://api.github.com/user",
                scopes=["read:user", "user:email"],
            ),
            "apple": ProviderConfig(
                name="apple",
                auth_url="https://appleid.apple.com/auth/authorize",
                token_url="https://appleid.apple.com/auth/token",
                userinfo_url="",
                scopes=["name", "email"],
            ),
        }


        def get_provider_config(provider: str) -> ProviderConfig:
            \"\"\"Return config for the named provider.

            Args:
                provider: Provider name (google, github, or apple).

            Returns:
                ``ProviderConfig`` for the given provider.

            Raises:
                ValueError: If the provider name is not recognized.
            \"\"\"
            if provider not in PROVIDER_CONFIGS:
                raise ValueError(f"Unknown social provider: {provider!r}")
            return PROVIDER_CONFIGS[provider]
    """)
    dest.write_text(content)


def _write_social_auth(dest: Path) -> None:
    """Write app/auth/social.py with SocialAuthProvider and lazy httpx.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Social authentication provider with lazy httpx import.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import secrets
        from dataclasses import dataclass
        from urllib.parse import urlencode

        from app.auth.social_config import get_provider_config

        logger = logging.getLogger(__name__)


        @dataclass
        class SocialUserInfo:
            \"\"\"Normalized user information from a social provider.

            Attributes:
                provider: Provider name (google, github, apple).
                provider_user_id: Stable unique identifier from provider.
                email: User email address (may be None for Apple).
                email_verified: Whether the provider verified this email.
                name: Display name from provider (may be None).
            \"\"\"

            provider: str
            provider_user_id: str
            email: str | None
            email_verified: bool
            name: str | None


        class SocialAuthProvider:
            \"\"\"OAuth2 social login provider.

            Handles authorization URL generation and token exchange for
            Google, GitHub, and Apple. Uses lazy httpx import so the app
            boots without the library installed.

            Args:
                provider: Provider name (google, github, apple).
            \"\"\"

            def __init__(self, provider: str) -> None:
                \"\"\"Initialize provider.

                Args:
                    provider: One of 'google', 'github', 'apple'.
                \"\"\"
                self._config = get_provider_config(provider)
                self._provider = provider

            def build_authorization_url(self, redirect_uri: str) -> tuple[str, str]:
                \"\"\"Build the provider's OAuth2 authorization redirect URL.

                Args:
                    redirect_uri: Callback URL registered with the provider.

                Returns:
                    Tuple of (authorization_url, state_token).
                \"\"\"
                state = secrets.token_urlsafe(32)
                client_id = os.environ.get(
                    f"{self._provider.upper()}_CLIENT_ID", ""
                )
                params: dict[str, str] = {
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "scope": " ".join(self._config.scopes),
                    "state": state,
                    "response_type": "code",
                }
                if self._provider == "google":
                    params["access_type"] = "offline"
                    params["prompt"] = "consent"
                if self._provider == "apple":
                    params["response_mode"] = "form_post"
                url = f"{self._config.auth_url}?{urlencode(params)}"
                return url, state

            async def exchange_code(
                self, code: str, redirect_uri: str
            ) -> SocialUserInfo:
                \"\"\"Exchange an authorization code for user info.

                Calls the provider's token endpoint then userinfo endpoint.
                httpx is imported lazily inside this method.

                Args:
                    code: Authorization code from the callback query string.
                    redirect_uri: Must match the value used in build_authorization_url.

                Returns:
                    ``SocialUserInfo`` with normalized user data.

                Raises:
                    ValueError: If the provider returns an error.
                \"\"\"
                import httpx  # lazy import — not required at app boot

                client_id = os.environ.get(f"{self._provider.upper()}_CLIENT_ID", "")
                client_secret = os.environ.get(
                    f"{self._provider.upper()}_CLIENT_SECRET", ""
                )
                async with httpx.AsyncClient(timeout=10.0) as client:
                    token_data = await _fetch_token(
                        client, self._config.token_url,
                        client_id, client_secret, code, redirect_uri,
                        self._provider,
                    )
                    access_token = token_data.get("access_token", "")
                    if self._provider == "apple":
                        return _parse_apple_id_token(token_data, self._provider)
                    return await _fetch_userinfo(
                        client, self._config.userinfo_url,
                        access_token, self._provider,
                    )


        async def _fetch_token(
            client: object,
            token_url: str,
            client_id: str,
            client_secret: str,
            code: str,
            redirect_uri: str,
            provider: str,
        ) -> dict:
            \"\"\"POST to the token endpoint and return the JSON response.

            Args:
                client: httpx.AsyncClient instance.
                token_url: Provider's token endpoint URL.
                client_id: OAuth2 client identifier.
                client_secret: OAuth2 client secret.
                code: Authorization code to exchange.
                redirect_uri: Redirect URI matching the authorization request.
                provider: Provider name for header selection.

            Returns:
                Parsed JSON response dict from the token endpoint.
            \"\"\"
            headers: dict[str, str] = {}
            if provider == "github":
                headers["Accept"] = "application/json"
            resp = await client.post(  # type: ignore[union-attr]
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()


        async def _fetch_userinfo(
            client: object,
            userinfo_url: str,
            access_token: str,
            provider: str,
        ) -> SocialUserInfo:
            \"\"\"Fetch normalized user info from the provider's userinfo endpoint.

            Args:
                client: httpx.AsyncClient instance.
                userinfo_url: Provider's userinfo endpoint URL.
                access_token: Access token from token exchange.
                provider: Provider name for field mapping.

            Returns:
                ``SocialUserInfo`` with provider, id, email, verified, name.
            \"\"\"
            resp = await client.get(  # type: ignore[union-attr]
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            if provider == "google":
                return SocialUserInfo(
                    provider=provider,
                    provider_user_id=data["sub"],
                    email=data.get("email"),
                    email_verified=data.get("email_verified", False),
                    name=data.get("name"),
                )
            # GitHub
            email = data.get("email") or ""
            return SocialUserInfo(
                provider=provider,
                provider_user_id=str(data["id"]),
                email=email or None,
                email_verified=bool(email),
                name=data.get("name"),
            )


        def _parse_apple_id_token(token_data: dict, provider: str) -> SocialUserInfo:
            \"\"\"Extract user info from Apple's id_token JWT (no userinfo endpoint).

            Apple returns user info inside the id_token JWT claims.  We decode
            only the payload (no signature verification — server-side flow).

            Args:
                token_data: Full response dict from Apple's token endpoint.
                provider: Always 'apple'.

            Returns:
                ``SocialUserInfo`` parsed from id_token claims.
            \"\"\"
            import base64
            import json

            id_token = token_data.get("id_token", "")
            parts = id_token.split(".")
            if len(parts) < 2:
                return SocialUserInfo(
                    provider=provider,
                    provider_user_id="",
                    email=None,
                    email_verified=False,
                    name=None,
                )
            padding = 4 - len(parts[1]) % 4
            payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * padding)
            claims = json.loads(payload_bytes)
            return SocialUserInfo(
                provider=provider,
                provider_user_id=claims.get("sub", ""),
                email=claims.get("email"),
                email_verified=claims.get("email_verified", False),
                name=None,
            )
    """)
    dest.write_text(content)


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/social.py with Pydantic schemas for social login.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for social login endpoints.\"\"\"

        from __future__ import annotations

        import uuid

        from pydantic import BaseModel, ConfigDict


        class SocialAccountRead(BaseModel):
            \"\"\"Public representation of a linked social account.

            Attributes:
                id: Primary key UUID.
                provider: Provider name (google, github, apple).
                provider_email: Email reported by the provider.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            provider: str
            provider_email: str | None


        class SocialLoginCallbackResponse(BaseModel):
            \"\"\"Response returned after a successful social login callback.

            Attributes:
                access_token: JWT access token.
                token_type: Always 'bearer'.
                user_id: UUID of the authenticated (or newly created) user.
                is_new_user: True when a new account was created.
            \"\"\"

            access_token: str
            token_type: str = "bearer"
            user_id: uuid.UUID
            is_new_user: bool
    """)
    dest.write_text(content)


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/social_auth.py with login + callback endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""        \"\"\"Social login routes: redirect and callback.\"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, Depends, HTTPException, Query
        from fastapi.responses import RedirectResponse
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.session import get_session
        from app.schemas.social import SocialLoginCallbackResponse

        logger = logging.getLogger(__name__)
        router = APIRouter(prefix="/auth", tags=["social-login"])

        _VALID_PROVIDERS = frozenset({"google", "github", "apple"})


        @router.get("/{provider}/login")
        async def social_login(
            provider: str,
            return_to: str = Query(default="/", description="Post-login redirect path"),
        ) -> RedirectResponse:
            \"\"\"Redirect user to the provider's OAuth2 authorization page.

            Args:
                provider: One of google, github, apple.
                return_to: Path to redirect to after login (must start with '/').

            Returns:
                RedirectResponse to the provider authorization URL.

            Raises:
                HTTPException 400: Unknown provider or unsafe return_to.
            \"\"\"
            if provider not in _VALID_PROVIDERS:
                raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
            if not return_to.startswith("/"):
                raise HTTPException(status_code=400, detail="return_to must start with '/'")
            base_url = _get_callback_base()
            redirect_uri = f"{base_url}/auth/{provider}/callback"
            from app.auth.social import SocialAuthProvider
            auth_url, _state = SocialAuthProvider(provider).build_authorization_url(
                redirect_uri
            )
            return RedirectResponse(url=auth_url)


        @router.get("/{provider}/callback", response_model=SocialLoginCallbackResponse)
        async def social_callback(
            provider: str,
            code: str = Query(..., description="Authorization code from provider"),
            state: str = Query(default="", description="CSRF state token"),
            session: AsyncSession = Depends(get_session),
        ) -> SocialLoginCallbackResponse:
            \"\"\"Handle OAuth2 callback, link or create user, and return JWT.

            Args:
                provider: One of google, github, apple.
                code: Authorization code from the provider callback.
                state: CSRF state token.
                session: SQLAlchemy async session dependency.

            Returns:
                \'SocialLoginCallbackResponse\' with JWT and user metadata.

            Raises:
                HTTPException 400: Unknown provider or unverified email.
                HTTPException 500: Provider exchange failed.
            \"\"\"
            if provider not in _VALID_PROVIDERS:
                raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
            user_info = await _exchange_social_code(
                provider, code, _get_callback_base()
            )
            if not user_info.email_verified and user_info.email:
                raise HTTPException(
                    status_code=400,
                    detail={"detail": "Provider email is not verified"},
                )
            return await _resolve_social_user(session, provider, user_info)


        async def _exchange_social_code(
            provider: str, code: str, base_url: str
        ) -> object:
            \"\"\"Exchange authorization code for user info.

            Args:
                provider: Provider name string.
                code: Authorization code from callback.
                base_url: Base URL for building redirect_uri.

            Returns:
                SocialUserInfo from the provider.

            Raises:
                HTTPException 500: If the exchange fails.
            \"\"\"
            from app.auth.social import SocialAuthProvider
            redirect_uri = f"{base_url}/auth/{provider}/callback"
            try:
                return await SocialAuthProvider(provider).exchange_code(code, redirect_uri)
            except Exception as exc:
                logger.error("Social login exchange failed: %s", exc)
                raise HTTPException(
                    status_code=500,
                    detail={"detail": "Provider token exchange failed"},
                ) from exc


        async def _resolve_social_user(
            session: AsyncSession,
            provider: str,
            user_info: object,
        ) -> SocialLoginCallbackResponse:
            \"\"\"Find or create user and social account, return JWT.

            Args:
                session: Active async session.
                provider: Provider name string.
                user_info: SocialUserInfo from provider exchange.

            Returns:
                SocialLoginCallbackResponse with JWT and user metadata.
            \"\"\"
            from app.api.routes._social_crud import (
                find_social_account,
                create_social_account,
                find_user_by_email,
                create_user_for_social,
            )
            existing = await find_social_account(
                session, provider, user_info.provider_user_id  # type: ignore[union-attr]
            )
            if existing:
                return SocialLoginCallbackResponse(
                    access_token=_mint_jwt(existing.user_id),
                    user_id=existing.user_id,
                    is_new_user=False,
                )
            user_id = None
            is_new = False
            if user_info.email:  # type: ignore[union-attr]
                user_id = await find_user_by_email(session, user_info.email)  # type: ignore[union-attr]
            if user_id is None:
                user_id = await create_user_for_social(
                    session, user_info.email, user_info.name  # type: ignore[union-attr]
                )
                is_new = True
            await create_social_account(
                session, provider,
                user_info.provider_user_id,  # type: ignore[union-attr]
                user_info.email, user_id,  # type: ignore[union-attr]
            )
            return SocialLoginCallbackResponse(
                access_token=_mint_jwt(user_id), user_id=user_id, is_new_user=is_new
            )


        def _get_callback_base() -> str:
            \"\"\"Return the configured callback base URL.

            Returns:
                Base URL string from environment or settings.
            \"\"\"
            import os
            return os.environ.get("SOCIAL_LOGIN_CALLBACK_BASE_URL", "http://localhost:8000")


        def _mint_jwt(user_id: object) -> str:
            \"\"\"Create a JWT access token for the authenticated user.

            Args:
                user_id: UUID of the user to encode in the token.

            Returns:
                Signed JWT string.
            \"\"\"
            from app.core.security import create_access_token
            return create_access_token(subject=str(user_id))
    """)
    dest.write_text(content)

    # Write the CRUD helper used by the routes (kept small)
    crud_file = dest.parent / "_social_crud.py"
    _write_social_crud(crud_file)

def _write_social_crud(dest: Path) -> None:
    """Write app/api/routes/_social_crud.py with DB helpers for social login.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"DB helpers for social login routes (not a public API).\"\"\"

        from __future__ import annotations

        import logging
        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.social_account import SocialAccount

        logger = logging.getLogger(__name__)


        async def find_social_account(
            session: AsyncSession,
            provider: str,
            provider_user_id: str,
        ) -> SocialAccount | None:
            \"\"\"Return an existing SocialAccount row or None.

            Args:
                session: Active async database session.
                provider: Provider name string.
                provider_user_id: Provider's stable user identifier.

            Returns:
                ``SocialAccount`` row if found, else ``None``.
            \"\"\"
            stmt = select(SocialAccount).where(
                SocialAccount.provider == provider,
                SocialAccount.provider_user_id == provider_user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()


        async def create_social_account(
            session: AsyncSession,
            provider: str,
            provider_user_id: str,
            provider_email: str | None,
            user_id: uuid.UUID,
        ) -> SocialAccount:
            \"\"\"Insert a new SocialAccount row and flush.

            Args:
                session: Active async database session.
                provider: Provider name string.
                provider_user_id: Provider's stable user identifier.
                provider_email: Email address from the provider (may be None).
                user_id: UUID of the user to link to.

            Returns:
                The newly created ``SocialAccount`` instance.
            \"\"\"
            account = SocialAccount(
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
                user_id=user_id,
            )
            session.add(account)
            await session.flush()
            return account


        async def find_user_by_email(
            session: AsyncSession, email: str
        ) -> uuid.UUID | None:
            \"\"\"Return the user UUID matching *email*, or None.

            Args:
                session: Active async database session.
                email: Email address to look up.

            Returns:
                User UUID if found, else ``None``.
            \"\"\"
            from sqlalchemy import text

            result = await session.execute(
                text("SELECT id FROM users WHERE email = :email LIMIT 1"),
                {"email": email},
            )
            row = result.fetchone()
            if row is None:
                return None
            return uuid.UUID(str(row[0]))


        async def create_user_for_social(
            session: AsyncSession,
            email: str | None,
            name: str | None,
        ) -> uuid.UUID:
            \"\"\"Create a minimal user row for a social-only account.

            Args:
                session: Active async database session.
                email: Email from the provider (may be None for Apple).
                name: Display name from the provider (may be None).

            Returns:
                UUID of the newly created user.
            \"\"\"
            from sqlalchemy import text

            new_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO users (id, email, full_name, hashed_password, is_active)"
                    " VALUES (:id, :email, :name, '', true)"
                ),
                {"id": str(new_id), "email": email or "", "name": name or ""},
            )
            await session.flush()
            return new_id
    """)
    dest.write_text(content)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the social_accounts table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent(f"""\
        \"\"\"Add social_accounts table for social login.

        Revision ID: 0074_add_social_login
        Revises: {down_rev}
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0074_add_social_login"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create social_accounts table.\"\"\"
            op.create_table(
                "social_accounts",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("provider_user_id", sa.String(255), nullable=False),
                sa.Column("provider_email", sa.String(320), nullable=True),
                sa.Column("user_id", sa.Uuid(), nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.ForeignKeyConstraint(
                    ["user_id"], ["users.id"], ondelete="CASCADE"
                ),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint(
                    "provider", "provider_user_id", name="uq_social_provider_user"
                ),
                sa.CheckConstraint(
                    "provider IN ('google','github','apple')",
                    name="ck_social_provider",
                ),
            )
            op.create_index("ix_social_accounts_user_id", "social_accounts", ["user_id"])


        def downgrade() -> None:
            \"\"\"Drop social_accounts table.\"\"\"
            op.drop_index("ix_social_accounts_user_id", table_name="social_accounts")
            op.drop_table("social_accounts")
    """)
    migration_file = versions_dir / "0074_add_social_login.py"
    migration_file.write_text(content)
    return migration_file
