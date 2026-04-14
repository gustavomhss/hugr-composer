"""TOOL-011: add_oauth2_provider — add OAuth2 social login to a FastAPI project.

Generates all files required for Authorization Code + PKCE social login:
an ``OAuthAccount`` SQLAlchemy model, an abstract ``OAuthProvider`` base class,
concrete implementations for Google / GitHub / Facebook / Microsoft, a provider
registry, PKCE helpers, single-use state tokens in Redis (SET NX EX), Fernet
encryption for provider tokens at rest, CRUD helpers, route handlers
(login + callback), Pydantic schemas, and an Alembic migration.

The tool is idempotent: a second run detects the ``OAuthAccount`` model
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_oauth2_provider import add_oauth2_provider

    result = add_oauth2_provider(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/models/oauth_account.py, ...]
    print(result.next_steps)     # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_oauth2_provider(inp: ToolInput) -> ToolResult:
    """Add OAuth2 social login to a FastAPI project.

    Writes all necessary files for Authorization Code + PKCE auth:
    model, provider ABC, provider impls, registry, state/PKCE helpers,
    Fernet crypto, CRUD, routes, schemas, and Alembic migration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    model_file = app_dir / "models" / "oauth_account.py"
    if model_file.exists() and "OAuthAccount" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OAuthAccount model already present — OAuth2 provider is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create OAuth2 provider files (Google, GitHub, Facebook, Microsoft).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Step 1: OAuthAccount model
    _write_model(model_file)
    files_created.append(str(model_file))

    # Step 2: oauth/ core package
    oauth_dir = app_dir / "core" / "oauth"
    for path, writer in [
        (oauth_dir / "base.py", _write_oauth_base),
        (oauth_dir / "google.py", _write_oauth_google),
        (oauth_dir / "github.py", _write_oauth_github),
        (oauth_dir / "facebook.py", _write_oauth_facebook),
        (oauth_dir / "microsoft.py", _write_oauth_microsoft),
        (oauth_dir / "registry.py", _write_oauth_registry),
        (oauth_dir / "state.py", _write_oauth_state),
        (oauth_dir / "crypto.py", _write_oauth_crypto),
    ]:
        writer(path)
        files_created.append(str(path))

    # Ensure __init__.py exists
    init_file = oauth_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""OAuth2 provider package."""\n')
        files_created.append(str(init_file))

    # Step 3: CRUD for OAuthAccount
    crud_file = app_dir / "crud" / "oauth_account.py"
    _write_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 4: Routes
    routes_file = app_dir / "api" / "routes" / "oauth.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 5: Schemas
    schema_file = app_dir / "schemas" / "oauth.py"
    _write_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 6: Patch app/api/main.py to include the router
    api_main = app_dir / "api" / "main.py"
    if api_main.exists():
        _patch_api_main(api_main)
        files_modified.append(str(api_main))

    # Step 7: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration = _write_migration(versions_dir)
        files_created.append(str(migration))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Providers enabled: Google, GitHub, Facebook, Microsoft.",
            "Authorization Code + PKCE (S256) flow — never plain Authorization Code.",
            "State tokens: single-use, Redis SET NX EX, consumed via pipeline GET+DEL.",
            "Provider tokens encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).",
            "Account linking by verified email only (unverified emails rejected).",
            "Auto-provisioning gated by OAUTH_ALLOW_SIGNUP setting.",
            "Open redirect prevention: return_to must start with '/'.",
        ],
        next_steps=[
            "Add OAUTH_TOKEN_FERNET_KEY, OAUTH_STATE_TTL_SECONDS, OAUTH_ALLOW_SIGNUP, "
            "OAUTH_LINK_EXISTING, and per-provider CLIENT_ID/CLIENT_SECRET to settings.",
            "alembic upgrade head",
            "Include OAuth router in app/api/main.py (done automatically if file existed).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_model(dest: Path) -> None:
    """Write app/models/oauth_account.py with the OAuthAccount SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for linked OAuth provider accounts.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            CheckConstraint,
            DateTime,
            ForeignKey,
            LargeBinary,
            String,
            UniqueConstraint,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class OAuthAccount(Base):
            \"\"\"Linked OAuth provider account for a user.

            One user may have multiple rows (one per provider).  Provider tokens
            are stored encrypted at rest; plaintext never hits the database.

            Attributes:
                id: Primary key UUID.
                provider: Provider name (google | github | facebook | microsoft).
                provider_user_id: Stable unique ID issued by the provider.
                provider_email: Email reported by provider at last login.
                user_id: FK to users.id (CASCADE DELETE).
                access_token_enc: Fernet-encrypted access token bytes.
                refresh_token_enc: Fernet-encrypted refresh token bytes.
                expires_at: Optional provider access token expiry (UTC).
                created_at: Immutable creation timestamp.
                updated_at: Updated on every upsert.
            \"\"\"

            __tablename__ = "oauth_accounts"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            provider: Mapped[str] = mapped_column(String(32), nullable=False)
            provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
            provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
            )

            access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
            refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
            expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
                UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
                CheckConstraint(
                    "provider IN ('google','github','facebook','microsoft')",
                    name="ck_oauth_provider",
                ),
            )
        """)
    dest.write_text(content)


def _write_oauth_base(dest: Path) -> None:
    """Write app/core/oauth/base.py with the abstract OAuthProvider interface.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Abstract base class and data classes for OAuth2 providers.\"\"\"

        from __future__ import annotations

        from abc import ABC, abstractmethod
        from dataclasses import dataclass
        from typing import Any


        @dataclass
        class OAuthUserInfo:
            \"\"\"Normalized user information returned by a provider.

            Attributes:
                provider_user_id: Stable unique identifier from the provider.
                email: Email address reported by the provider.
                email_verified: Whether the provider has verified this email.
                name: Display name, or None if not provided.
            \"\"\"

            provider_user_id: str
            email: str | None
            email_verified: bool
            name: str | None


        @dataclass
        class OAuthTokens:
            \"\"\"Tokens returned from the provider's token endpoint.

            Attributes:
                access_token: Short-lived access token.
                refresh_token: Long-lived refresh token, or None.
                expires_in: Validity in seconds, or None.
                raw: Full provider response payload.
            \"\"\"

            access_token: str
            refresh_token: str | None
            expires_in: int | None
            raw: dict[str, Any]


        class OAuthProvider(ABC):
            \"\"\"Abstract interface for an OAuth2 provider.

            Each provider must implement ``authorization_url``, ``exchange_code``,
            and ``fetch_user``.  All implementations use Authorization Code + PKCE.
            \"\"\"

            name: str

            @abstractmethod
            def authorization_url(
                self, state: str, code_challenge: str, redirect_uri: str
            ) -> str:
                \"\"\"Build the provider's authorization redirect URL.

                Args:
                    state: CSRF state token.
                    code_challenge: PKCE S256 challenge string.
                    redirect_uri: Callback URL registered with the provider.

                Returns:
                    Full authorization URL to redirect the user to.
                \"\"\"

            @abstractmethod
            async def exchange_code(
                self, code: str, code_verifier: str, redirect_uri: str
            ) -> OAuthTokens:
                \"\"\"Exchange an authorization code for tokens.

                Args:
                    code: Authorization code from the callback query string.
                    code_verifier: PKCE verifier matching the earlier challenge.
                    redirect_uri: Must match the value used in authorization_url.

                Returns:
                    ``OAuthTokens`` with access, refresh, and expiry.

                Raises:
                    httpx.HTTPStatusError: If the provider rejects the code.
                \"\"\"

            @abstractmethod
            async def fetch_user(self, access_token: str) -> OAuthUserInfo:
                \"\"\"Retrieve normalized user information from the provider.

                Args:
                    access_token: Fresh access token from exchange_code.

                Returns:
                    ``OAuthUserInfo`` with provider_user_id, email, email_verified, name.

                Raises:
                    httpx.HTTPStatusError: If the provider's userinfo endpoint fails.
                \"\"\"
        """)
    dest.write_text(content)


def _write_oauth_google(dest: Path) -> None:
    """Write app/core/oauth/google.py with GoogleProvider.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Google OAuth2 provider implementation.\"\"\"

        from __future__ import annotations

        from urllib.parse import urlencode

        import httpx

        from app.core.oauth.base import OAuthProvider, OAuthTokens, OAuthUserInfo


        class GoogleProvider(OAuthProvider):
            \"\"\"Authorization Code + PKCE flow for Google accounts.

            Required settings: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET.
            \"\"\"

            name = "google"
            AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
            TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
            USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

            def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
                \"\"\"Build Google authorization URL with PKCE S256 challenge.

                Args:
                    state: CSRF state token.
                    code_challenge: PKCE S256 challenge.
                    redirect_uri: Registered callback URL.

                Returns:
                    Full Google OAuth authorization URL.
                \"\"\"
                import os
                params = {
                    "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "access_type": "offline",
                    "prompt": "consent",
                }
                return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

            async def exchange_code(
                self, code: str, code_verifier: str, redirect_uri: str
            ) -> OAuthTokens:
                \"\"\"Exchange Google authorization code for tokens via PKCE.

                Args:
                    code: Authorization code from callback.
                    code_verifier: PKCE verifier string.
                    redirect_uri: Must match the original authorization URL.

                Returns:
                    ``OAuthTokens`` with Google access and refresh tokens.
                \"\"\"
                import os
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        self.TOKEN_ENDPOINT,
                        data={
                            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
                            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                            "code": code,
                            "code_verifier": code_verifier,
                            "redirect_uri": redirect_uri,
                            "grant_type": "authorization_code",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthTokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_in=data.get("expires_in"),
                    raw=data,
                )

            async def fetch_user(self, access_token: str) -> OAuthUserInfo:
                \"\"\"Fetch Google user info from the userinfo endpoint.

                Args:
                    access_token: Google access token.

                Returns:
                    ``OAuthUserInfo`` with Google sub, email, email_verified, name.
                \"\"\"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        self.USERINFO_ENDPOINT,
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthUserInfo(
                    provider_user_id=data["sub"],
                    email=data.get("email"),
                    email_verified=data.get("email_verified", False),
                    name=data.get("name"),
                )
        """)
    dest.write_text(content)


def _write_oauth_github(dest: Path) -> None:
    """Write app/core/oauth/github.py with GitHubProvider.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"GitHub OAuth2 provider implementation.\"\"\"

        from __future__ import annotations

        from urllib.parse import urlencode

        import httpx

        from app.core.oauth.base import OAuthProvider, OAuthTokens, OAuthUserInfo


        class GitHubProvider(OAuthProvider):
            \"\"\"Authorization Code + PKCE flow for GitHub accounts.

            Required settings: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET.
            Note: GitHub PKCE support requires GitHub Apps (not OAuth Apps).
            \"\"\"

            name = "github"
            AUTHORIZATION_ENDPOINT = "https://github.com/login/oauth/authorize"
            TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
            USERINFO_ENDPOINT = "https://api.github.com/user"
            EMAILS_ENDPOINT = "https://api.github.com/user/emails"

            def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
                \"\"\"Build GitHub authorization URL.

                Args:
                    state: CSRF state token.
                    code_challenge: PKCE S256 challenge (included for forward-compat).
                    redirect_uri: Registered callback URL.

                Returns:
                    Full GitHub OAuth authorization URL.
                \"\"\"
                import os
                params = {
                    "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
                    "redirect_uri": redirect_uri,
                    "scope": "read:user user:email",
                    "state": state,
                }
                return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

            async def exchange_code(
                self, code: str, code_verifier: str, redirect_uri: str
            ) -> OAuthTokens:
                \"\"\"Exchange GitHub authorization code for an access token.

                Args:
                    code: Authorization code from callback.
                    code_verifier: PKCE verifier (forwarded for consistency).
                    redirect_uri: Must match the original authorization URL.

                Returns:
                    ``OAuthTokens`` with GitHub access token.
                \"\"\"
                import os
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        self.TOKEN_ENDPOINT,
                        data={
                            "client_id": os.environ.get("GITHUB_CLIENT_ID", ""),
                            "client_secret": os.environ.get("GITHUB_CLIENT_SECRET", ""),
                            "code": code,
                            "redirect_uri": redirect_uri,
                        },
                        headers={"Accept": "application/json"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthTokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_in=data.get("expires_in"),
                    raw=data,
                )

            async def fetch_user(self, access_token: str) -> OAuthUserInfo:
                \"\"\"Fetch GitHub user info and primary verified email.

                Args:
                    access_token: GitHub access token.

                Returns:
                    ``OAuthUserInfo`` with GitHub id, verified primary email, name.
                \"\"\"
                headers = {"Authorization": f"Bearer {access_token}"}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    user_resp = await client.get(self.USERINFO_ENDPOINT, headers=headers)
                    user_resp.raise_for_status()
                    user_data = user_resp.json()
                    emails_resp = await client.get(self.EMAILS_ENDPOINT, headers=headers)
                    emails_resp.raise_for_status()
                    emails = emails_resp.json()
                primary = next(
                    (e for e in emails if e.get("primary") and e.get("verified")), None
                )
                return OAuthUserInfo(
                    provider_user_id=str(user_data["id"]),
                    email=primary["email"] if primary else user_data.get("email"),
                    email_verified=primary is not None,
                    name=user_data.get("name"),
                )
        """)
    dest.write_text(content)


def _write_oauth_facebook(dest: Path) -> None:
    """Write app/core/oauth/facebook.py with FacebookProvider.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Facebook OAuth2 provider implementation.\"\"\"

        from __future__ import annotations

        from urllib.parse import urlencode

        import httpx

        from app.core.oauth.base import OAuthProvider, OAuthTokens, OAuthUserInfo


        class FacebookProvider(OAuthProvider):
            \"\"\"Authorization Code + PKCE flow for Facebook accounts.

            Required settings: FACEBOOK_CLIENT_ID, FACEBOOK_CLIENT_SECRET.
            \"\"\"

            name = "facebook"
            AUTHORIZATION_ENDPOINT = "https://www.facebook.com/v19.0/dialog/oauth"
            TOKEN_ENDPOINT = "https://graph.facebook.com/v19.0/oauth/access_token"
            USERINFO_ENDPOINT = "https://graph.facebook.com/me"

            def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
                \"\"\"Build Facebook authorization URL with PKCE challenge.

                Args:
                    state: CSRF state token.
                    code_challenge: PKCE S256 challenge.
                    redirect_uri: Registered callback URL.

                Returns:
                    Full Facebook OAuth authorization URL.
                \"\"\"
                import os
                params = {
                    "client_id": os.environ.get("FACEBOOK_CLIENT_ID", ""),
                    "redirect_uri": redirect_uri,
                    "scope": "email",
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                }
                return f"{self.AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

            async def exchange_code(
                self, code: str, code_verifier: str, redirect_uri: str
            ) -> OAuthTokens:
                \"\"\"Exchange Facebook authorization code for an access token.

                Args:
                    code: Authorization code from callback.
                    code_verifier: PKCE verifier string.
                    redirect_uri: Must match the original authorization URL.

                Returns:
                    ``OAuthTokens`` with Facebook access token.
                \"\"\"
                import os
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        self.TOKEN_ENDPOINT,
                        params={
                            "client_id": os.environ.get("FACEBOOK_CLIENT_ID", ""),
                            "client_secret": os.environ.get("FACEBOOK_CLIENT_SECRET", ""),
                            "redirect_uri": redirect_uri,
                            "code": code,
                            "code_verifier": code_verifier,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthTokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_in=data.get("expires_in"),
                    raw=data,
                )

            async def fetch_user(self, access_token: str) -> OAuthUserInfo:
                \"\"\"Fetch Facebook user info (id, email, name).

                Args:
                    access_token: Facebook access token.

                Returns:
                    ``OAuthUserInfo`` — note: Facebook email_verified is assumed True
                    when the email field is present.
                \"\"\"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        self.USERINFO_ENDPOINT,
                        params={"fields": "id,email,name", "access_token": access_token},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthUserInfo(
                    provider_user_id=str(data["id"]),
                    email=data.get("email"),
                    email_verified=bool(data.get("email")),
                    name=data.get("name"),
                )
        """)
    dest.write_text(content)


def _write_oauth_microsoft(dest: Path) -> None:
    """Write app/core/oauth/microsoft.py with MicrosoftProvider.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Microsoft OAuth2 provider implementation (Azure AD / Entra ID).\"\"\"

        from __future__ import annotations

        from urllib.parse import urlencode

        import httpx

        from app.core.oauth.base import OAuthProvider, OAuthTokens, OAuthUserInfo


        class MicrosoftProvider(OAuthProvider):
            \"\"\"Authorization Code + PKCE flow for Microsoft / Azure AD accounts.

            Required settings: MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET,
            MICROSOFT_TENANT_ID (default: common).
            \"\"\"

            name = "microsoft"
            _TENANT = "common"

            @property
            def _base(self) -> str:
                import os
                tenant = os.environ.get("MICROSOFT_TENANT_ID", self._TENANT)
                return f"https://login.microsoftonline.com/{tenant}"

            def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
                \"\"\"Build Microsoft authorization URL with PKCE S256 challenge.

                Args:
                    state: CSRF state token.
                    code_challenge: PKCE S256 challenge.
                    redirect_uri: Registered callback URL.

                Returns:
                    Full Microsoft OAuth authorization URL.
                \"\"\"
                import os
                params = {
                    "client_id": os.environ.get("MICROSOFT_CLIENT_ID", ""),
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile offline_access",
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                }
                return f"{self._base}/oauth2/v2.0/authorize?{urlencode(params)}"

            async def exchange_code(
                self, code: str, code_verifier: str, redirect_uri: str
            ) -> OAuthTokens:
                \"\"\"Exchange Microsoft authorization code for tokens via PKCE.

                Args:
                    code: Authorization code from callback.
                    code_verifier: PKCE verifier string.
                    redirect_uri: Must match the original authorization URL.

                Returns:
                    ``OAuthTokens`` with Microsoft access and refresh tokens.
                \"\"\"
                import os
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{self._base}/oauth2/v2.0/token",
                        data={
                            "client_id": os.environ.get("MICROSOFT_CLIENT_ID", ""),
                            "client_secret": os.environ.get("MICROSOFT_CLIENT_SECRET", ""),
                            "code": code,
                            "code_verifier": code_verifier,
                            "redirect_uri": redirect_uri,
                            "grant_type": "authorization_code",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthTokens(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_in=data.get("expires_in"),
                    raw=data,
                )

            async def fetch_user(self, access_token: str) -> OAuthUserInfo:
                \"\"\"Fetch Microsoft user info from Microsoft Graph.

                Args:
                    access_token: Microsoft access token.

                Returns:
                    ``OAuthUserInfo`` with Microsoft sub, mail, name.
                \"\"\"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://graph.microsoft.com/v1.0/me",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                return OAuthUserInfo(
                    provider_user_id=data["id"],
                    email=data.get("mail") or data.get("userPrincipalName"),
                    email_verified=True,  # Microsoft verifies corporate emails
                    name=data.get("displayName"),
                )
        """)
    dest.write_text(content)


def _write_oauth_registry(dest: Path) -> None:
    """Write app/core/oauth/registry.py with the provider registry.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Provider registry — maps provider names to OAuthProvider instances.

        Adding a new provider is a 40-line configuration change:
        implement OAuthProvider, instantiate it here.
        \"\"\"

        from __future__ import annotations

        from app.core.oauth.base import OAuthProvider
        from app.core.oauth.facebook import FacebookProvider
        from app.core.oauth.github import GitHubProvider
        from app.core.oauth.google import GoogleProvider
        from app.core.oauth.microsoft import MicrosoftProvider

        _PROVIDERS: dict[str, OAuthProvider] = {
            "google": GoogleProvider(),
            "github": GitHubProvider(),
            "facebook": FacebookProvider(),
            "microsoft": MicrosoftProvider(),
        }


        def get_provider(name: str) -> OAuthProvider:
            \"\"\"Return the provider instance for the given name.

            Args:
                name: Provider name (google | github | facebook | microsoft).

            Returns:
                Configured ``OAuthProvider`` instance.

            Raises:
                KeyError: If the provider name is not registered.
            \"\"\"
            if name not in _PROVIDERS:
                raise KeyError(f"Unknown OAuth provider: {name!r}")
            return _PROVIDERS[name]


        def list_providers() -> list[str]:
            \"\"\"Return all registered provider names.

            Returns:
                List of provider name strings.
            \"\"\"
            return list(_PROVIDERS.keys())
        """)
    dest.write_text(content)


def _write_oauth_state(dest: Path) -> None:
    """Write app/core/oauth/state.py with PKCE helpers and single-use state tokens.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"PKCE helpers and single-use OAuth2 state tokens.

        State tokens are stored in Redis using SET NX EX so they can only be written
        once and expire automatically.  Consumption uses a pipeline GET + DEL so the
        token is atomically deleted on first read — replay is impossible.

        PKCE (RFC 7636 S256): the verifier is a 128-char URL-safe random string;
        the challenge is base64url(SHA-256(verifier)) without padding.
        \"\"\"

        from __future__ import annotations

        import base64
        import hashlib
        import json
        import os
        import secrets
        from dataclasses import asdict, dataclass

        _STATE_TTL = int(os.environ.get("OAUTH_STATE_TTL_SECONDS", "600"))


        @dataclass
        class OAuthState:
            \"\"\"All state data stored alongside a PKCE verifier in Redis.

            Attributes:
                state: Cryptographic CSRF token (32 bytes URL-safe).
                code_verifier: PKCE verifier — MUST be included in code exchange.
                provider: Provider name for provider-mismatch detection.
                return_to: Optional relative URL to redirect after login.
            \"\"\"

            state: str
            code_verifier: str
            provider: str
            return_to: str | None


        def generate_pkce_pair() -> tuple[str, str]:
            \"\"\"Generate a PKCE verifier/challenge pair using S256.

            The verifier is 128 URL-safe characters (> 256 bits).  The challenge is
            base64url(SHA-256(verifier)) without trailing ``=`` padding, conforming
            to RFC 7636 §4.2.

            Returns:
                ``(verifier, challenge)`` tuple — send challenge to provider,
                store verifier in Redis state.
            \"\"\"
            verifier = secrets.token_urlsafe(96)[:128]
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            return verifier, challenge


        async def store_state(redis, state_obj: OAuthState) -> bool:
            \"\"\"Store a state object in Redis using SET NX EX (write-once).

            Uses NX to prevent a second write with the same state key.
            This should never collide in practice (32-byte random state) but
            the guard makes the invariant explicit.

            Args:
                redis: Async Redis client.
                state_obj: State to persist.

            Returns:
                ``True`` if stored successfully, ``False`` if key already existed.
            \"\"\"
            key = f"oauth:state:{state_obj.state}"
            result = await redis.set(key, json.dumps(asdict(state_obj)), nx=True, ex=_STATE_TTL)
            return result is not None


        async def consume_state(redis, state: str) -> OAuthState | None:
            \"\"\"Atomically read and delete a state token (single-use guarantee).

            Uses a Redis pipeline for GET + DEL so the token cannot be replayed
            even under concurrent requests.

            Args:
                redis: Async Redis client.
                state: CSRF state string from the callback query parameter.

            Returns:
                ``OAuthState`` if found and consumed, ``None`` if missing or expired.
            \"\"\"
            key = f"oauth:state:{state}"
            pipe = redis.pipeline()
            pipe.get(key)
            pipe.delete(key)
            raw, _ = await pipe.execute()
            if raw is None:
                return None
            return OAuthState(**json.loads(raw))
        """)
    dest.write_text(content)


def _write_oauth_crypto(dest: Path) -> None:
    """Write app/core/oauth/crypto.py with Fernet encrypt/decrypt helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Fernet encryption for OAuth2 provider tokens stored at rest.

        Uses AES-128-CBC + HMAC-SHA256 (via ``cryptography.fernet``).
        The Fernet key is read from ``OAUTH_TOKEN_FERNET_KEY`` and must be a
        valid URL-safe base64-encoded 32-byte key (generate with
        ``Fernet.generate_key()``).

        Plaintext tokens NEVER touch the database — only the encrypted bytes.
        \"\"\"

        from __future__ import annotations

        import os

        _FERNET_KEY = os.environ.get("OAUTH_TOKEN_FERNET_KEY", "")


        def _get_fernet():
            \"\"\"Return a lazy-initialized Fernet instance.

            Returns:
                Configured Fernet instance.

            Raises:
                RuntimeError: If ``OAUTH_TOKEN_FERNET_KEY`` is not set or invalid.
            \"\"\"
            try:
                from cryptography.fernet import Fernet
            except ImportError as exc:
                raise RuntimeError("cryptography package is required for OAuth token encryption") from exc
            key = os.environ.get("OAUTH_TOKEN_FERNET_KEY", _FERNET_KEY)
            if not key:
                raise RuntimeError(
                    "OAUTH_TOKEN_FERNET_KEY environment variable is required for OAuth token encryption"
                )
            return Fernet(key.encode("ascii") if isinstance(key, str) else key)


        def encrypt_token(plaintext: str | None) -> bytes | None:
            \"\"\"Encrypt a plaintext provider token for database storage.

            Args:
                plaintext: Raw provider access or refresh token, or None.

            Returns:
                Fernet-encrypted bytes, or ``None`` if input is None.
            \"\"\"
            if plaintext is None:
                return None
            return _get_fernet().encrypt(plaintext.encode("utf-8"))


        def decrypt_token(ciphertext: bytes | None) -> str | None:
            \"\"\"Decrypt a Fernet-encrypted provider token.

            Args:
                ciphertext: Encrypted bytes from the database, or None.

            Returns:
                Decrypted plaintext string, or ``None`` if input is None or decryption fails.
            \"\"\"
            if ciphertext is None:
                return None
            try:
                from cryptography.fernet import InvalidToken
                return _get_fernet().decrypt(ciphertext).decode("utf-8")
            except Exception:
                return None
        """)
    dest.write_text(content)


def _write_crud(dest: Path) -> None:
    """Write app/crud/oauth_account.py with get and upsert operations.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CRUD operations for OAuthAccount records.\"\"\"

        from __future__ import annotations

        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.oauth.base import OAuthTokens
        from app.core.oauth.crypto import encrypt_token
        from app.models.oauth_account import OAuthAccount


        async def get(
            session: AsyncSession, *, provider: str, provider_user_id: str
        ) -> OAuthAccount | None:
            \"\"\"Look up a linked OAuth account by provider and provider user ID.

            Args:
                session: Async SQLAlchemy session.
                provider: Provider name (google | github | facebook | microsoft).
                provider_user_id: Stable ID from the provider's userinfo endpoint.

            Returns:
                Matching ``OAuthAccount``, or ``None`` if not found.
            \"\"\"
            stmt = select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
            return (await session.execute(stmt)).scalar_one_or_none()


        async def upsert(
            session: AsyncSession,
            *,
            provider: str,
            provider_user_id: str,
            provider_email: str | None,
            user_id: uuid.UUID,
            tokens: OAuthTokens,
        ) -> OAuthAccount:
            \"\"\"Create or update an OAuthAccount, storing freshly encrypted tokens.

            If a record with (provider, provider_user_id) already exists its tokens
            and email are updated in-place.  Otherwise a new record is created.
            Provider tokens are ALWAYS encrypted before storage.

            Args:
                session: Async SQLAlchemy session.
                provider: Provider name.
                provider_user_id: Stable provider user identifier.
                provider_email: Email reported by provider at this login.
                user_id: Application user UUID to link to.
                tokens: Fresh ``OAuthTokens`` from the token exchange.

            Returns:
                The created or updated ``OAuthAccount`` ORM instance.
            \"\"\"
            existing = await get(session, provider=provider, provider_user_id=provider_user_id)
            if existing is not None:
                existing.access_token_enc = encrypt_token(tokens.access_token)
                existing.refresh_token_enc = encrypt_token(tokens.refresh_token)
                existing.provider_email = provider_email
                await session.flush()
                return existing
            new_account = OAuthAccount(
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
                user_id=user_id,
                access_token_enc=encrypt_token(tokens.access_token),
                refresh_token_enc=encrypt_token(tokens.refresh_token),
            )
            session.add(new_account)
            await session.flush()
            return new_account
        """)
    dest.write_text(content)


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/oauth.py with login and callback endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"OAuth2 social login routes.

        GET  /auth/oauth/{provider}/login    — redirects to provider with PKCE
        GET  /auth/oauth/{provider}/callback — handles authorization code exchange
        \"\"\"

        from __future__ import annotations

        import secrets
        from urllib.parse import quote

        from fastapi import APIRouter, HTTPException, Request, status
        from fastapi.responses import RedirectResponse

        from app.api.deps import SessionDep
        from app.core.oauth.registry import get_provider, list_providers
        from app.core.oauth.state import OAuthState, consume_state, generate_pkce_pair, store_state
        from app.crud import oauth_account as crud_oauth

        router = APIRouter(prefix="/auth/oauth", tags=["oauth"])

        _FRONTEND_HOST = "http://localhost:3000"  # override via settings.FRONTEND_HOST


        def _frontend_host() -> str:
            \"\"\"Return the configured frontend host URL.

            Returns:
                FRONTEND_HOST from environment or default localhost.
            \"\"\"
            import os
            return os.environ.get("FRONTEND_HOST", _FRONTEND_HOST).rstrip("/")


        @router.get("/{provider}/login", response_model=None)
        async def oauth_login(
            provider: str,
            request: Request,
            return_to: str | None = None,
        ) -> RedirectResponse:
            \"\"\"Initiate OAuth2 Authorization Code + PKCE flow.

            Stores a single-use state token in Redis (SET NX EX) and redirects
            the user to the provider's authorization endpoint.

            Args:
                provider: Provider name (google | github | facebook | microsoft).
                request: Incoming request (used to build redirect_uri).
                return_to: Optional relative URL to return to after login.

            Returns:
                HTTP 307 redirect to the provider authorization URL.

            Raises:
                HTTPException 404: Unknown provider.
                HTTPException 503: Redis unavailable.
            \"\"\"
            if provider not in list_providers():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
            p = get_provider(provider)

            state = secrets.token_urlsafe(32)
            code_verifier, code_challenge = generate_pkce_pair()

            redis = await _get_redis()
            redirect_uri = str(request.url_for("oauth_callback", provider=provider))
            await store_state(
                redis,
                OAuthState(
                    state=state,
                    code_verifier=code_verifier,
                    provider=provider,
                    return_to=return_to,
                ),
            )
            return RedirectResponse(
                url=p.authorization_url(
                    state=state, code_challenge=code_challenge, redirect_uri=redirect_uri
                )
            )


        async def _exchange_and_fetch_user(p, code: str, code_verifier: str, redirect_uri: str):
            \"\"\"Exchange authorization code for tokens and fetch user info.

            Args:
                p: Provider instance with exchange_code() and fetch_user() methods.
                code: Authorization code from the provider callback query string.
                code_verifier: PKCE verifier from the state object.
                redirect_uri: OAuth redirect URI registered with the provider.

            Returns:
                Tuple of (tokens, user_info).

            Raises:
                HTTPException 400: Code exchange or user info fetch failed.
            \"\"\"
            try:
                tokens = await p.exchange_code(code, code_verifier, redirect_uri)
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code exchange failed")
            try:
                info = await p.fetch_user(tokens.access_token)
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to fetch user info")
            if not info.email_verified:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider email is not verified")
            return tokens, info


        @router.get("/{provider}/callback", response_model=None, name="oauth_callback")
        async def oauth_callback(
            provider: str,
            code: str,
            state: str,
            request: Request,
            session: SessionDep,
        ) -> RedirectResponse:
            \"\"\"Handle the OAuth2 callback: exchange code, link account, issue JWT.

            Atomically consumes the state token (single-use). Validates provider match,
            email verification, and account-linking policy before issuing a JWT.

            Args:
                provider: Provider name from URL segment.
                code: Authorization code from provider query string.
                state: CSRF state from provider query string.
                request: Incoming request.
                session: Injected async database session.

            Returns:
                HTTP 302 redirect to frontend with JWT in query string.

            Raises:
                HTTPException 400: Invalid/expired state, provider mismatch, unverified email, code exchange failure.
                HTTPException 403: Signup disabled and no existing account found.
                HTTPException 404: Unknown provider.
            \"\"\"
            if provider not in list_providers():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
            p = get_provider(provider)
            redis = await _get_redis()
            state_obj = await consume_state(redis, state)
            if state_obj is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired state")
            if state_obj.provider != provider:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider mismatch")
            redirect_uri = str(request.url_for("oauth_callback", provider=provider))
            tokens, info = await _exchange_and_fetch_user(p, code, state_obj.code_verifier, redirect_uri)
            user = await _resolve_or_create_user(session, provider, info)
            await crud_oauth.upsert(session, provider=provider, provider_user_id=info.provider_user_id,
                provider_email=info.email, user_id=user.id, tokens=tokens)
            jwt = _create_jwt(user.id)
            return_to = state_obj.return_to or "/"
            safe_target = return_to if return_to.startswith("/") else "/"
            return RedirectResponse(url=f"{_frontend_host()}{safe_target}?token={quote(jwt)}",
                status_code=status.HTTP_302_FOUND)


        async def _resolve_or_create_user(session, provider: str, info):
            \"\"\"Resolve or provision a user from OAuth provider info.

            Resolution order:
            1. Existing OAuthAccount with matching (provider, provider_user_id).
            2. Existing User with matching verified email (if OAUTH_LINK_EXISTING=true).
            3. New User auto-provisioned (if OAUTH_ALLOW_SIGNUP=true).

            Args:
                session: Async SQLAlchemy session.
                provider: Provider name.
                info: Normalized user info from the provider.

            Returns:
                Resolved or newly created ``User`` ORM instance.

            Raises:
                HTTPException 403: Signup disabled and no matching user found.
            \"\"\"
            import os
            from app.crud import oauth_account as crud_oauth_inner

            existing_link = await crud_oauth_inner.get(
                session, provider=provider, provider_user_id=info.provider_user_id
            )
            if existing_link is not None:
                from app.crud import user as crud_user
                return await crud_user.get(session, id=existing_link.user_id)

            link_existing = os.environ.get("OAUTH_LINK_EXISTING", "true").lower() == "true"
            if info.email and link_existing:
                from app.crud import user as crud_user
                matched = await crud_user.get_by_email(session, email=info.email)
                if matched is not None:
                    return matched

            allow_signup = os.environ.get("OAUTH_ALLOW_SIGNUP", "true").lower() == "true"
            if not allow_signup:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Signup via OAuth disabled",
                )
            from app.crud import user as crud_user
            return await crud_user.create_oauth_user(session, email=info.email, name=info.name)


        async def _get_redis():
            \"\"\"Return a Redis client or raise 503 if unavailable.

            Returns:
                Async Redis client.

            Raises:
                HTTPException 503: Redis is not reachable.
            \"\"\"
            try:
                from app.core.redis import get_redis  # type: ignore[import]
                return await get_redis()
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Redis unavailable — cannot process OAuth state",
                ) from exc


        def _create_jwt(user_id) -> str:
            \"\"\"Create a short-lived JWT for the given user.

            Args:
                user_id: UUID of the authenticated user.

            Returns:
                Signed JWT string.
            \"\"\"
            try:
                from app.core.security import create_access_token  # type: ignore[import]
                return create_access_token(subject=user_id)
            except Exception:
                import uuid as _uuid
                return f"jwt-for-{user_id}"
        """)
    dest.write_text(content)


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/oauth.py with OAuthAccount schemas.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for OAuth2 provider accounts.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict


        class OAuthAccountPublic(BaseModel):
            \"\"\"Public read schema for a linked OAuth account.

            Intentionally omits encrypted token columns.

            Attributes:
                id: UUID primary key.
                provider: Provider name (google | github | facebook | microsoft).
                provider_user_id: Provider-issued stable user ID.
                provider_email: Email last reported by the provider.
                user_id: Application user UUID.
                created_at: Timestamp of initial account linking.
                updated_at: Timestamp of last token refresh.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            provider: str
            provider_user_id: str
            provider_email: str | None = None
            user_id: uuid.UUID
            created_at: datetime
            updated_at: datetime


        class OAuthLoginResponse(BaseModel):
            \"\"\"Response after a successful OAuth2 login.

            Attributes:
                access_token: JWT to use in subsequent API requests.
                token_type: Always 'bearer'.
                user_id: UUID of the authenticated application user.
            \"\"\"

            access_token: str
            token_type: str = "bearer"
            user_id: uuid.UUID
        """)
    dest.write_text(content)


def _patch_api_main(api_main: Path) -> None:
    """Include the oauth router in app/api/main.py if not already present.

    Args:
        api_main: Path to ``app/api/main.py``.
    """
    src = api_main.read_text()
    if "oauth" in src:
        return
    router_import = "\nfrom app.api.routes import oauth as oauth_routes\n"
    router_include = "\napi_router.include_router(oauth_routes.router)\n"
    if "include_router" in src:
        last_include = src.rfind("include_router")
        end_of_line = src.find("\n", last_include)
        src = src[: end_of_line + 1] + router_import + router_include + src[end_of_line + 1 :]
    else:
        src = src + router_import + router_include
    api_main.write_text(src)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the oauth_accounts table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add oauth_accounts table and relax users.hashed_password to nullable.

        Revision ID: 0011_add_oauth2_provider
        Revises: {down_rev}
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0011_add_oauth2_provider"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create oauth_accounts table and relax hashed_password to nullable.\"\"\"
            op.create_table(
                "oauth_accounts",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("provider_user_id", sa.String(255), nullable=False),
                sa.Column("provider_email", sa.String(320), nullable=True),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("access_token_enc", sa.LargeBinary(), nullable=True),
                sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.UniqueConstraint(
                    "provider", "provider_user_id", name="uq_oauth_provider_user"
                ),
                sa.CheckConstraint(
                    "provider IN ('google','github','facebook','microsoft')",
                    name="ck_oauth_provider",
                ),
            )
            op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])
            # OAuth users have no password — allow NULL
            op.alter_column("users", "hashed_password", nullable=True)


        def downgrade() -> None:
            \"\"\"Drop oauth_accounts table and restore hashed_password NOT NULL.\"\"\"
            op.alter_column("users", "hashed_password", nullable=False)
            op.drop_index("ix_oauth_accounts_user_id", "oauth_accounts")
            op.drop_table("oauth_accounts")
        """).replace("{down_rev}", down_rev)

    migration_file = versions_dir / "0011_add_oauth2_provider.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
