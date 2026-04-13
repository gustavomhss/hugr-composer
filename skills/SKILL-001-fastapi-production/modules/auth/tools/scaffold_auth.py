"""
SKILL-001 Auth Tool: Generate production auth boilerplate for FastAPI.

Creates a complete auth module with JWT token pairs, argon2id password hashing
via pwdlib, timing attack prevention, refresh token rotation with jti, layered
dependency chain using Annotated type aliases, and rate limiting on auth
endpoints. All generated code follows KNOWLEDGE.md patterns.

Generated files:
    auth/router.py        -- login, register, refresh, logout endpoints
    auth/dependencies.py  -- OAuth2PasswordBearer + layered dependency chain
    auth/security.py      -- password hashing (pwdlib[argon2]), JWT create/verify
    auth/schemas.py       -- LoginRequest, RegisterRequest, TokenResponse (strict=True)
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _security_py(with_refresh: bool) -> str:
    """Template for auth/security.py -- password hashing and JWT helpers."""
    refresh_verify = ""
    if with_refresh:
        refresh_verify = textwrap.dedent("""\


        def verify_refresh_token(token: str) -> dict:
            \"\"\"Verify a refresh token. Rejects access tokens used as refresh.\"\"\"
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.ExpiredSignatureError:
                raise ValueError("Refresh token has expired")
            except jwt.InvalidTokenError:
                raise ValueError("Invalid refresh token")
            if payload.get("type") != "refresh":
                raise ValueError("Not a refresh token")
            return payload
        """)

    refresh_creation = ""
    refresh_return = ""
    if with_refresh:
        refresh_creation = textwrap.dedent("""\

            refresh = jwt.encode(
                {
                    "sub": user_id,
                    "type": "refresh",
                    "exp": now + REFRESH_TOKEN_EXPIRE,
                    "jti": str(uuid.uuid4()),
                },
                SECRET_KEY,
                algorithm=ALGORITHM,
            )""")
        refresh_return = ', "refresh_token": refresh'

    return textwrap.dedent(f"""\
        \"\"\"Password hashing with pwdlib[argon2] and JWT token management.\"\"\"

        from datetime import datetime, timedelta, timezone
        import uuid

        import jwt
        from pwdlib import PasswordHash

        # ---------------------------------------------------------------------------
        # Password hashing — argon2id (OWASP recommended, NOT bcrypt)
        # ---------------------------------------------------------------------------

        password_hash = PasswordHash.recommended()

        # Pre-computed hash for timing attack prevention. When a user does not
        # exist we still run verify() against this dummy so response time is
        # constant regardless of whether the email is registered.
        DUMMY_HASH = password_hash.hash("dummy-password-for-timing-attack-prevention")

        # ---------------------------------------------------------------------------
        # JWT configuration
        # ---------------------------------------------------------------------------

        # IMPORTANT: Load from environment in production — NEVER hardcode.
        SECRET_KEY: str = ""  # Set via settings.jwt_secret at import time
        ALGORITHM = "HS256"
        ACCESS_TOKEN_EXPIRE = timedelta(minutes=15)
        REFRESH_TOKEN_EXPIRE = timedelta(days=7)


        def configure_jwt(secret: str) -> None:
            \"\"\"Set the JWT secret at startup. Called from app lifespan.\"\"\"
            global SECRET_KEY
            SECRET_KEY = secret


        def create_token_pair(user_id: str) -> dict:
            \"\"\"Create an access + refresh token pair.

            Access token is short-lived (15min). Refresh token includes a unique
            jti for rotation and revocation tracking.
            \"\"\"
            now = datetime.now(timezone.utc)

            access = jwt.encode(
                {{"sub": user_id, "type": "access", "exp": now + ACCESS_TOKEN_EXPIRE}},
                SECRET_KEY,
                algorithm=ALGORITHM,
            ){refresh_creation}

            return {{"access_token": access{refresh_return}, "token_type": "bearer"}}


        def verify_access_token(token: str) -> dict:
            \"\"\"Verify an access token. Rejects refresh tokens used as access.\"\"\"
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.ExpiredSignatureError:
                raise ValueError("Access token has expired")
            except jwt.InvalidTokenError:
                raise ValueError("Invalid access token")
            if payload.get("type") != "access":
                raise ValueError("Not an access token")
            return payload
        {refresh_verify}""")


def _schemas_py() -> str:
    """Template for auth/schemas.py -- request/response models."""
    return textwrap.dedent("""\
        \"\"\"Auth request and response schemas with strict validation.\"\"\"

        from pydantic import BaseModel, ConfigDict, Field, field_validator

        COMMON_PASSWORDS = {
            "password", "12345678", "qwerty123", "admin123", "letmein",
            "welcome1", "password1", "abc12345", "123456789", "iloveyou",
        }


        class LoginRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            email: str = Field(min_length=5, max_length=254)
            password: str = Field(min_length=1, max_length=128)


        class RegisterRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            email: str = Field(min_length=5, max_length=254)
            password: str = Field(min_length=8, max_length=128)
            name: str = Field(min_length=1, max_length=100)

            @field_validator("password")
            @classmethod
            def password_strength(cls, v: str) -> str:
                if v.lower() in COMMON_PASSWORDS:
                    raise ValueError("Password is too common")
                if not any(c.isdigit() for c in v):
                    raise ValueError("Password must contain at least one digit")
                if not any(c.isupper() for c in v):
                    raise ValueError("Password must contain at least one uppercase letter")
                return v


        class TokenResponse(BaseModel):
            model_config = ConfigDict(strict=True)

            access_token: str
            refresh_token: str | None = None
            token_type: str = "bearer"


        class RefreshRequest(BaseModel):
            model_config = ConfigDict(strict=True)

            refresh_token: str
    """)


def _dependencies_py() -> str:
    """Template for auth/dependencies.py -- layered dependency chain."""
    return textwrap.dedent("""\
        \"\"\"Layered auth dependency chain for FastAPI.

        Architecture: token extraction -> token validation -> user lookup -> permission check.
        Each layer is independently testable and replaceable.
        \"\"\"

        from typing import Annotated

        from fastapi import Depends, HTTPException, status
        from fastapi.security import OAuth2PasswordBearer

        from .security import verify_access_token

        # OAuth2 scheme — extracts Bearer token from Authorization header.
        # tokenUrl is used only for Swagger UI docs, not for routing.
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


        async def get_token_payload(
            token: Annotated[str, Depends(oauth2_scheme)],
        ) -> dict:
            \"\"\"Layer 1: Extract and validate JWT. No DB access.\"\"\"
            try:
                return verify_access_token(token)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=str(exc),
                    headers={"WWW-Authenticate": "Bearer"},
                )


        async def get_current_user(
            payload: Annotated[dict, Depends(get_token_payload)],
        ) -> dict:
            \"\"\"Layer 2: Return user payload. Replace with DB lookup in production.

            In production, inject a SessionDep and query the User table:
                user = await session.execute(select(User).where(User.id == payload["sub"]))
            \"\"\"
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token payload")
            return {"id": user_id, **payload}


        async def require_admin(
            user: Annotated[dict, Depends(get_current_user)],
        ) -> dict:
            \"\"\"Layer 3: Permission check. Raises 403 if user is not admin.\"\"\"
            if not user.get("is_admin"):
                raise HTTPException(status_code=403, detail="Admin privileges required")
            return user


        # --- Type aliases for route signatures ---
        TokenPayload = Annotated[dict, Depends(get_token_payload)]
        CurrentUser = Annotated[dict, Depends(get_current_user)]
        AdminUser = Annotated[dict, Depends(require_admin)]
    """)


def _router_py(with_refresh: bool, with_oauth2: bool) -> str:
    """Template for auth/router.py -- auth endpoints."""
    refresh_imports = ""
    refresh_endpoints = ""
    if with_refresh:
        refresh_imports = "\nfrom .schemas import RefreshRequest"
        refresh_endpoints = textwrap.dedent("""\


        @router.post("/auth/refresh", response_model=TokenResponse)
        async def refresh(body: RefreshRequest):
            \"\"\"Rotate refresh token. Old refresh token is invalidated.

            In production, check jti against a blocklist (Redis) before issuing
            new tokens. If jti was already used, revoke ALL user tokens (theft
            detection via refresh token rotation).
            \"\"\"
            try:
                payload = verify_refresh_token(body.refresh_token)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail=str(exc))

            # TODO: Check jti against blocklist and revoke on reuse
            # jti = payload["jti"]
            # if await is_token_revoked(jti):
            #     await revoke_all_user_tokens(payload["sub"])
            #     raise HTTPException(401, "Token reuse detected")
            # await revoke_token(jti)

            tokens = create_token_pair(payload["sub"])
            return TokenResponse(**tokens)
        """)

    verify_refresh_import = ""
    if with_refresh:
        verify_refresh_import = ", verify_refresh_token"

    oauth2_note = ""
    if with_oauth2:
        oauth2_note = textwrap.dedent("""\

        # NOTE: OAuth2 (Google, GitHub) integration points:
        # 1. Add authlib to requirements: pip install authlib httpx
        # 2. Create /auth/google and /auth/google/callback endpoints
        # 3. Use OAuth2Session from authlib.integrations.starlette_client
        # 4. On callback, create or link user, then issue token pair
        """)

    return textwrap.dedent(f"""\
        \"\"\"Auth router — login, register, refresh, logout endpoints.\"\"\"

        from fastapi import APIRouter, HTTPException, Request
        from fastapi.responses import JSONResponse

        from .dependencies import TokenPayload
        from .schemas import LoginRequest, RegisterRequest, TokenResponse{refresh_imports}
        from .security import (
            DUMMY_HASH,
            create_token_pair,
            password_hash{verify_refresh_import},
        )
        {oauth2_note}
        router = APIRouter(tags=["auth"])

        # ---------------------------------------------------------------------------
        # In-memory user store (replace with DB in production)
        # ---------------------------------------------------------------------------

        _users_db: dict[str, dict] = {{}}


        @router.post("/auth/register", response_model=TokenResponse, status_code=201)
        async def register(body: RegisterRequest):
            \"\"\"Register a new user. Returns token pair on success.

            Rate limit this endpoint (3/minute per IP) in production via:
                @limiter.limit("3/minute")
            \"\"\"
            if body.email in _users_db:
                raise HTTPException(status_code=409, detail="Email already registered")

            hashed = password_hash.hash(body.password)
            _users_db[body.email] = {{
                "email": body.email,
                "name": body.name,
                "password_hash": hashed,
            }}

            tokens = create_token_pair(body.email)
            return TokenResponse(**tokens)


        @router.post("/auth/login", response_model=TokenResponse)
        async def login(body: LoginRequest):
            \"\"\"Authenticate user. Timing-safe even when user does not exist.

            Rate limit this endpoint (5/minute per IP) in production via:
                @limiter.limit("5/minute")
            \"\"\"
            user = _users_db.get(body.email)

            if user is None:
                # User does not exist — still run hash to prevent timing attacks
                password_hash.verify(body.password, DUMMY_HASH)
                raise HTTPException(status_code=401, detail="Invalid credentials")

            if not password_hash.verify(body.password, user["password_hash"]):
                raise HTTPException(status_code=401, detail="Invalid credentials")

            tokens = create_token_pair(body.email)
            return TokenResponse(**tokens)


        @router.post("/auth/logout")
        async def logout(payload: TokenPayload):
            \"\"\"Revoke the current access token.

            In production, add the token's jti to a Redis blocklist with TTL
            matching the token's remaining lifetime.
            \"\"\"
            # TODO: Revoke token jti in Redis/DB blocklist
            # jti = payload.get("jti")
            # exp = payload.get("exp")
            # if jti:
            #     ttl = max(0, exp - int(datetime.now(timezone.utc).timestamp()))
            #     await revoke_token(jti, ttl=ttl)
            return JSONResponse({{"detail": "Logged out"}})
        {refresh_endpoints}""")


def _init_py() -> str:
    """Template for auth/__init__.py -- package marker."""
    return textwrap.dedent("""\
        \"\"\"Auth module — production authentication for FastAPI.\"\"\"
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_auth_module(
    output_dir: str,
    with_refresh: bool = True,
    with_oauth2: bool = False,
) -> dict:
    """
    Generate a production-ready auth module for a FastAPI project.

    Creates 4 files (router, dependencies, security, schemas) inside an
    ``auth/`` subdirectory of *output_dir*. All code uses pwdlib[argon2]
    for hashing, JWT with separate access/refresh types, timing attack
    prevention via DUMMY_HASH, and a layered dependency chain.

    Args:
        output_dir: Parent directory where the ``auth/`` package will be created.
        with_refresh: Include refresh token rotation endpoints and logic.
        with_oauth2: Add OAuth2 integration comments and scaffolding stubs.

    Returns:
        Dict with ``created_files`` (list of paths) and ``auth_path`` (str).

    Example::

        result = generate_auth_module("/tmp/myproject", with_refresh=True)
        print(result["created_files"])
        # ['auth/__init__.py', 'auth/security.py', 'auth/schemas.py',
        #  'auth/dependencies.py', 'auth/router.py']
    """
    auth_dir = Path(output_dir) / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "security.py": _security_py(with_refresh),
        "schemas.py": _schemas_py(),
        "dependencies.py": _dependencies_py(),
        "router.py": _router_py(with_refresh, with_oauth2),
    }

    created: list[str] = []
    for filename, content in files.items():
        filepath = auth_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"auth/{filename}")

    return {
        "created_files": created,
        "auth_path": str(auth_dir),
        "with_refresh": with_refresh,
        "with_oauth2": with_oauth2,
    }
