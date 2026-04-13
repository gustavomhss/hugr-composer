# TOOL-011: add_oauth2_provider

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_oauth2_provider` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User), Alembic, Redis (for state token), httpx |
| Signature | `add_oauth2_provider(project_dir: str, providers: list[Literal["google","github","facebook","microsoft"]], allow_signup: bool = True, link_existing: bool = True, state_ttl_seconds: int = 600) -> dict` |
| Parameters | `project_dir`: project root path<br>`providers`: list of OAuth providers to enable<br>`allow_signup`: if False, only existing users may sign in via OAuth<br>`link_existing`: if True, OAuth login matches by email and links account<br>`state_ttl_seconds`: TTL of CSRF state token in Redis |

---

## 2. Purpose

The `fastapi_add_oauth2_provider` tool adds OAuth2 social login — Google, GitHub, Facebook, Microsoft, and any additional standards-compliant provider — on top of the existing email/password authentication path so end users can click "Continue with Google" instead of maintaining yet another password. Social login is the default expectation for consumer-facing apps in 2026 and the default access pattern for many B2B SaaS apps, but a safe implementation requires CSRF-resistant state tokens, PKCE verifiers, account-linking logic that does not let a partial match hijack another user, encrypted storage of provider tokens at rest, and a provider abstraction that lets the team add a new IdP without rewriting the auth layer — all of which are subtle and dangerous to hand-roll.

This tool implements the **Authorization Code flow with PKCE (RFC 7636)** for every provider, short-lived state tokens stored in Redis (keyed on the per-request verifier with a 5-minute TTL) so a stale or missing state token aborts the callback before any user lookup, account linking by verified email only (unverified emails from providers are rejected to prevent takeover via fake Google accounts), encrypted storage of provider access and refresh tokens at rest using a Fernet key from settings so a database compromise does not expose usable downstream credentials, and an auto-provisioning path gated by `allow_signup=True` so operators can disable new signups during incident response without disabling existing social logins. Key design decisions: PKCE mandatory (never plain Authorization Code), state tokens with cryptographic binding to the client, verified-email-only linking, Fernet-encrypted token storage rotated via TOOL-005 audit_log events, and a pluggable provider registry so adding a new IdP is a 40-line configuration change rather than a new code path through the auth layer.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Dev waits in CLI |
| Files modified | ≤ 5 global files | Predictability |
| Files created | ≥ 10 (model, providers/, crud, routes, schemas, deps, encryption, migration, tests, settings) | Predictability |
| Login redirect latency | < 200 ms | Local logic; only DB hit is state token write to Redis |
| Callback latency | < 800 ms p99 | Includes 1 outbound HTTPS call to provider for code exchange |
| State token lookup | < 5 ms | Redis GET |
| Token encryption / decryption | < 1 ms | Fernet (AES-128-CBC + HMAC) |
| Migration runtime | < 5s on existing User table | One new table + nullable column on users |
| Memory overhead | < 1 MB per worker | httpx client pool |

---

## 4. Code Examples (Before / After)

### 4.1 Models (NEW)
```python
# app/models/oauth_account.py
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
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Encrypted Fernet payloads
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        CheckConstraint(
            "provider IN ('google','github','facebook','microsoft')",
            name="ck_oauth_provider",
        ),
    )
```

### 4.2 Provider abstraction (NEW)
```python
# app/core/oauth/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class OAuthUserInfo:
    provider_user_id: str
    email: str | None
    email_verified: bool
    name: str | None


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    raw: dict[str, Any]


class OAuthProvider(ABC):
    name: str

    @abstractmethod
    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        ...

    @abstractmethod
    async def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> OAuthTokens:
        ...

    @abstractmethod
    async def fetch_user(self, access_token: str) -> OAuthUserInfo:
        ...
```

```python
# app/core/oauth/google.py
import httpx

from app.core.config import settings
from app.core.oauth.base import OAuthProvider, OAuthTokens, OAuthUserInfo


class GoogleProvider(OAuthProvider):
    name = "google"

    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
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
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.TOKEN_ENDPOINT,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
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
```

(Analogous classes for `github.py`, `facebook.py`, `microsoft.py`.)

### 4.3 Provider registry (NEW)
```python
# app/core/oauth/registry.py
from app.core.oauth.base import OAuthProvider
from app.core.oauth.google import GoogleProvider
from app.core.oauth.github import GitHubProvider
from app.core.oauth.facebook import FacebookProvider
from app.core.oauth.microsoft import MicrosoftProvider

_PROVIDERS: dict[str, OAuthProvider] = {
    "google": GoogleProvider(),
    "github": GitHubProvider(),
    "facebook": FacebookProvider(),
    "microsoft": MicrosoftProvider(),
}


def get_provider(name: str) -> OAuthProvider:
    if name not in _PROVIDERS:
        raise KeyError(f"Unknown OAuth provider: {name}")
    return _PROVIDERS[name]


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())
```

### 4.4 State token + PKCE (NEW)
```python
# app/core/oauth/state.py
import base64
import hashlib
import json
import secrets
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from app.core.config import settings

STATE_TTL = settings.OAUTH_STATE_TTL_SECONDS


@dataclass
class OAuthState:
    state: str
    code_verifier: str
    provider: str
    return_to: str | None


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (verifier, challenge) using S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def store_state(redis: Redis, state_obj: OAuthState) -> None:
    await redis.setex(
        f"oauth:state:{state_obj.state}",
        STATE_TTL,
        json.dumps(asdict(state_obj)),
    )


async def consume_state(redis: Redis, state: str) -> OAuthState | None:
    """Atomic GET + DEL — state is single-use."""
    key = f"oauth:state:{state}"
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    if raw is None:
        return None
    return OAuthState(**json.loads(raw))
```

### 4.5 Token encryption (NEW)
```python
# app/core/oauth/crypto.py
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet = Fernet(settings.OAUTH_TOKEN_FERNET_KEY.encode("ascii"))


def encrypt_token(plaintext: str | None) -> bytes | None:
    if plaintext is None:
        return None
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_token(ciphertext: bytes | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _fernet.decrypt(ciphertext).decode("utf-8")
    except InvalidToken:
        return None
```

### 4.6 Routes (NEW)
```python
# app/api/routes/oauth.py
import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.oauth.registry import get_provider, list_providers
from app.core.oauth.state import OAuthState, consume_state, generate_pkce_pair, store_state
from app.core.redis import get_redis
from app.core.security import create_access_token
from app.crud import oauth_account as crud_oauth
from app.crud import user as crud_user
from app.models.user import User

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


@router.get("/{provider}/login")
async def oauth_login(
    provider: str,
    return_to: str | None = None,
):
    if provider not in list_providers():
        raise HTTPException(404, "Unknown provider")
    p = get_provider(provider)

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    redis = await get_redis()
    await store_state(
        redis,
        OAuthState(
            state=state,
            code_verifier=code_verifier,
            provider=provider,
            return_to=return_to,
        ),
    )
    redirect_uri = f"{settings.FRONTEND_HOST}{settings.API_V1_STR}/auth/oauth/{provider}/callback"
    return RedirectResponse(
        url=p.authorization_url(state=state, code_challenge=code_challenge, redirect_uri=redirect_uri)
    )


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    session: SessionDep,
):
    if provider not in list_providers():
        raise HTTPException(404, "Unknown provider")
    p = get_provider(provider)

    redis = await get_redis()
    state_obj = await consume_state(redis, state)
    if state_obj is None:
        raise HTTPException(400, "Invalid or expired state")
    if state_obj.provider != provider:
        raise HTTPException(400, "Provider mismatch")

    redirect_uri = f"{settings.FRONTEND_HOST}{settings.API_V1_STR}/auth/oauth/{provider}/callback"
    try:
        tokens = await p.exchange_code(code, state_obj.code_verifier, redirect_uri)
    except Exception:
        raise HTTPException(400, "Code exchange failed")

    try:
        info = await p.fetch_user(tokens.access_token)
    except Exception:
        raise HTTPException(400, "Failed to fetch user info")

    if not info.email_verified:
        raise HTTPException(400, "Provider email is not verified")

    user = await _resolve_or_create_user(session, provider, info)
    await crud_oauth.upsert(
        session,
        provider=provider,
        provider_user_id=info.provider_user_id,
        provider_email=info.email,
        user_id=user.id,
        tokens=tokens,
    )

    jwt = create_access_token(subject=user.id)
    target = state_obj.return_to or "/"
    safe_target = target if target.startswith("/") else "/"
    return RedirectResponse(
        url=f"{settings.FRONTEND_HOST}{safe_target}?token={quote(jwt)}",
        status_code=status.HTTP_302_FOUND,
    )


async def _resolve_or_create_user(session, provider: str, info) -> User:
    # 1. Already linked?
    existing = await crud_oauth.get(session, provider=provider, provider_user_id=info.provider_user_id)
    if existing:
        return await crud_user.get(session, id=existing.user_id)

    # 2. Link by email if exists
    if info.email and settings.OAUTH_LINK_EXISTING:
        u = await crud_user.get_by_email(session, email=info.email)
        if u:
            return u

    # 3. Auto-provision
    if not settings.OAUTH_ALLOW_SIGNUP:
        raise HTTPException(403, "Signup via OAuth disabled")
    return await crud_user.create_oauth_user(session, email=info.email, name=info.name)
```

### 4.7 CRUD (NEW, fragment)
```python
# app/crud/oauth_account.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oauth.crypto import encrypt_token
from app.models.oauth_account import OAuthAccount


async def get(session: AsyncSession, *, provider: str, provider_user_id: str) -> OAuthAccount | None:
    stmt = select(OAuthAccount).where(
        OAuthAccount.provider == provider,
        OAuthAccount.provider_user_id == provider_user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert(session, *, provider, provider_user_id, provider_email, user_id, tokens) -> OAuthAccount:
    existing = await get(session, provider=provider, provider_user_id=provider_user_id)
    if existing:
        existing.access_token_enc = encrypt_token(tokens.access_token)
        existing.refresh_token_enc = encrypt_token(tokens.refresh_token)
        existing.provider_email = provider_email
        await session.flush()
        return existing
    new = OAuthAccount(
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=provider_email,
        user_id=user_id,
        access_token_enc=encrypt_token(tokens.access_token),
        refresh_token_enc=encrypt_token(tokens.refresh_token),
    )
    session.add(new)
    await session.flush()
    return new
```

### 4.8 Migration
```python
# alembic/versions/0011_add_oauth2_provider.py
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(320), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        sa.CheckConstraint(
            "provider IN ('google','github','facebook','microsoft')",
            name="ck_oauth_provider",
        ),
    )
    op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])

    # Allow users.hashed_password to be NULL (OAuth users don't have a password)
    op.alter_column("users", "hashed_password", nullable=True)


def downgrade() -> None:
    op.alter_column("users", "hashed_password", nullable=False)
    op.drop_index("ix_oauth_accounts_user_id", "oauth_accounts")
    op.drop_table("oauth_accounts")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **CSRF protection via single-use state token** | State token is generated server-side, stored in Redis with TTL, and DELETED on first read (`consume_state` uses pipeline GET+DEL). Replay impossible. |
| QS-2 | **PKCE always used** | `code_challenge_method=S256` in authorization URL; `code_verifier` stored in Redis, used in exchange. Prevents code interception attacks. |
| QS-3 | **Provider tokens encrypted at rest** | Fernet (AES-128-CBC + HMAC-SHA256) via `OAUTH_TOKEN_FERNET_KEY`. Plaintext tokens NEVER hit the database. |
| QS-4 | **Email verification required** | Callback rejects if `email_verified=false`. Prevents account hijacking via unverified emails. |
| QS-5 | **Provider isolation** | Each provider implements `OAuthProvider`; registry pattern allows adding/removing providers without touching routes. |
| QS-6 | **Account linking is conservative** | Linking by email only happens if `link_existing=True` AND email is verified by provider. |
| QS-7 | **Auto-signup is opt-in** | `allow_signup=False` blocks new account creation; existing users can still link. |
| QS-8 | **Open redirect prevention** | `return_to` validated to start with `/` (relative URL only). External URLs rejected. |
| QS-9 | **Provider HTTP calls are bounded** | `httpx.AsyncClient(timeout=10.0)` on every external request. No hanging requests. |
| QS-10 | **Provider mismatch blocked** | Callback verifies `state_obj.provider == provider` to prevent provider-confusion attacks. |
| QS-11 | **Fernet key is mandatory** | `settings.OAUTH_TOKEN_FERNET_KEY` raises at startup if missing. |
| QS-12 | **OAuth users can have NULL password** | Migration relaxes `users.hashed_password` to nullable; password-less accounts allowed. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `OAuthAccount` model exists at `app/models/oauth_account.py` | File exists |
| CC-02 | `app/core/oauth/base.py` defines `OAuthProvider` ABC | grep |
| CC-03 | A provider class exists for each provider in `providers` param | grep |
| CC-04 | `app/core/oauth/registry.py` exists with `get_provider`/`list_providers` | File exists |
| CC-05 | `app/core/oauth/state.py` exists with `generate_pkce_pair`, `store_state`, `consume_state` | File exists |
| CC-06 | `app/core/oauth/crypto.py` exists with `encrypt_token`/`decrypt_token` | File exists |
| CC-07 | `app/api/routes/oauth.py` exists with login + callback endpoints | File exists |
| CC-08 | `app/crud/oauth_account.py` exists with `get`, `upsert` | File exists |
| CC-09 | Migration `0011_add_oauth2_provider.py` exists | File exists |
| CC-10 | Migration creates table + relaxes `users.hashed_password` to nullable | Inspect |
| CC-11 | Migration unique constraint `(provider, provider_user_id)` | Inspect |
| CC-12 | `OAUTH_TOKEN_FERNET_KEY` settings is required and raises if missing | grep config.py |
| CC-13 | `OAUTH_LINK_EXISTING` and `OAUTH_ALLOW_SIGNUP` settings | grep |
| CC-14 | `OAUTH_STATE_TTL_SECONDS` settings configurable | grep |
| CC-15 | Per-provider settings (e.g. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) | grep |
| CC-16 | `state.consume_state` uses pipeline GET+DEL (atomic single-use) | grep |
| CC-17 | `authorization_url` includes `code_challenge_method=S256` | grep |
| CC-18 | Callback validates `email_verified` | grep |
| CC-19 | Callback validates state.provider == provider | grep |
| CC-20 | Callback validates `return_to` starts with `/` | grep |
| CC-21 | Routes registered in `app/api/main.py` | grep |
| CC-22 | OpenAPI exposes new endpoints | curl /openapi.json |
| CC-23 | `.env.example` updated with all new env vars | inspect |
| CC-24 | New file `tests/test_oauth.py` with 30 tests | File exists |
| CC-25 | Existing tests pass | pytest 0 failures |
| CC-26 | All files parse | Tool internal |
| CC-27 | Tool execution time < 5s | Time measurement |
| CC-28 | Login redirect < 200 ms | Benchmark T-29 |
| CC-29 | Callback p99 < 800 ms | Benchmark T-30 |
| CC-30 | Idempotent re-run | T-26 |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 8 Invariants enforced (see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (see §10)
- [ ] Tool is idempotent
- [ ] Tool is reversible: rollback procedure documented and tested
- [ ] Performance budget met
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated (KNOWLEDGE.md, manifest.yaml, SKILL.md)
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-OA-01 | A state token is single-use; replay returns 400 | `consume_state` uses pipeline GET+DEL | T-04 |
| INV-OA-02 | A state token expires after TTL | Redis SETEX — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-05 |
| INV-OA-03 | A state token's provider must match the callback URL provider | Callback checks `state_obj.provider == provider` | T-12 |
| INV-OA-04 | An unverified email NEVER creates or links an account | Callback raises 400 if `email_verified=false` | T-13 |
| INV-OA-05 | Provider tokens are NEVER stored in plaintext | Only `*_enc` columns exist; CRUD always encrypts on write | T-15 |
| INV-OA-06 | An open redirect is NEVER possible via `return_to` | Validation: must start with `/`; otherwise default to `/` | T-17 |
| INV-OA-07 | A user with `allow_signup=False` cannot be created via OAuth | Callback raises 403 if no existing user matched | T-09 |
| INV-OA-08 | The Fernet key is required at startup | Settings field has no default; raises on import if missing | T-30 |

---

## 9. User Stories

### 9.1 Initial login flow (US-01 .. US-05)

**US-01: Authorization redirect includes PKCE challenge**
- **As a** developer integrating social login
- **I want** the `/auth/oauth/{provider}/login` endpoint to redirect to the provider with a valid PKCE S256 challenge
- **So that** the Authorization Code flow is hardened against code interception from the first request
- **Given:** provider `google` is configured in the registry and `GOOGLE_CLIENT_ID` is set in settings
- **When:** a client issues `GET /auth/oauth/google/login`
- **Then:**
  - the response is HTTP 307 to `https://accounts.google.com/o/oauth2/v2/auth`
  - the redirect URL contains `code_challenge_method=S256` and a non-empty `code_challenge`
  - the `state` parameter is a 32-byte URL-safe random string stored in Redis under `oauth:state:<state>` with TTL = `OAUTH_STATE_TTL_SECONDS`
  - [CC-05, CC-17, T-01, T-02, T-03]

**US-02: Successful callback auto-provisions a new user**
- **As a** first-time visitor with a verified Google account
- **I want** to complete the OAuth callback and receive a JWT
- **So that** I am authenticated without creating a separate password
- **Given:** `allow_signup=True`, no existing `User` with the provider email, and the provider returns `email_verified=true`
- **When:** Google redirects to `GET /auth/oauth/google/callback?code=AUTHCODE&state=VALID_STATE`
- **Then:**
  - `consume_state` atomically deletes the Redis key (GET + DEL pipeline) so replay is impossible
  - a new `User` row is created with `hashed_password=NULL` and `is_active=True`
  - an `OAuthAccount` row is created with `provider='google'` and `provider_user_id` matching `sub` from Google's userinfo
  - a JWT is issued via `create_access_token` and the response is HTTP 302 to `${FRONTEND_HOST}/?token=<jwt>`
  - [CC-07, CC-08, CC-10, INV-OA-01, T-06]

**US-03: Callback resolves to existing email/password user via account linking**
- **As a** registered user who signed up with email/password
- **I want** logging in with Google (same email) to link my social account automatically
- **So that** I use one account across both login methods
- **Given:** a `User` row exists with `email='alice@example.com'`, `link_existing=True`, and Google returns that same verified email
- **When:** the OAuth callback completes successfully
- **Then:**
  - no new `User` row is created (`user` count unchanged)
  - a new `OAuthAccount` row is inserted linking to the existing `user.id`
  - the JWT subject is the existing `user.id`, not a new UUID
  - [CC-06, INV-OA-04, T-07]

**US-04: Returning social user is recognized without creating a duplicate account**
- **As a** user who previously linked their Google account
- **I want** a second Google login to find my existing `OAuthAccount` and skip re-provisioning
- **So that** I never accumulate duplicate accounts across sessions
- **Given:** an `OAuthAccount` row already exists with `provider='google'` and `provider_user_id='1234567890'`
- **When:** Google calls back with the same `sub` value
- **Then:**
  - the `crud_oauth.get()` lookup returns the existing row on the `(provider, provider_user_id)` unique constraint
  - `crud_user.create_oauth_user` is never called
  - the `OAuthAccount.access_token_enc` is updated with the freshly encrypted token
  - [CC-11, INV-OA-05, T-08]

**US-05: Callback redirects to the `return_to` path after login**
- **As a** user who was navigating a protected page before clicking "Login with Google"
- **I want** to land back on that page after successful authentication
- **So that** I don't lose my navigation context on every login
- **Given:** the login was initiated with `return_to=/projects/42` and the OAuth flow completes successfully
- **When:** the callback endpoint issues the final redirect
- **Then:**
  - the redirect target is `${FRONTEND_HOST}/projects/42?token=<jwt>` (relative path preserved)
  - an absolute URL like `return_to=https://evil.com` causes the endpoint to fall back to `/` instead
  - [CC-20, INV-OA-06, T-17, T-18]

---

### 9.2 PKCE & state token (US-06 .. US-10)

**US-06: State token is consumed on first use — replay returns 400**
- **As a** security engineer auditing the CSRF surface
- **I want** the state token to be atomically deleted on first consumption
- **So that** an intercepted callback URL cannot be replayed by an attacker
- **Given:** a valid callback has already been processed (state token consumed via GET+DEL pipeline)
- **When:** the same `state` query parameter is submitted to the callback endpoint a second time
- **Then:**
  - `consume_state` finds no Redis key (already deleted) and returns `None`
  - the endpoint returns HTTP 400 with body `"Invalid or expired state"`
  - no user lookup or token exchange is attempted
  - [INV-OA-01, CC-16, T-04]

**US-07: State token with expired TTL returns 400 without leaking timing info**
- **As a** security engineer
- **I want** stale state tokens to be rejected after the configured TTL
- **So that** a login URL that was bookmarked or delayed cannot be exploited
- **Given:** a state token was stored in Redis with `SETEX` at `t₀` and `OAUTH_STATE_TTL_SECONDS=600`
- **When:** the callback arrives at `t₀ + 700s`
- **Then:**
  - Redis has already evicted the key; `consume_state` returns `None`
  - the endpoint returns HTTP 400 with the same generic message as a missing state
  - no branch reveals whether the state ever existed
  - [INV-OA-01, INV-OA-02, T-05]

**US-08: Wrong code verifier causes provider to reject the token exchange**
- **As a** security engineer testing PKCE enforcement
- **I want** a tampered `code_verifier` to be rejected at the provider's token endpoint
- **So that** a stolen authorization code cannot be exchanged without the original verifier
- **Given:** the state object in Redis holds `code_verifier=V1`, but an attacker substitutes `code_verifier=V2` in the exchange call
- **When:** `provider.exchange_code(code, code_verifier=V2, redirect_uri=...)` is called
- **Then:**
  - the provider returns HTTP 400 (invalid_grant or invalid_request)
  - our callback catches the exception and returns HTTP 400 to the client
  - the `OAuthState` key was already consumed, preventing any retry
  - [INV-OA-01, CC-17, T-08 — provider-side enforcement via S256 hash mismatch]

**US-09: Provider mismatch between state and callback URL returns 400**
- **As a** security engineer testing provider-confusion attacks
- **I want** the callback to verify that the state token's `provider` field matches the URL segment
- **So that** a state token issued for Google cannot be replayed on the GitHub callback route
- **Given:** a state token was stored with `provider='google'`
- **When:** the attacker submits that state to `GET /auth/oauth/github/callback?code=X&state=THAT_STATE`
- **Then:**
  - `consume_state` returns the state object (consuming it irreversibly)
  - the check `state_obj.provider != provider` evaluates to `True`
  - HTTP 400 `"Provider mismatch"` is returned before any token exchange
  - [INV-OA-03, CC-19, T-12]

**US-10: PKCE verifier and challenge are generated with `secrets.token_urlsafe` and SHA-256**
- **As a** developer reviewing the PKCE implementation
- **I want** the verifier to use a cryptographically secure random source and S256 hashing
- **So that** the implementation conforms to RFC 7636 and is immune to brute-force on the verifier
- **Given:** `generate_pkce_pair()` is called
- **When:** the returned `(verifier, challenge)` pair is inspected
- **Then:**
  - `verifier` is between 43 and 128 URL-safe characters (RFC 7636 §4.1)
  - `challenge == base64url(SHA256(verifier.encode('ascii')))` without trailing `=`
  - the authorization URL sent to the provider includes `code_challenge_method=S256` and the computed challenge
  - [CC-17, T-03]

---

### 9.3 Account linking (US-11 .. US-15)

**US-11: Linking by verified email is skipped when `link_existing=False`**
- **As an** operator who wants strict provider-identity isolation
- **I want** to disable email-based account linking so that each provider login always creates a distinct account
- **So that** a user with the same email on two providers cannot accidentally merge accounts
- **Given:** `link_existing=False` in settings, and a `User` row exists with `email='bob@example.com'`
- **When:** the OAuth callback arrives with a verified email matching that user
- **Then:**
  - the email-lookup branch is skipped entirely
  - if `allow_signup=True`, a new `User` is provisioned (separate account, same email)
  - if `allow_signup=False`, HTTP 403 `"Signup via OAuth disabled"` is returned
  - [INV-OA-07, CC-13, T-10]

**US-12: Unverified email from provider is rejected before any account lookup**
- **As a** security engineer preventing account hijacking via unverified provider emails
- **I want** the callback to abort if the provider reports `email_verified=false`
- **So that** an attacker who registers a fake Google account with someone else's email cannot link to or create an account
- **Given:** GitHub returns a user-info payload where `email_verified` is absent or explicitly `false`
- **When:** the callback processes the provider response
- **Then:**
  - HTTP 400 `"Provider email is not verified"` is returned
  - no `User` or `OAuthAccount` row is created or modified
  - the state token has already been consumed (preventing retry)
  - [INV-OA-04, CC-18, T-13]

**US-13: A user can link multiple providers to the same account**
- **As a** user who has both a Google and a GitHub account with the same email
- **I want** both providers to resolve to my single application account
- **So that** I can log in with either provider and always access the same data
- **Given:** a `User` exists with `email='carol@example.com'`; a Google `OAuthAccount` is already linked; `link_existing=True`
- **When:** Carol logs in via GitHub with the same verified email
- **Then:**
  - `crud_oauth.get(provider='github', provider_user_id=...)` returns `None` (no GitHub link yet)
  - `crud_user.get_by_email('carol@example.com')` returns the existing user
  - a new `OAuthAccount` row is inserted for `provider='github'` pointing to the same `user.id`
  - Carol now has two `OAuthAccount` rows, one per provider
  - [CC-06, INV-OA-04, T-07]

**US-14: Signup disabled with `allow_signup=False` blocks new user creation but not existing logins**
- **As an** operator running the platform in closed-beta mode
- **I want** to prevent any new accounts from being created via OAuth
- **So that** I can control the user base while still allowing existing social-login users to authenticate
- **Given:** `allow_signup=False`; one `User` already has an `OAuthAccount` for Google; a completely new email attempts OAuth login
- **When:** both the existing user and the new email go through the Google callback
- **Then:**
  - the existing user (`OAuthAccount` found on step 1) receives a JWT normally
  - the new email (no `OAuthAccount`, no matching user) triggers HTTP 403
  - no `User` row is created for the new email
  - [INV-OA-07, CC-13, T-09]

**US-15: `OAuthAccount` is upserted on every login — tokens stay fresh**
- **As a** developer relying on the stored provider tokens for downstream API calls
- **I want** each successful login to refresh the encrypted tokens in `oauth_accounts`
- **So that** the application always holds the most recent access and refresh tokens
- **Given:** an `OAuthAccount` exists with old `access_token_enc` and `refresh_token_enc` values
- **When:** the same user completes another successful OAuth callback
- **Then:**
  - `crud_oauth.upsert` detects the existing row via `(provider, provider_user_id)` and updates `access_token_enc` and `refresh_token_enc` in-place
  - the DB row count for `oauth_accounts` does not increase
  - `decrypt_token(row.access_token_enc)` returns the new access token
  - [INV-OA-05, CC-08, T-15, T-16]

---

### 9.4 Token encryption at rest (US-16 .. US-20)

**US-16: Provider access token is never stored in plaintext**
- **As a** DBA or security auditor inspecting the `oauth_accounts` table
- **I want** all provider tokens to be stored as opaque ciphertext
- **So that** a database dump or read replica compromise does not expose usable downstream credentials
- **Given:** a successful OAuth callback with Google returning `access_token='ya29.ABCDEF...'`
- **When:** the row is read directly from the `oauth_accounts` table via raw SQL
- **Then:**
  - `access_token_enc` is a `LargeBinary` byte string starting with `gAAA` (Fernet token header)
  - `access_token_enc != b'ya29.ABCDEF...'`
  - `decrypt_token(access_token_enc)` using the correct Fernet key returns `'ya29.ABCDEF...'`
  - [INV-OA-05, CC-12, T-15]

**US-17: Refresh token is independently encrypted at rest**
- **As a** security engineer
- **I want** the refresh token to be encrypted separately from the access token
- **So that** compromise of one Fernet-encrypted blob does not trivially expose the other
- **Given:** Google's token endpoint returns both `access_token` and `refresh_token` during the first login (with `prompt=consent`)
- **When:** the `upsert` CRUD function is called
- **Then:**
  - `refresh_token_enc` is a non-null `LargeBinary` in the DB
  - `decrypt_token(refresh_token_enc)` returns the original refresh token
  - if the provider does not return a refresh token, `refresh_token_enc` is `NULL` (not an error)
  - [INV-OA-05, CC-12, T-16]

**US-18: Missing Fernet key raises at application startup, not at request time**
- **As an** operator deploying the service
- **I want** a missing `OAUTH_TOKEN_FERNET_KEY` to fail loudly at boot
- **So that** I never ship a misconfigured instance that silently stores tokens unencrypted
- **Given:** `OAUTH_TOKEN_FERNET_KEY` is absent from the environment
- **When:** the application process starts and imports `app.core.config`
- **Then:**
  - a `ValidationError` or `ValueError` is raised before any request is handled
  - the error message clearly names `OAUTH_TOKEN_FERNET_KEY` as the missing field
  - no fallback encryption or plaintext storage is attempted
  - [INV-OA-08, CC-12, T-30]

**US-19: Fernet key rotation via `MultiFernet` keeps existing tokens decryptable**
- **As an** operator rotating encryption keys after a security incident
- **I want** to prepend a new Fernet key while retaining the old one
- **So that** tokens encrypted under the old key remain decryptable during the rotation window
- **Given:** `OAUTH_TOKEN_FERNET_KEY` is updated to a `MultiFernet`-compatible key list `[NEW_KEY, OLD_KEY]`
- **When:** `decrypt_token` is called on a ciphertext that was encrypted with `OLD_KEY`
- **Then:**
  - `MultiFernet` tries `NEW_KEY` first (fails silently), then succeeds with `OLD_KEY`
  - the plaintext access token is returned without error
  - new tokens written after the rotation are encrypted with `NEW_KEY`
  - [INV-OA-05, CC-12, T-15]

**US-20: Invalid ciphertext (corrupted or wrong key) returns `None` without raising**
- **As a** developer calling `decrypt_token` on a row written under a key that was already rotated out
- **I want** the function to return `None` rather than raise an unhandled exception
- **So that** the application can surface a graceful "re-authentication required" flow instead of a 500 error
- **Given:** `decrypt_token` is called with bytes that fail Fernet's HMAC verification (wrong key or corrupted)
- **When:** `_fernet.decrypt(ciphertext)` raises `cryptography.fernet.InvalidToken`
- **Then:**
  - the exception is caught inside `decrypt_token`
  - the function returns `None`
  - the caller receives `None` and can prompt the user to re-authenticate
  - [INV-OA-05, CC-06, T-16]

---

### 9.5 Provider extensibility & edge cases (US-21 .. US-25)

**US-21: Adding a new provider requires only a class + registry entry, not route changes**
- **As a** developer adding Apple Sign In to the platform
- **I want** to implement `AppleProvider(OAuthProvider)` and register it in `_PROVIDERS`
- **So that** the `/auth/oauth/apple/login` and `/auth/oauth/apple/callback` routes work automatically via the existing parameterized router
- **Given:** `AppleProvider` implements `authorization_url`, `exchange_code`, and `fetch_user` from `OAuthProvider`; it is added to `_PROVIDERS = {..., "apple": AppleProvider()}`; `ck_oauth_provider` DB constraint is updated via migration
- **When:** a client hits `GET /auth/oauth/apple/login`
- **Then:**
  - `get_provider('apple')` returns the `AppleProvider` instance without error
  - the login route generates a PKCE pair, stores state in Redis, and issues a 307 redirect to Apple's authorization endpoint
  - no changes are needed to `oauth.py` routes or any existing provider file
  - [CC-04, CC-05, T-21]

**US-22: Unknown provider slug returns 404, not 500**
- **As a** developer hitting a mistyped provider URL during integration
- **I want** an unrecognized provider name to produce a clear 404 response
- **So that** I get actionable feedback instead of a Python `KeyError` traceback
- **Given:** the registry contains only `['google', 'github', 'facebook', 'microsoft']`
- **When:** `GET /auth/oauth/twitter/login` is requested
- **Then:**
  - `list_providers()` does not include `'twitter'`
  - the endpoint raises `HTTPException(404, "Unknown provider")` before generating any PKCE material or Redis state
  - the OpenAPI schema lists the 404 response for both login and callback endpoints
  - [CC-04, T-19]

**US-23: Tool re-run is fully idempotent — no duplicate files or migrations**
- **As a** developer running the generator a second time after OAuth is already installed
- **I want** the tool to detect existing files and skip re-creation
- **So that** I can safely re-run without corrupting existing provider classes or creating duplicate Alembic revisions
- **Given:** `add_oauth2_provider(project_dir=..., providers=['google'])` was already run once successfully
- **When:** the same call is made again with identical parameters
- **Then:**
  - no existing file is overwritten (`app/models/oauth_account.py`, `app/core/oauth/google.py`, etc.)
  - no new Alembic migration file is created
  - the tool returns a result dict indicating `status='no_op'` with a list of already-present files
  - [CC-30, T-26]

**US-24: Re-run with an additional provider adds only the new provider files**
- **As a** developer expanding social login from Google-only to Google + GitHub
- **I want** re-running the tool with `providers=['google', 'github']` to add only the GitHub-specific files
- **So that** the Google integration is not touched or regenerated
- **Given:** Google is already installed (`app/core/oauth/google.py` exists, `GOOGLE_CLIENT_ID` is in `.env.example`)
- **When:** `add_oauth2_provider(..., providers=['google', 'github'])` is called
- **Then:**
  - `app/core/oauth/github.py` is created with `GitHubProvider(OAuthProvider)`
  - `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` placeholders are appended to `.env.example`
  - `app/core/oauth/google.py` is not modified (mtime unchanged)
  - the registry in `app/core/oauth/registry.py` is updated to include `'github': GitHubProvider()`
  - [CC-03, CC-15, CC-23, T-27]

**US-25: Callback with a provider HTTP timeout returns 400 within the bounded window**
- **As a** developer operating under SLO constraints
- **I want** a provider that hangs on the token exchange to be cut off after 10 seconds
- **So that** a slow or unresponsive IdP does not exhaust FastAPI worker threads indefinitely
- **Given:** the mock provider's token endpoint is configured to sleep for 30 seconds before responding
- **When:** `provider.exchange_code(code, code_verifier, redirect_uri)` is awaited with `httpx.AsyncClient(timeout=10.0)`
- **Then:**
  - `httpx.ReadTimeout` is raised after ~10 seconds
  - the callback route catches the exception and returns HTTP 400 `"Code exchange failed"` within 10.5 seconds
  - no partial `OAuthAccount` or `User` row is committed to the database
  - [INV-OA-08 (implicit — bounded HTTP), T-28]

## 10. Test Plan

### 10.1 Authorization & state

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | login redirects to provider | provider configured | GET /auth/oauth/google/login | 307 to Google with state + code_challenge |
| T-02 | login stores state in Redis | login | inspect Redis | `oauth:state:<state>` exists with TTL |
| T-03 | login generates PKCE S256 | login | inspect URL | code_challenge_method=S256 |
| T-04 | replay of state returns 400 | callback once | callback with same state | 400 |
| T-05 | expired state returns 400 | TTL=1s, wait 2s | callback | 400 |

### 10.2 Callback & user resolution

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | new user auto-provisioned | allow_signup=True, no existing user | callback | new user created, OAuthAccount linked |
| T-07 | existing user linked by email | existing user, link_existing=True | callback | OAuthAccount linked to existing |
| T-08 | already-linked OAuth account → existing user | OAuthAccount exists | callback | same user, no new user |
| T-09 | allow_signup=False blocks new user | no existing | callback | 403 |
| T-10 | callback with bad code → 400 | mock provider 401 | callback | 400 |
| T-11 | callback fetches user info | mock | inspect | userinfo endpoint called |
| T-12 | provider mismatch → 400 | state for google, callback to github | callback | 400 |

### 10.3 Security

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | unverified email → 400 | provider returns email_verified=false | callback | 400 |
| T-14 | state token deleted after consume | callback once | inspect Redis | key absent |
| T-15 | access token stored encrypted | callback | inspect access_token_enc | bytes != plaintext |
| T-16 | tokens decryptable | inspect | decrypt_token() | matches original |
| T-17 | open redirect blocked | return_to=https://evil | callback | redirect to / not evil |
| T-18 | absolute return_to with leading slash works | return_to=/dashboard | callback | redirect to /dashboard |

### 10.4 Provider abstraction & idempotency

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | unknown provider → 404 | GET /auth/oauth/unknown/login | request | 404 |
| T-20 | provider registry lists installed | call list_providers() | check | matches installed |
| T-21 | adding new provider to registry exposes routes | add Apple class | hit /auth/oauth/apple/login | 307 |
| T-26 | tool re-run no-op | already installed | run | no file changes |
| T-27 | env vars present in .env.example | run tool | grep | placeholders found |

### 10.5 Integration & performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | JWT issued matches password-login JWT format | callback | inspect token | same algo, same claims |
| T-23 | Inactive user cannot complete login | user.is_active=False | callback | redirect with token, but next API call → 403 |
| T-24 | Multi-tenancy: new user assigned to default tenant | tenancy installed | callback | user.tenant_id = default |
| T-25 | hashed_password is now NULL-able | inspect schema | check | nullable=True |
| T-28 | provider HTTP timeout = 10s | mock provider hang | callback | 400 within 10s |
| T-29 | login redirect < 200 ms | benchmark | measure | < 200 ms |
| T-30 | callback p99 < 800 ms | benchmark with mock provider | measure | < 800 ms; Fernet key missing → startup raises |

---

## 11. Interaction Matrix

How `add_oauth2_provider` interacts with other tools:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Tenancy first** | ⚠️ Caveat | New OAuth users must be assigned to a tenant; tool documents the default-tenant strategy. |
| `add_audit_log` | **Audit first** | ✅ Compatible | OAuth login produces an audit entry with `action='oauth_login', provider=...`. |
| `add_rbac` | **RBAC first** | ✅ Compatible | New OAuth users get a default role; configurable. |
| `add_mfa` | No | ⚠️ Caveat | If MFA is enabled, OAuth login should still trigger MFA challenge after callback. |
| `add_api_key_auth` | No | ✅ Compatible | Independent auth methods. |
| `add_feature_flags` | No | ✅ Compatible | Flags can target by provider. |
| `add_audit_log` (re-mention) | — | — | — |
| `add_rate_limit` | No | ⚠️ Caveat | Rate-limit the callback endpoint to prevent flooding. |
| `add_security_headers` | No | ✅ Compatible | OAuth uses redirects; HSTS still applies. |
| `add_cors` | **CORS-aware** | ⚠️ Caveat | OAuth callbacks come from provider, not your frontend; ensure CORS allows the provider's origin if frontend reads the JWT from URL. |
| TOOL-034 performance_baseline | downstream | `GET /auth/oauth/{provider}/login` and `GET /auth/oauth/{provider}/callback` are captured in the baseline (target p99 < 200 ms); a regression in `app/core/oauth/crypto.py` Fernet encrypt/decrypt that adds latency to the callback flow will be caught before merge |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_oauth2_provider` is installed but no `add_mfa` is present and recommends TOOL-013 `add_mfa`, noting that OAuth users bypass the password step and should still face an MFA challenge — flagged as HIGH if the project handles sensitive data |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

If `add_oauth2_provider` produces broken state, the rollback procedure is:

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/oauth_account.py app/core/oauth \
  app/crud/oauth_account.py app/api/routes/oauth.py app/api/main.py \
  app/core/config.py .env.example
rm alembic/versions/*_add_oauth2_provider.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `oauth_accounts` and re-NOT-NULLs `users.hashed_password`. **Warning**: any OAuth-only users (with NULL password) will block the downgrade. Either delete them, set a placeholder password, or skip the column constraint.

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_oauth2_provider.py`
- Drop partially-created `oauth_accounts` table
- Re-run tool

### Emergency: provider is leaking tokens
1. Disable provider: remove from registry + redeploy
2. Rotate Fernet key (`OAUTH_TOKEN_FERNET_KEY`); use `MultiFernet` to keep old keys decryptable during rotation
3. Force re-link: `DELETE FROM oauth_accounts WHERE provider='X'`
4. Notify affected users


### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (some modules present, others missing, config half-written), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- app/ tests/ alembic/ pyproject.toml
git clean -fd app/ tests/

# 3. Verify clean tree before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: OAuth provider client_id/secret leaked in logs or error response
If `client_id` or `client_secret` were emitted in structured logs, an error traceback, or a 500 response body:
```bash
# 1. Immediately revoke the compromised credential at the provider console
#    Google: https://console.cloud.google.com/apis/credentials
#    GitHub: https://github.com/settings/applications
#    Azure:  https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps

# 2. Generate new credentials at the provider console and update .env
sed -i.bak 's/^GOOGLE_CLIENT_SECRET=.*/GOOGLE_CLIENT_SECRET=NEW_VALUE/' .env

# 3. Rotate the Fernet key; old tokens in oauth_accounts.access_token become unreadable
python - <<'EOF'
from cryptography.fernet import Fernet, MultiFernet
import os
new_key = Fernet.generate_key().decode()
print(f"New OAUTH_TOKEN_FERNET_KEY={new_key}")
print("Add old key as OAUTH_TOKEN_FERNET_KEY_OLD for MultiFernet transition period")
EOF

# 4. Update config to use MultiFernet with [new, old] during re-encryption window
#    In app/core/oauth/crypto.py: fernet = MultiFernet([Fernet(NEW), Fernet(OLD)])

# 5. Run background re-encryption job; remove old key after completion
psql $DATABASE_URL -c "SELECT COUNT(*) FROM oauth_accounts WHERE provider='google';"
python scripts/reencrypt_oauth_tokens.py --provider google

# 6. Confirm no active tokens with old key remain, then drop old key from MultiFernet
# 7. Audit: scan recent structured logs for any remaining token leakage patterns
grep -r "client_secret\|access_token" /var/log/app/ | grep -v ".enc" | head -20
```

### Emergency: Redis state token store down during OAuth callback
If Redis is unavailable, `consume_state()` returns `None` on every callback and all OAuth logins fail with 400:
```bash
# 1. Confirm Redis is unreachable from the app pod
redis-cli -u $REDIS_URL ping   # expects PONG

# 2. Check Redis sentinel / cluster status
redis-cli -u $REDIS_URL cluster info 2>/dev/null || redis-cli -u $REDIS_URL info replication

# 3. If Redis is flapping, increase state TTL temporarily so partial keys survive a restart
redis-cli -u $REDIS_URL CONFIG SET hz 10

# 4. Inspect orphaned state keys accumulated during outage (safe to delete)
redis-cli -u $REDIS_URL KEYS "oauth:state:*" | wc -l
redis-cli -u $REDIS_URL DEL $(redis-cli -u $REDIS_URL KEYS "oauth:state:*")

# 5. If Redis will be down for > SSE_STATE_TTL (600s), redirect users to password login
#    Set env var OAUTH_FALLBACK_DISABLED=true and redeploy; the generated login page
#    hides OAuth buttons when this var is set

# 6. Once Redis recovers, verify state pipeline works end-to-end before re-enabling
curl -s "$APP_URL/auth/oauth/google/login" | grep -i "Location"

# 7. Review callback error logs from the outage window for any state replay attempts
grep '"event":"oauth_state_invalid"' /var/log/app/structured.log | tail -50
```


---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no User model | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | Project has no Redis | Tool errors: "OAuth requires Redis for state storage." |
| EC-3 | Fernet key missing in env | App startup fails; the operation returns a structured error response and no side effects persist |
| EC-4 | Fernet key is invalid (wrong length) | Cryptography raises at import; the operation returns a structured error response and no side effects persist |
| EC-5 | Provider returns no email | Callback errors (cannot link or auto-provision) |
| EC-6 | Provider returns email but `email_verified=false` | 400; the operation returns a structured error response and no side effects persist |
| EC-7 | User cancels at provider screen → returns to callback with `error=access_denied` | 400 with friendly message; the operation returns a structured error response and no side effects persist |
| EC-8 | State TTL is too short for slow users | TTL configurable; default 600s is safe for most flows |
| EC-9 | Two callbacks happen with the same state (race) | Pipeline GET+DEL is atomic; only first succeeds, second gets 400 |
| EC-10 | Provider is rate-limiting our requests | httpx propagates 429; we return 503 to user |
| EC-11 | Redis down during login | login fails with 500; user sees friendly error |
| EC-12 | Redis down during callback | consume_state returns None → 400; the operation returns a structured error response and no side effects persist |
| EC-13 | User has both password and OAuth; OAuth login still works | Yes; both auth methods coexist |
| EC-14 | User unlinks last provider but has no password | Endpoint must require user to set a password first; otherwise reject |
| EC-15 | A new provider is added that the project does not enable | Registry has all 4; only enabled providers have working settings |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 30 CC verified by automated check
2. ✅ All 25 user stories have passing acceptance tests
3. ✅ All 30 test cases pass
4. ✅ All 8 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified by integration tests
7. ✅ Rollback procedure tested end-to-end
8. ✅ Performance SLOs measured and met
9. ✅ Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10
10. ✅ One human dev configures Google + GitHub, completes both flows in a real browser

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Redis is configured
- [ ] Validate Alembic initialized
- [ ] Detect existing `oauth_accounts` table → idempotent skip if found
- [ ] Detect existing `app/core/oauth/` directory → idempotent merge
- [ ] Verify idempotency: run the tool twice and confirm second invocation returns `status="already_installed"` without modifying `app/core/oauth/` or creating duplicate DB tables

### 15.2 Settings
- [ ] Add `OAUTH_TOKEN_FERNET_KEY: str` (required)
- [ ] Add `OAUTH_LINK_EXISTING: bool = True`
- [ ] Add `OAUTH_ALLOW_SIGNUP: bool = True`
- [ ] Add `OAUTH_STATE_TTL_SECONDS: int = 600`
- [ ] Per provider: `{PROVIDER}_CLIENT_ID` and `{PROVIDER}_CLIENT_SECRET`
- [ ] Add to `.env.example` with placeholders
- [ ] Confirm the app raises `ValidationError` on startup when `OAUTH_TOKEN_FERNET_KEY` is unset in `tests/test_oauth.py::test_app_refuses_start_without_fernet_key`

### 15.3 Crypto module
- [ ] Create `app/core/oauth/crypto.py`
- [ ] Implement `encrypt_token` and `decrypt_token`
- [ ] Verify file parses
- [ ] Confirm `decrypt_token(encrypt_token(token)) == token` round-trip in `tests/test_oauth_crypto.py::test_fernet_round_trip`
- [ ] Run `ruff check app/core/oauth/crypto.py` and `mypy app/core/oauth/crypto.py --strict` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG entry documenting Fernet encryption for provider access/refresh tokens at rest

### 15.4 State module
- [ ] Create `app/core/oauth/state.py`
- [ ] Implement `OAuthState` dataclass
- [ ] Implement `generate_pkce_pair`
- [ ] Implement `store_state` (SETEX)
- [ ] Implement `consume_state` (pipeline GET+DEL)
- [ ] Verify file parses
- [ ] Test that state token replay within the 5-minute window fails with HTTP 400 Bad Request in `tests/test_oauth.py::test_state_token_replay_returns_400`
- [ ] Confirm `consume_state` atomically deletes the key so a concurrent second call returns `None` (single-use), verified with two near-simultaneous calls in `tests/test_oauth_state.py::test_consume_state_single_use`

### 15.5 Provider abstraction
- [ ] Create `app/core/oauth/base.py` with ABC + dataclasses
- [ ] Create `app/core/oauth/google.py` for each provider in `providers` param
- [ ] Create `app/core/oauth/github.py`, `facebook.py`, `microsoft.py` as needed
- [ ] Create `app/core/oauth/registry.py`
- [ ] Verify files parse
- [ ] Confirm `GoogleOAuthProvider.get_user_info` parses the `email_verified` field and raises `HTTPException(400)` when it is `false`, via a `respx` mock in `tests/test_oauth.py::test_google_unverified_email_returns_400`
- [ ] Verify `OAuthRegistry.get("github")` returns a `GitHubOAuthProvider` instance and that requesting an unregistered provider raises `KeyError` in `tests/test_oauth.py::test_registry_unknown_provider_raises`

### 15.6 Model
- [ ] Create `app/models/oauth_account.py`
- [ ] Add UniqueConstraint and CheckConstraint
- [ ] Verify file parses
- [ ] Confirm `UniqueConstraint("provider", "provider_user_id")` exists in `OAuthAccount.__table_args__` by inspecting `sqlalchemy.inspect` in `tests/test_oauth_model.py::test_unique_constraint_provider_user_id`
- [ ] Run `ruff check app/models/oauth_account.py` and `mypy app/models/oauth_account.py --strict` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG entry documenting `oauth_accounts` table and nullable `users.hashed_password` migration

### 15.7 CRUD
- [ ] Create `app/crud/oauth_account.py` with `get`, `upsert`
- [ ] Verify file parses
- [ ] Confirm `upsert` updates `access_token_encrypted` and `token_expires_at` when the account already exists, not creating a duplicate row, in `tests/test_oauth.py::test_upsert_updates_existing_account`
- [ ] Run `ruff check app/crud/oauth_account.py` and `mypy app/crud/oauth_account.py --strict` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG note that `upsert` stores the encrypted token via `encrypt_token` (never plaintext)
- [ ] Add structured log event `oauth.callback.success` with fields `provider`, `user_id`, `is_new_user` emitted in `oauth_callback` after successful login or signup

### 15.8 Routes
- [ ] Create `app/api/routes/oauth.py`
- [ ] Implement `oauth_login` and `oauth_callback`
- [ ] Validate `return_to` starts with `/`
- [ ] Validate `state.provider == provider`
- [ ] Validate `email_verified=true`
- [ ] Add to `app/api/main.py` router
- [ ] Verify file parses

### 15.9 User CRUD extension
- [ ] Add `crud_user.create_oauth_user(email, name)` helper
- [ ] Add `crud_user.get_by_email`
- [ ] Verify file parses
- [ ] Confirm `create_oauth_user` sets `hashed_password=None` (OAuth-only account) in `tests/test_oauth.py::test_create_oauth_user_has_null_password`
- [ ] Run `ruff check app/crud/user.py` and `mypy app/crud/user.py --strict` with zero new findings after the extension
- [ ] Add `## [Unreleased]` CHANGELOG note that `crud_user.get_by_email` is now exposed for OAuth linking flow

### 15.10 Migration
- [ ] Generate `0NNN_add_oauth2_provider.py`
- [ ] `upgrade()` creates table + relaxes hashed_password to nullable
- [ ] `downgrade()` drops table + restores NOT NULL (with caveat note)
- [ ] Verify migration parses
- [ ] Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a clean Postgres container and assert each step exits with code 0
- [ ] Confirm `users.hashed_password` is nullable after `alembic upgrade head`: `psql -c "\d users" | grep hashed_password` must show no `not null`
- [ ] Run `ruff check alembic/versions/0NNN_add_oauth2_provider.py` with zero findings

### 15.11 Test generation
- [ ] Create `tests/test_oauth.py` with all 30 tests
- [ ] Use `respx` to mock provider HTTPS calls
- [ ] Verify file parses
- [ ] Run `pytest tests/test_oauth.py -v` and confirm all 30 cases pass including state replay and unverified-email tests
- [ ] Run `ruff check tests/test_oauth.py` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG entry documenting 30 new OAuth test cases covering login, signup, link-existing, replay attack, and unverified email scenarios

### 15.12 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created table on failure
- [ ] Inject a failure after writing `app/core/oauth/crypto.py` but before `app/core/oauth/state.py` and assert `app/core/oauth/crypto.py` is removed from disk after rollback in `tests/test_tool_atomicity.py::test_oauth_rollback_on_state_write`
- [ ] Verify no stale `.tmp` files under `app/core/oauth/` after forced failure: `list(Path('app/core/oauth').glob('*.tmp'))` must be empty
- [ ] Run `ruff check app/core/oauth/base.py app/core/oauth/registry.py` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG atomicity note documenting the rollback path and the `files_rolled_back` field

### 15.13 Documentation
- [ ] Append OAuth section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Confirm `manifest.yaml` contains `fastapi_add_oauth2_provider` entry: `python -c "import yaml; d=yaml.safe_load(open('manifest.yaml')); assert any(t['name']=='fastapi_add_oauth2_provider' for t in d['tools'])"`
- [ ] Verify `core/KNOWLEDGE.md` OAuth section documents PKCE (S256), Fernet token storage, state TTL, and the `email_verified` requirement
- [ ] Run `ruff check app/api/routes/oauth.py app/crud/oauth_account.py` with zero findings

### 15.14 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Run `pytest tests/test_oauth.py -v` and confirm all 30 OAuth test cases pass with zero skips
- [ ] Run `pytest tests/ --ignore=tests/test_oauth.py -q` and confirm zero regressions on previously-green tests

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/oauth_account.py",
    "app/core/oauth/__init__.py",
    "app/core/oauth/base.py",
    "app/core/oauth/google.py",
    "app/core/oauth/github.py",
    "app/core/oauth/registry.py",
    "app/core/oauth/state.py",
    "app/core/oauth/crypto.py",
    "app/crud/oauth_account.py",
    "app/api/routes/oauth.py",
    "alembic/versions/0011_add_oauth2_provider.py",
    "tests/test_oauth.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py",
    "app/crud/user.py",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 4521,
    "files_changed": 16,
    "lines_added": 1102,
    "lines_removed": 8,
    "providers_installed": ["google", "github"],
    "allow_signup": true,
    "link_existing": true
  },
  "next_steps": [
    "Set OAUTH_TOKEN_FERNET_KEY in your .env (`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`)",
    "Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET",
    "Run: alembic upgrade head",
    "Run: pytest tests/test_oauth.py -v",
    "Add 'Login with Google' button on your frontend pointing to /api/v1/auth/oauth/google/login"
  ],
  "warnings": [
    "OAUTH_TOKEN_FERNET_KEY is REQUIRED. App refuses to start without it.",
    "users.hashed_password is now NULL-able to support OAuth-only accounts. Make sure password-login code paths handle this gracefully.",
    "If multi-tenancy is installed, decide how new OAuth users are assigned to tenants and document it."
  ],
  "notes": [
    "OAuth installed for providers: google, github.",
    "PKCE (S256) enabled.",
    "State token TTL: 600s, single-use via pipeline GET+DEL.",
    "Fernet encryption for provider tokens at rest.",
    "Existing tests still pass: 56/56."
  ]
}
```
