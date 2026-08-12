---
spec_id: "TOOL-010"
tool_name: "add_api_key_auth"
primitive: "auth/RequestGuard"
primitive_path: "core.venous.auth.RequestGuard"
generator: "generators/auth/deps.py"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-AK-01"
  - "INV-AK-02"
  - "INV-AK-03"
  - "INV-AK-04"
  - "INV-AK-05"
  - "INV-AK-06"
  - "INV-AK-07"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
  - "CC-25"
  - "CC-26"
  - "CC-27"
  - "CC-28"
  - "CC-29"
  - "CC-30"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
  - "T-25"
  - "T-26"
  - "T-27"
  - "T-28"
  - "T-29"
  - "T-30"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-010: add_api_key_auth

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_api_key_auth` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User), Alembic, optional Redis (for rate limiting) |
| Signature | `add_api_key_auth(project_dir: str, hash_algorithm: Literal["argon2id", "sha256_pepper"] = "sha256_pepper", default_scopes: list[str] | None = None, rate_limit_per_minute: int = 600) -> dict` |
| Parameters | `project_dir`: project root path<br>`hash_algorithm`: how to hash the secret at rest<br>`default_scopes`: scopes auto-assigned to new keys (None = `["read"]`)<br>`rate_limit_per_minute`: per-key rate limit (Redis-backed if Redis present, in-process otherwise) |

---

## 2. Purpose

The `fastapi_add_api_key_auth` tool adds first-class API-key authentication so that machines — CI jobs, cron scripts, third-party integrations, partner services — can call the API without going through an interactive user OAuth flow that requires a human at a browser. Without this tool teams either hack a static bearer token into the codebase (which cannot be revoked, scoped, or audited), copy OAuth credentials into a service account (which conflates machine-to-machine with user-to-machine semantics), or build their own ad-hoc key system that forgets rate limiting, auditing, or hashing and becomes the vector for the next breach.

Keys are issued per user or per service account, scoped via `resource:action` strings (`orders:read`, `billing:write`, `*:*` for superadmin), revocable instantly via a single admin endpoint, rate-limited per-key so one runaway script cannot exhaust the global budget, and audited on every call via TOOL-005 so compliance has evidence of exactly which key did what and when. The plaintext secret is shown exactly once at creation (`sk_live_<prefix><secret>`); storage uses a fast-lookup `prefix` column for log-friendly debugging plus an **Argon2id-hashed** secret for verification, so database compromise does not leak usable credentials and secret comparison runs in constant time. Key design decisions: Argon2id over bcrypt (modern, GPU-resistant), 256 bits of entropy per key, `sk_live_`/`sk_test_` environment prefixes so a test key accidentally leaking into production is detected on use, TTL-based rotation hooks that let operators roll keys without downtime, and deny-by-default rate limiting with per-key overrides stored alongside the key record.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Dev waits in CLI |
| Files modified | ≤ 4 global files | Predictability |
| Files created | ≥ 9 (model, crud, routes, schemas, deps, hasher, rate_limit, migration, tests) | Predictability |
| API key verification latency p99 | < 5 ms | Indexed lookup by `key_id` + constant-time hash compare |
| Rate-limit check latency p99 | < 1 ms (Redis) / < 0.1 ms (in-process) | Atomic INCR + EXPIRE |
| Migration runtime | < 5s on empty table (new table only) | One new table |
| Memory overhead | < 1 MB per worker | No in-memory key cache by default |
| Plaintext secret exposure | Exactly 1 time, on creation | Never logged, never returned in subsequent reads |

---

## 4. Code Examples (Before / After)

### 4.1 Model (NEW)
```python
# app/models/api_key.py
from datetime import datetime
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    last_used_ua: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_api_keys_status",
        ),
        CheckConstraint(
            "key_id ~ '^[a-z0-9]{16,32}$'",
            name="ck_api_keys_key_id_format",
        ),
        Index("ix_api_keys_user_status", "user_id", "status"),
    )
```

### 4.2 Hasher (NEW)
```python
# app/core/api_key_hasher.py
"""
API key secret hashing.

Two strategies:
- argon2id: slow, expensive (50ms). Highest security. Recommended for low-volume keys.
- sha256_pepper: fast (< 1ms). Recommended for high-volume keys; relies on a server-side
  pepper kept in env var (NEVER in DB).

The plaintext secret is generated client-side using `secrets.token_urlsafe(32)`.
"""
import hashlib
import hmac
import secrets
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()
_PEPPER = settings.API_KEY_PEPPER.encode("utf-8")  # raises if missing


def generate_secret() -> str:
    """Return a URL-safe 32-byte random secret."""
    return secrets.token_urlsafe(32)


def generate_key_id() -> str:
    """Return a 16-char lowercase alphanumeric key_id."""
    return secrets.token_hex(8)  # 16 hex chars


def hash_secret(secret: str, algorithm: Literal["argon2id", "sha256_pepper"] = "sha256_pepper") -> str:
    if algorithm == "argon2id":
        return f"argon2$${_ph.hash(secret)}"
    return f"sha256$${hmac.new(_PEPPER, secret.encode('utf-8'), hashlib.sha256).hexdigest()}"


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time verification."""
    if not stored_hash:
        return False
    if stored_hash.startswith("argon2$$"):
        try:
            _ph.verify(stored_hash[len("argon2$$"):], secret)
            return True
        except VerifyMismatchError:
            return False
    if stored_hash.startswith("sha256$$"):
        expected = hmac.new(_PEPPER, secret.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, stored_hash[len("sha256$$"):])
    return False
```

### 4.3 Dependency (NEW)
```python
# app/core/api_key_deps.py
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.core.api_key_hasher import verify_secret
from app.core.api_key_rate_limit import check_rate_limit
from app.models.api_key import APIKey
from app.models.user import User

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


def _parse_header(header_value: str | None) -> tuple[str, str] | None:
    """
    Authorization header is `Bearer api_<key_id>_<secret>`.
    Returns (key_id, secret) or None if malformed.
    """
    if not header_value:
        return None
    if not header_value.startswith("Bearer "):
        return None
    token = header_value[len("Bearer "):]
    if not token.startswith("api_"):
        return None
    parts = token.split("_", 2)
    if len(parts) != 3:
        return None
    _, key_id, secret = parts
    if not key_id or not secret:
        return None
    return key_id, secret


async def get_current_api_key(
    request: Request,
    session: SessionDep,
    header_value: Annotated[str | None, Depends(api_key_header)],
) -> APIKey:
    parsed = _parse_header(header_value)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    key_id, secret = parsed

    # Indexed lookup by key_id
    stmt = select(APIKey).where(APIKey.key_id == key_id)
    api_key = (await session.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        # Constant-time fake check to prevent enumeration
        verify_secret(secret, "sha256$$" + "0" * 64)
        raise HTTPException(401, "Invalid API key")

    if not verify_secret(secret, api_key.secret_hash):
        raise HTTPException(401, "Invalid API key")

    if api_key.status != "active":
        raise HTTPException(401, "API key is not active")

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        api_key.status = "expired"
        await session.flush()
        raise HTTPException(401, "API key expired")

    # Rate limit
    if not await check_rate_limit(api_key.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    # Audit (best-effort, non-blocking write)
    api_key.last_used_at = datetime.now(timezone.utc)
    api_key.last_used_ip = request.client.host if request.client else None
    api_key.last_used_ua = request.headers.get("user-agent", "")[:500]
    await session.flush()

    return api_key


def require_scope(scope: str):
    """
    FastAPI dependency that ensures the calling API key has the given scope.

    Usage:
        @router.post("/items/", dependencies=[Depends(require_scope("write"))])
    """

    async def dep(api_key: Annotated[APIKey, Depends(get_current_api_key)]) -> None:
        if "admin" in api_key.scopes:
            return
        if scope not in api_key.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {scope}",
            )

    return dep
```

### 4.4 Rate limit (NEW)
```python
# app/core/api_key_rate_limit.py
import time
from uuid import UUID

from app.core.config import settings
from app.core.redis import get_redis_or_none

WINDOW_SECONDS = 60
LIMIT = settings.API_KEY_RATE_LIMIT_PER_MINUTE


async def check_rate_limit(key_id: UUID) -> bool:
    """
    Atomic INCR + EXPIRE on Redis. Returns True if under limit, False if exceeded.
    Falls back to in-process counter if Redis is unavailable.
    """
    redis = await get_redis_or_none()
    if redis is None:
        return _check_in_process(key_id)

    bucket = int(time.time() // WINDOW_SECONDS)
    redis_key = f"api_key:rate:{key_id}:{bucket}"
    pipe = redis.pipeline()
    pipe.incr(redis_key)
    pipe.expire(redis_key, WINDOW_SECONDS * 2)
    count, _ = await pipe.execute()
    return count <= LIMIT


# In-process fallback (best-effort, per-worker)
_local_counters: dict[tuple[UUID, int], int] = {}


def _check_in_process(key_id: UUID) -> bool:
    bucket = int(time.time() // WINDOW_SECONDS)
    # Garbage-collect old buckets
    for k in list(_local_counters):
        if k[1] != bucket:
            _local_counters.pop(k, None)
    cur = _local_counters.get((key_id, bucket), 0) + 1
    _local_counters[(key_id, bucket)] = cur
    return cur <= LIMIT
```

### 4.5 Routes (NEW, admin/owner only)
```python
# app/api/routes/api_keys.py
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.core.api_key_hasher import generate_key_id, generate_secret, hash_secret
from app.crud import api_key as crud_api_key
from app.schemas.api_key import (
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyPublic,
    APIKeyUpdate,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("/", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: APIKeyCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> APIKeyCreatedResponse:
    key_id = generate_key_id()
    secret = generate_secret()
    secret_hash = hash_secret(secret)
    plaintext_token = f"api_{key_id}_{secret}"

    api_key = await crud_api_key.create(
        session,
        key_in=key_in,
        user_id=current_user.id,
        key_id=key_id,
        secret_hash=secret_hash,
    )

    # Plaintext token is returned ONCE here. Never again.
    return APIKeyCreatedResponse(
        api_key=APIKeyPublic.model_validate(api_key),
        plaintext_token=plaintext_token,
        warning="Store this token now. It will NOT be shown again.",
    )


@router.get("/", response_model=list[APIKeyPublic])
async def list_my_api_keys(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[APIKeyPublic]:
    keys = await crud_api_key.list_for_user(session, user_id=current_user.id)
    return [APIKeyPublic.model_validate(k) for k in keys]


@router.post("/{key_id}/rotate", response_model=APIKeyCreatedResponse)
async def rotate_api_key(
    key_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> APIKeyCreatedResponse:
    api_key = await crud_api_key.get_by_key_id(session, key_id=key_id)
    if not api_key or api_key.user_id != current_user.id:
        raise HTTPException(404)
    new_secret = generate_secret()
    api_key.secret_hash = hash_secret(new_secret)
    await session.flush()
    plaintext_token = f"api_{api_key.key_id}_{new_secret}"
    return APIKeyCreatedResponse(
        api_key=APIKeyPublic.model_validate(api_key),
        plaintext_token=plaintext_token,
        warning="Old secret is now invalid. Update your client immediately.",
    )


@router.post("/{key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    api_key = await crud_api_key.get_by_key_id(session, key_id=key_id)
    if not api_key or api_key.user_id != current_user.id:
        raise HTTPException(404)
    await crud_api_key.revoke(session, api_key=api_key)
```

### 4.6 Migration
```python
# alembic/versions/0010_add_api_key_auth.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET


revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key_id", sa.String(32), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("scopes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", INET(), nullable=True),
        sa.Column("last_used_ua", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active','revoked','expired')", name="ck_api_keys_status"),
        sa.CheckConstraint("key_id ~ '^[a-z0-9]{16,32}$'", name="ck_api_keys_key_id_format"),
    )
    op.create_index("ix_api_keys_key_id", "api_keys", ["key_id"], unique=True)
    op.create_index("ix_api_keys_user_status", "api_keys", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_status", "api_keys")
    op.drop_index("ix_api_keys_key_id", "api_keys")
    op.drop_table("api_keys")
```

---

### 4.10 API key generator and verifier
```python
# app/auth/api_key_generator.py
"""Generate, hash, verify, and prefix-parse API keys.

The public part of every key is `sk_{env}_{prefix}...` — the `prefix`
is stored in plaintext for log-friendly debugging while the secret
suffix is hashed with Argon2id and never stored in plaintext.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)
_KEY_BYTES = 32  # 256 bits of entropy
_PREFIX_LEN = 8


@dataclass(frozen=True)
class GeneratedKey:
    plaintext: str       # full key, shown to user exactly once
    prefix: str          # public debugging prefix (8 chars)
    hashed_secret: str   # Argon2id hash stored in DB


def generate_api_key(environment: str = "live") -> GeneratedKey:
    if environment not in {"live", "test"}:
        raise ValueError(f"environment must be 'live' or 'test', got {environment!r}")
    raw = secrets.token_urlsafe(_KEY_BYTES)
    prefix = raw[:_PREFIX_LEN]
    plaintext = f"sk_{environment}_{raw}"
    hashed_secret = _hasher.hash(raw)
    return GeneratedKey(plaintext=plaintext, prefix=prefix, hashed_secret=hashed_secret)


def verify_api_key(presented_plaintext: str, stored_hash: str) -> bool:
    """Constant-time verify using Argon2 — never log the presented key."""
    if not presented_plaintext or not stored_hash:
        return False
    parts = presented_plaintext.split("_", 2)
    if len(parts) != 3:
        return False
    raw = parts[2]
    try:
        _hasher.verify(stored_hash, raw)
    except VerifyMismatchError:
        return False
    return True


def extract_prefix(presented_plaintext: str) -> str | None:
    """Return the 8-char public prefix if the key looks valid, else None."""
    parts = presented_plaintext.split("_", 2)
    if len(parts) != 3:
        return None
    return parts[2][:_PREFIX_LEN]
```

### 4.11 Scope evaluator with wildcard support
```python
# app/auth/api_key_scopes.py
"""Evaluate the requested scope against a key's granted scopes.

Scopes are strings like `orders:read`, `orders:write`, `admin:*`, `*:*`.
The evaluator supports wildcards on resource or action segments so
operators can grant `orders:*` meaning every action on orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ScopeCheckResult:
    allowed: bool
    matched_scope: str | None
    reason: str


def _scope_matches(granted: str, required: str) -> bool:
    g_resource, _, g_action = granted.partition(":")
    r_resource, _, r_action = required.partition(":")
    resource_ok = g_resource == "*" or g_resource == r_resource
    action_ok = g_action == "*" or g_action == r_action
    return resource_ok and action_ok


def evaluate_scope(granted_scopes: Iterable[str], required_scope: str) -> ScopeCheckResult:
    required_scope = required_scope.strip()
    if ":" not in required_scope:
        return ScopeCheckResult(False, None, f"required scope must be 'resource:action', got {required_scope!r}")
    for scope in granted_scopes:
        if _scope_matches(scope, required_scope):
            return ScopeCheckResult(True, scope, "matched")
    return ScopeCheckResult(False, None, f"no granted scope matches {required_scope!r}")
```



## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Plaintext secret is shown exactly once** | The CREATE endpoint returns it inside `APIKeyCreatedResponse`. All other endpoints return only `APIKeyPublic` (no secret, no hash). |
| QS-2 | **Secret comparison is constant-time** | `hmac.compare_digest` for sha256 path; argon2 verify is constant-time by design. Prevents timing attacks. |
| QS-3 | **Unknown key_id triggers a fake hash check** | To prevent enumeration timing oracles, the dep performs a dummy `verify_secret` even when `key_id` doesn't exist. |
| QS-4 | **Pepper is mandatory** | `settings.API_KEY_PEPPER` raises at startup if missing. Pepper NEVER stored in DB. |
| QS-5 | **Revocation is immediate** | Setting `status='revoked'` causes the next verification to return 401. No cache; next request hits DB. (If a cache is added later, it MUST be invalidated on revoke.) |
| QS-6 | **Scopes use deny-by-default** | `require_scope("X")` requires `X` (or `admin`) explicitly in `api_key.scopes`. No wildcard fallback. |
| QS-7 | **Rate limit always enforced** | If Redis is up: per-key sliding window. Otherwise: in-process counter (best-effort, per-worker). Never disabled. |
| QS-8 | **Audit fields updated on every successful call** | `last_used_at`, `last_used_ip`, `last_used_ua` updated in the same transaction. |
| QS-9 | **Expired keys auto-update status** | First request after expiry sets `status='expired'` so subsequent requests return faster paths. |
| QS-10 | **Token format is unambiguous** | `api_<key_id>_<secret>` prefix `api_` makes it grep-able for accidental commits; tools like trufflehog can detect leaked keys. |
| QS-11 | **Owner check on rotate/revoke** | A user can only manage keys where `user_id = current_user.id`. No exception for non-superadmins. |
| QS-12 | **All write operations pass input validation before touching storage** | Enforced by Pydantic v2 schema validation in `app/schemas/` — every request body is parsed and rejected with 422 on malformed data, verified by `tests/test_schemas.py::test_validation` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `APIKey` model exists at `app/models/api_key.py` | File exists |
| CC-02 | `app/core/api_key_hasher.py` exists with `generate_secret/key_id/hash/verify` | File exists |
| CC-03 | `app/core/api_key_deps.py` exists with `get_current_api_key` + `require_scope` | File exists |
| CC-04 | `app/core/api_key_rate_limit.py` exists with `check_rate_limit` (Redis + fallback) | File exists |
| CC-05 | `app/crud/api_key.py` exists with `create/get_by_key_id/list_for_user/revoke` | File exists |
| CC-06 | `app/api/routes/api_keys.py` exists with create/list/rotate/revoke endpoints | File exists |
| CC-07 | `app/schemas/api_key.py` has `APIKeyCreate/Update/Public/CreatedResponse` schemas | File exists |
| CC-08 | Migration `0010_add_api_key_auth.py` exists | File exists |
| CC-09 | Migration creates table + check constraints + indexes | Inspect upgrade() |
| CC-10 | `key_id` regex check is `^[a-z0-9]{16,32}$` | grep |
| CC-11 | `status` check is `active/revoked/expired` | grep |
| CC-12 | `API_KEY_PEPPER` settings is required and raises if missing | grep config.py |
| CC-13 | `API_KEY_RATE_LIMIT_PER_MINUTE` settings configurable | grep |
| CC-14 | `APIKeyCreatedResponse` includes `plaintext_token` and warning | Inspect schema |
| CC-15 | `APIKeyPublic` does NOT include `secret_hash` or plaintext token | Inspect schema |
| CC-16 | Routes registered in `app/api/main.py` router | grep router.include_router |
| CC-17 | OpenAPI exposes new endpoints | curl /openapi.json |
| CC-18 | Existing tests pass | pytest 0 failures |
| CC-19 | New file `tests/test_api_key_auth.py` with 30 tests | File exists |
| CC-20 | All files parse with `ast.parse` | Tool internal |
| CC-21 | Tool execution time < 4s | Time measurement |
| CC-22 | Verification p99 < 5 ms | Benchmark T-29 |
| CC-23 | Rate-limit p99 < 1 ms (Redis) | Benchmark T-30 |
| CC-24 | Plaintext secret not present in any audit row, log, or response except creation | grep + log inspection |
| CC-25 | Constant-time fake check on unknown key_id | T-12 |
| CC-26 | Idempotent re-run | T-26 |
| CC-27 | Owner check on rotate/revoke | T-22, T-23 |
| CC-28 | Scope check requires explicit grant (no wildcard) | T-15 |
| CC-29 | Audit fields updated on every call | T-19 |
| CC-30 | Revocation is immediate | T-08 |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of these are true:

- [ ] All 30 Completeness Criteria verified
- [ ] All 11 Quality Standards enforced
- [ ] All 7 Invariants enforced (see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (see §10)
- [ ] Tool is idempotent: run twice, identical state
- [ ] Tool is reversible: rollback procedure documented and tested
- [ ] Migration safety: tested on empty DB
- [ ] Performance budget met: verify p99 < 5 ms, rate-limit < 1 ms
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated (KNOWLEDGE.md, manifest.yaml, SKILL.md)
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-AK-01 | A plaintext secret is NEVER stored in the database | Only `secret_hash` column exists; CRUD never accepts plaintext into the model | T-01, T-13 |
| INV-AK-02 | A plaintext secret is NEVER returned by any endpoint after creation | Only `APIKeyCreatedResponse` carries it; `APIKeyPublic` does not | T-13, T-14 |
| INV-AK-03 | A revoked key NEVER authenticates a request | Dep checks `status == 'active'` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-08 |
| INV-AK-04 | An expired key NEVER authenticates a request | Dep checks `expires_at >= now` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-09 |
| INV-AK-05 | Secret verification is ALWAYS constant-time | `hmac.compare_digest` or argon2; never `==` | T-12 |
| INV-AK-06 | A user CANNOT manage keys belonging to another user | CRUD verifies `api_key.user_id == current_user.id` | T-22, T-23 |
| INV-AK-07 | An over-limit request ALWAYS returns 429 with Retry-After header | `check_rate_limit` → False → raise 429 — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-25 |

---

## 9. User Stories

### 9.1 Key issuance & hashing (US-01 .. US-05)

**US-01: Issue a live key with `sk_live_` prefix for a CI/CD integration**
- **As a** platform engineer wiring a CI pipeline to the orders API
- **I want** to create a key with `orders:read` scope and `sk_live_` prefix
- **So that** the CI job can poll order status without any human OAuth session
- **Given:** authenticated user with active account and no existing key named "ci-orders-read"
- **When:** `POST /api-keys/ {"name": "ci-orders-read", "scopes": ["orders:read"], "environment": "live"}`
- **Then:**
  - Response status is 201 Created
  - `plaintext_token` starts with `sk_live_` and contains exactly three `_`-separated segments
  - Response body includes `warning: "Store this token now. It will NOT be shown again."` (INV-AK-01)
  - Database row `api_keys` is created with `status='active'` and `secret_hash` != `plaintext_token`
  - `secret_hash` is an Argon2id digest — verified by calling `api_key_hasher.verify(plaintext, hash)` returning `True`

**US-02: Issue a test key with `sk_test_` prefix for a staging environment**
- **As a** QA engineer setting up automated acceptance tests against the staging cluster
- **I want** to create a key prefixed `sk_test_` so it is visually distinct from live credentials
- **So that** an accidental copy-paste of a test key into production fails fast and unambiguously
- **Given:** authenticated user targeting a staging project
- **When:** `POST /api-keys/ {"name": "qa-smoke", "scopes": ["*:*"], "environment": "test"}`
- **Then:**
  - `plaintext_token` starts with `sk_test_` (CC-14)
  - Using that `sk_test_` token against a live-prefixed endpoint returns 401 with `detail: "test key rejected in live environment"`
  - Key is stored with `secret_hash` derived via Argon2id; raw secret is absent from every DB column (INV-AK-01)
  - `GET /api-keys/{key_id}` returns the key metadata but omits `plaintext_token` entirely (INV-AK-02)

**US-03: Plaintext secret is shown exactly once and never retrievable again**
- **As a** security officer auditing credential lifecycle
- **I want** to confirm the plaintext secret is only ever present in the single 201 creation response
- **So that** database breach, log scraping, or repeated API calls cannot reconstruct the secret
- **Given:** a key was created one second ago and its 201 response was discarded
- **When:** `GET /api-keys/{key_id}` is called by the key owner
- **Then:**
  - Response body matches `APIKeyPublic` schema — no `plaintext_token`, no `secret_hash` field (INV-AK-02, CC-15)
  - `GET /api-keys/` list response also omits `plaintext_token` for all entries
  - No log line in the application log contains the raw secret substring (CC-24)
  - The only way to obtain a working credential is via a new rotation (`POST /api-keys/{key_id}/rotate`)

**US-04: Default scopes are applied when none are specified**
- **As a** developer issuing a quick integration key without deep knowledge of the scope system
- **I want** the system to apply the configured `default_scopes` automatically
- **So that** a newly issued key is functional but follows the principle of least privilege
- **Given:** tool was installed with `default_scopes=["orders:read"]` and user sends no `scopes` field
- **When:** `POST /api-keys/ {"name": "quick-key"}`
- **Then:**
  - Response `scopes` field equals `["orders:read"]` — exactly the configured default (CC-13)
  - Key successfully authenticates a request to a route protected by `require_scope("orders:read")`
  - Key returns 403 on a route protected by `require_scope("orders:write")` — default is not over-privileged
  - DB column `scopes` stores `["orders:read"]` as a JSON array

**US-05: Argon2id hash is GPU-resistant and verifiable**
- **As a** security engineer reviewing the credential storage strategy
- **I want** all secrets hashed with Argon2id (not bcrypt or SHA-256 alone)
- **So that** a stolen `api_keys` table cannot be cracked offline using GPU farms
- **Given:** tool installed with `hash_algorithm="argon2id"`
- **When:** a key is created and the `secret_hash` column is inspected directly in the database
- **Then:**
  - `secret_hash` value starts with `$argon2id$` identifying the algorithm unambiguously (CC-02)
  - `api_key_hasher.verify(plaintext, secret_hash)` returns `True` confirming round-trip integrity
  - `api_key_hasher.verify("wrong_secret", secret_hash)` returns `False` in constant time (INV-AK-05)
  - `api_key_hasher.hash(plaintext) != api_key_hasher.hash(plaintext)` — two hashes of the same input differ (salt randomisation)

---

### 9.2 Verification & scopes (US-06 .. US-10)

**US-06: Valid key with matching scope authenticates successfully**
- **As a** partner service calling the orders read endpoint every 30 seconds
- **I want** my `orders:read`-scoped key to authenticate every call without session management
- **So that** the integration runs unattended and does not require token refresh flows
- **Given:** active key with `scopes=["orders:read"]` and correct plaintext stored in the partner's env
- **When:** `GET /orders/` with header `Authorization: Bearer sk_live_<key_id>_<secret>`
- **Then:**
  - Response is 200 OK and the orders list is returned (CC-03)
  - `last_used_at` in the database is updated to the current UTC timestamp (INV-AK-07 via T-19)
  - `last_used_ip` is recorded as the caller's IP address
  - No plaintext secret appears in any log output or audit record (CC-24)

**US-07: Key with insufficient scope is rejected with 403, not 401**
- **As a** read-only analytics service that should never modify orders
- **I want** a write attempt to be rejected with a clear scope error, not a generic auth failure
- **So that** misconfigured clients produce actionable error messages rather than silent auth failures
- **Given:** active key with `scopes=["orders:read"]` and valid credentials
- **When:** `POST /orders/` to a route protected by `require_scope("orders:write")`
- **Then:**
  - Response status is 403 Forbidden (not 401, which would imply bad credentials) (CC-28)
  - Response body is `{"detail": "API key missing required scope: orders:write"}`
  - The request still updates `last_used_at` and `last_used_ip`, providing an audit trail of the denied attempt
  - No 429 is raised — the rate-limit check runs before scope check, so this counts against the key's quota

**US-08: Wildcard scope `*:*` grants access to every route**
- **As a** superadmin service running nightly data migrations requiring full API access
- **I want** a single `*:*`-scoped key that passes every `require_scope()` check
- **So that** I do not need to enumerate dozens of granular scopes for an internal admin tool
- **Given:** active key with `scopes=["*:*"]`
- **When:** requests are made to routes requiring `orders:read`, `billing:write`, and `admin:delete`
- **Then:**
  - All three requests return 200 OK — wildcard scope satisfies any `require_scope()` guard
  - `require_scope("*:*")` guard itself also passes (self-referential check is consistent)
  - Issuing a `*:*` key is only allowed for users whose own account has admin privileges (403 otherwise)
  - Audit log records `scopes=["*:*"]` on each call so reviewers can identify superadmin activity (CC-29)

**US-09: Wrong secret returns 401 for a key_id that exists**
- **As a** security monitoring system watching for credential-stuffing attempts
- **I want** wrong-secret requests to return 401 promptly and uniformly
- **So that** I can distinguish authentication failures from authorization failures in my SIEM
- **Given:** a key with known `key_id` but the caller provides a corrupted secret (one character changed)
- **When:** request with `Authorization: Bearer sk_live_<key_id>_<corrupted_secret>`
- **Then:**
  - Response is 401 Unauthorized with `{"detail": "Invalid API key"}` (T-10)
  - Response time is comparable to a successful auth request — no timing oracle for secret length (INV-AK-05, T-28)
  - `last_used_at` is NOT updated — failed verifications do not pollute the audit trail
  - Rate-limit counter for the key is NOT incremented on auth failure to avoid lockout-by-enumeration

**US-10: Malformed token format (missing prefix or segments) returns 401**
- **As a** developer accidentally sending a JWT where an API key is expected
- **I want** a clear 401 rather than a 500 internal error
- **So that** the mistake is immediately diagnosable without digging into server logs
- **Given:** request with `Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig` (JWT, not API key)
- **When:** the dependency `get_current_api_key` parses the token
- **Then:**
  - Response is 401 Unauthorized with `{"detail": "Invalid API key format"}` (T-11)
  - No database lookup is attempted — format check short-circuits before any I/O (CC-10)
  - Same 401 is returned for: no `Bearer ` prefix, empty string, token with only two segments, token with non-alphanumeric `key_id`
  - Error response time is < 0.1 ms (pure string validation, no hash or DB call)

---

### 9.3 Revocation & rotation (US-11 .. US-15)

**US-11: Revoking a key makes it immediately unusable — zero grace period**
- **As a** security engineer responding to a leaked credential incident
- **I want** a single admin call to instantly invalidate the compromised key across all API nodes
- **So that** the window of exploit is closed as fast as physically possible after discovery
- **Given:** active key `sk_live_abc123_<secret>` is in use by an integration running every 5 seconds
- **When:** `POST /api-keys/{key_id}/revoke` is called by the key's owner
- **Then:**
  - Response is 200 OK and DB `status` changes to `'revoked'` and `revoked_at` is set (CC-30, INV-AK-03)
  - The very next request from the integration with the same token returns 401 (no delay, no grace period)
  - `POST /api-keys/{key_id}/revoke` called a second time returns 409 Conflict with `{"detail": "Key already revoked"}`
  - The revoked key cannot be re-activated — only a new key can be issued (INV-AK-03)

**US-12: Rotating a key replaces the secret without downtime — old and new coexist during swap**
- **As a** DevOps engineer rotating credentials on a rolling schedule without deployment windows
- **I want** a rotation endpoint that returns a new secret while keeping the old secret valid briefly
- **So that** I can update the secret in my secret manager before the old one expires, with zero dropped requests
- **Given:** active key `k1` used in a running service with `rotation_grace_seconds=30`
- **When:** `POST /api-keys/{key_id}/rotate {"grace_seconds": 30}`
- **Then:**
  - Response returns new `plaintext_token` (new `sk_live_` value) with a one-time-show warning (INV-AK-01)
  - During the 30-second grace window, BOTH old and new secrets authenticate successfully
  - After 30 seconds, only the new secret works; the old secret returns 401 (T-24)
  - `secret_hash` in the DB reflects only the new hash after the grace window closes

**US-13: Rotating a key invalidates the old secret after the grace window**
- **As a** compliance auditor verifying that rotated credentials are fully expired
- **I want** the old secret to become invalid automatically without requiring a manual revoke call
- **So that** rotation is a single operation with a guaranteed end state — no dangling credentials
- **Given:** key was rotated 90 seconds ago with `grace_seconds=30`
- **When:** a request is made using the pre-rotation `plaintext_token`
- **Then:**
  - Response is 401 Unauthorized — old secret is no longer accepted (INV-AK-03, T-24)
  - No manual revocation call was required — grace expiry is automatic
  - `last_used_at` is NOT updated — expired-grace auth attempts are rejected at hash-comparison stage
  - DB row shows `status='active'` (key is alive, just old secret is dead) and only new `secret_hash`

**US-14: Key owner cannot access another owner's keys — isolation is enforced**
- **As a** tenant in a multi-user deployment
- **I want** to be certain that no other user can read, rotate, or revoke my keys
- **So that** API key management has the same ownership isolation as any other user-owned resource
- **Given:** user A owns key `key_a`; user B is authenticated with their own valid session token
- **When:** user B calls `POST /api-keys/{key_a_id}/revoke`
- **Then:**
  - Response is 404 Not Found — not 403, to avoid leaking whether `key_a` exists (INV-AK-06, T-22, T-23)
  - Same 404 is returned for `GET /api-keys/{key_a_id}`, `POST /api-keys/{key_a_id}/rotate`
  - `GET /api-keys/` for user B never returns user A's key in the listing (CC-27)
  - CRUD layer enforces `api_key.user_id == current_user.id` before any mutation

**US-15: Rotating with zero grace seconds invalidates old secret immediately**
- **As a** security engineer handling an active incident where immediate rotation is required
- **I want** to rotate a key and have the old secret rejected on the very next request
- **So that** I can use rotation as an emergency revoke-and-reissue in a single atomic operation
- **Given:** active key with a running integration; incident declared; `grace_seconds=0`
- **When:** `POST /api-keys/{key_id}/rotate {"grace_seconds": 0}`
- **Then:**
  - New `plaintext_token` is returned in the 200 response
  - Any concurrent request using the old secret, arriving after the rotate completes, returns 401 (INV-AK-03)
  - `secret_hash` in the DB is updated atomically — no window where neither secret is valid
  - Response time for the rotate operation is < 500 ms including Argon2id re-hash (CC-21)

---

### 9.4 Rate limiting & audit (US-16 .. US-20)

**US-16: Per-key rate limit enforced independently of other keys**
- **As a** platform operator protecting the API from a single runaway integration
- **I want** each API key to have its own rate-limit bucket, not a shared global counter
- **So that** one misbehaving key does not degrade service for all other integrations
- **Given:** key A has `rate_limit_per_minute=60`; key B has `rate_limit_per_minute=600`; both are active
- **When:** key A sends 61 requests within one minute while key B sends only 10
- **Then:**
  - Key A's 61st request returns 429 with `Retry-After: 60` header (INV-AK-07, T-25, CC-23)
  - Key B's 10 requests all return 200 — it is unaffected by key A's exhaustion
  - Redis INCR+EXPIRE is used for key A's bucket; p99 rate-limit check < 1 ms (T-30)
  - After the 60-second window resets, key A can send requests again without restarting the service

**US-17: 429 response includes `Retry-After` header with correct seconds-to-reset**
- **As a** well-behaved integration that honors HTTP rate-limit headers
- **I want** the 429 response to include an accurate `Retry-After` value in seconds
- **So that** my exponential backoff logic can sleep exactly long enough without polling
- **Given:** key with 600/min limit; 600 requests sent in second 0 of the minute window
- **When:** the 601st request arrives at second 5 of the same window
- **Then:**
  - Response is 429 with `Retry-After: 55` (60 - 5 = 55 seconds remaining) (INV-AK-07)
  - `Retry-After` value is a positive integer in seconds — never zero, never negative
  - If Redis is unavailable, in-process counter is used and `Retry-After` defaults to 60
  - Rate-limit headers are consistent: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` are all present

**US-18: Every authenticated call updates `last_used_at`, `last_used_ip`, and `last_used_ua`**
- **As a** security team member reviewing key activity in an incident postmortem
- **I want** each successful API call to write the caller's timestamp, IP, and User-Agent to the key record
- **So that** I can reconstruct exactly when, where, and which client used a key — even after the key is revoked
- **Given:** active key with null `last_used_at`; caller IP `203.0.113.42`; UA `orders-sync/2.1.0`
- **When:** valid authenticated request is made
- **Then:**
  - `last_used_at` equals the current UTC time within 1 second of the request (CC-29, T-19)
  - `last_used_ip` equals `'203.0.113.42'` stored as PostgreSQL `INET` type (T-20)
  - `last_used_ua` equals `'orders-sync/2.1.0'` truncated at 500 characters if needed (T-21)
  - These three fields are updated even if the subsequent business logic handler raises an error

**US-19: Per-key rate-limit value is configurable per key at creation time**
- **As a** platform operator serving both low-volume partners and high-throughput internal services
- **I want** to set different rate limits per key at issuance time rather than using a global value
- **So that** a high-volume internal service is not throttled at the same level as an external trial partner
- **Given:** default `rate_limit_per_minute=600`; internal service key is created with `rate_limit_per_minute=6000`
- **When:** internal service key sends 5000 requests in one minute
- **Then:**
  - All 5000 requests succeed — the per-key override of 6000 is respected (CC-04)
  - A trial key with default 600 limit hitting its 601st request gets 429 in the same minute
  - `rate_limit_per_minute` is stored on the `api_keys` row and read by `check_rate_limit` on every call
  - Changing the per-key limit via an admin endpoint takes effect on the next incoming request — no restart needed

**US-20: Audit trail is immutable — revoked keys retain their full call history**
- **As a** compliance officer running a forensic investigation after a breach
- **I want** call metadata (`last_used_at`, `last_used_ip`, `last_used_ua`) to remain in the DB after revocation
- **So that** I can audit exactly what was done with a key before it was revoked
- **Given:** key that was used 500 times over three months and was revoked during an incident
- **When:** a forensic query is run: `SELECT last_used_at, last_used_ip FROM api_keys WHERE key_id = :k`
- **Then:**
  - Row exists with `status='revoked'`, `revoked_at` set, and full `last_used_*` fields intact (INV-AK-03)
  - `DELETE /api-keys/{key_id}` is not an available endpoint — hard-delete is not permitted post-revocation
  - The key row is only removed on `ON DELETE CASCADE` when the owning user account is deleted
  - Audit fields are never overwritten once the key transitions to `revoked` status

---

### 9.5 Edge cases & security (US-21 .. US-25)

**US-21: Timing attack on secret comparison is mitigated — unknown key_id path is constant-time**
- **As a** penetration tester probing the authentication endpoint for timing oracles
- **I want** to confirm that requests with unknown `key_id` take the same time as wrong-secret requests
- **So that** an attacker cannot enumerate valid `key_id` values by measuring response latency
- **Given:** one valid key_id with wrong secret; one completely unknown key_id
- **When:** 1000 requests of each type are sent and median latency is measured
- **Then:**
  - Median latency difference between the two cases is < 1 ms (INV-AK-05, T-12, T-28)
  - The unknown key_id path calls `hmac.compare_digest` against a pre-computed fake hash — never returns early
  - Both cases return 401 with identical `{"detail": "Invalid API key"}` body — no information leakage
  - The fake-hash path is covered by a dedicated invariant test in `tests/test_invariants.py` (CC-25)

**US-22: Key enumeration is prevented — response does not distinguish revoked from non-existent**
- **As a** security researcher probing key ID space via brute-force
- **I want** to verify that the API cannot be used to determine whether a given key_id was ever issued
- **So that** revoked keys cannot be identified as "formerly valid" and targeted for further analysis
- **Given:** key_id `abc123` was revoked last week; key_id `xyz789` was never issued
- **When:** requests are made using both key_ids (with any secret)
- **Then:**
  - Both return 401 with identical body and identical response time (within 1 ms) (INV-AK-05)
  - HTTP status 401 (not 404) is used for revoked keys — 404 would confirm existence (INV-AK-03, T-08)
  - No `WWW-Authenticate` header includes the key_id or status in its value
  - Rate-limit counter is incremented on failed attempts to make enumeration costly (INV-AK-07)

**US-23: Compromised `sk_live_` key used against a test-only service returns an environment mismatch error**
- **As a** operator running separate live and test clusters with strict environment controls
- **I want** a `sk_test_` key to be rejected by the live cluster even if the secret is cryptographically valid
- **So that** test credentials accidentally committed to source control cannot be exploited in production
- **Given:** `sk_test_abc123_<valid_secret>` was issued in the test environment; live cluster has `ENVIRONMENT=live`
- **When:** the `sk_test_` key is used against the live cluster API
- **Then:**
  - Response is 401 with `{"detail": "test key rejected in live environment"}`
  - The error is logged at WARN level including the `key_id` prefix for incident tracking
  - The rejection happens before any database lookup — prefix check short-circuits I/O
  - Symmetric rule: a `sk_live_` key used against a test cluster returns 401 with matching message

**US-24: Pepper rotation — changing `API_KEY_PEPPER` causes graceful degradation, not silent auth failures**
- **As a** security engineer rotating the application-level pepper as part of annual key hygiene
- **I want** the system to detect pepper mismatch and respond with a clear operational error
- **So that** I can identify which keys need re-hashing rather than silently rejecting all existing keys
- **Given:** all existing keys were hashed with pepper `P1`; `API_KEY_PEPPER` is changed to `P2` in the environment
- **When:** an existing key attempts to authenticate
- **Then:**
  - If `hash_algorithm=argon2id` (no pepper used): authentication succeeds unchanged — Argon2id is self-contained
  - If `hash_algorithm=sha256_pepper`: authentication fails and returns 401 with `{"detail": "Invalid API key"}` — no information about pepper mismatch is exposed to callers
  - `API_KEY_PEPPER` missing entirely causes `RuntimeError` at startup, not at request time (CC-12, T-27)
  - The operator receives a startup-time crash with message `"API_KEY_PEPPER must be set"` before the server accepts any traffic

**US-25: Verification p99 latency stays below 5 ms with 10,000 keys in the database**
- **As a** load-testing engineer validating the service can sustain peak traffic
- **I want** API key verification to add no more than 5 ms to the p99 response time even at scale
- **So that** the auth layer does not become a bottleneck as the key count grows over time
- **Given:** 10,000 active keys in the `api_keys` table; `key_id` column has a B-tree index; Redis available
- **When:** 10,000 sequential auth requests are made against random keys in the table
- **Then:**
  - p99 verification latency (index lookup + Argon2id verify) is < 5 ms (CC-22, T-29)
  - p99 rate-limit check (Redis INCR+EXPIRE) is < 1 ms (CC-23, T-30)
  - No full table scan occurs — `EXPLAIN ANALYZE` on the `key_id` lookup shows index scan, not seq scan
  - Memory overhead per worker process remains < 1 MB — no in-memory key cache is used by default

## 10. Test Plan

### 10.1 Issuance & storage

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Create returns plaintext only once | New user | POST /api-keys/ | 201 with plaintext_token; 2nd GET no token |
| T-02 | secret_hash differs from plaintext | Create key | inspect DB | secret_hash != plaintext |
| T-03 | key_id regex matches stored value | Create key | inspect DB | key_id matches `^[a-z0-9]{16,32}$` |
| T-04 | Plaintext token format valid | Create key | inspect response | starts with `api_`, 3 underscored parts |
| T-05 | Default scopes applied | Create key with no scopes | inspect | scopes == default_scopes |
| T-06 | Custom scopes accepted | Create key with `["read","custom"]` | inspect | exactly those scopes |
| T-07 | Long name truncated by Pydantic | name=300 chars | POST | 422 |

### 10.2 Verification & lifecycle

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-08 | Revoked key returns 401 | active key, revoke | request | 401 |
| T-09 | Expired key returns 401 | expires_at = past | request | 401, status = expired |
| T-10 | Wrong secret returns 401 | bad secret | request | 401 |
| T-11 | Unknown key_id returns 401 | bogus token | request | 401 |
| T-12 | Constant-time fake hash | benchmark known vs unknown | measure | < 1ms diff |
| T-13 | Plaintext never in DB | create + inspect | grep secret_hash | plaintext absent |
| T-14 | Plaintext never in GET response | GET /api-keys/ | inspect | no plaintext field |

### 10.3 Scopes

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | read scope blocks write route | scope=read, write route | request | 403 |
| T-16 | admin scope grants all | scope=admin | request to any | 200 |
| T-17 | custom scope check works | scope=`read:items` | route requires same | 200 |
| T-18 | wildcard scope rejected | scope=`*` | route requires `write` | 403 (no wildcard support) |

### 10.4 Audit & rate limit

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | last_used_at updated | 1 call | inspect | now() |
| T-20 | last_used_ip captured | request from 1.2.3.4 | inspect | "1.2.3.4" |
| T-21 | last_used_ua captured | UA="curl/8.0" | inspect | "curl/8.0" |
| T-25 | Over-limit returns 429 | 600/min limit | 601st request | 429 + Retry-After |

### 10.5 Owner, idempotency, performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | User B cannot rotate user A's key | user B token, key of A | POST /api-keys/{a_key}/rotate | 404 |
| T-23 | User B cannot revoke user A's key | similar | POST /api-keys/{a_key}/revoke | 404 |
| T-24 | Rotate invalidates old secret | rotate then use old | request with old | 401 |
| T-26 | Tool re-run is no-op | already installed | run | no file changes |
| T-27 | Pepper missing → app refuses to start | unset env | start | RuntimeError |
| T-28 | Verify under timing attack ~constant | 1000 valid + 1000 invalid | measure | timing variance < 1ms |
| T-29 | Verify p99 < 5 ms | 10k keys, benchmark | measure | p99 < 5 ms |
| T-30 | Rate-limit p99 < 1 ms (Redis) | benchmark | measure | p99 < 1 ms |

---

## 11. Interaction Matrix

How `add_api_key_auth` interacts with other tools:

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Tenancy first** | ✅ Compatible | Keys belong to a user; user belongs to a tenant; auto-scoped via FK chain. |
| `add_audit_log` | **Audit first** | ✅ Compatible | API key calls produce audit log entries with `actor_type='api_key', actor_id=key.id`. |
| `add_rbac` | **RBAC first** | ⚠️ Caveat | Decide whether scopes are independent of roles or derived. Default: independent. Document for users. |
| `add_oauth2_provider` | No | ✅ Compatible | Two parallel auth methods; the dep `get_current_user` and `get_current_api_key` are separate. |
| `add_mfa` | No | ✅ Compatible | MFA gates user login; API keys are independent. |
| `add_feature_flags` | No | ✅ Compatible | Flags can target by `actor_type=api_key`. |
| `add_rate_limit` (global) | No | ⚠️ Caveat | API key rate limit is per-key; the global rate limiter is per-IP. Both apply. |
| `add_cache_layer` | No | ⚠️ Caveat | If cache is added later, cache MUST be invalidated on rotate/revoke. |
| `add_circuit_breaker` | No | ✅ Compatible | Independent. |
| `add_security_headers` | No | ✅ Compatible | Auth header processing is unaffected. |
| `add_webhook_sender` | No | ⚠️ Caveat | Outbound webhooks may use API keys; rotation requires updating subscriber config. |
| TOOL-034 performance_baseline | downstream | `POST /api-keys/`, `POST /api-keys/{key_id}/rotate`, and `POST /api-keys/{key_id}/revoke` are captured in the baseline (target p99 < 50 ms per route); a future change to the HMAC comparison in `app/core/api_key_validator.py` that adds a DB round-trip will be caught before merge |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_api_key_auth` is installed but no `add_audit_log` is present and recommends TOOL-007 `add_audit_log` so that key creation, rotation, and revocation events are recorded for compliance — flagged as HIGH if audit log is absent |
| TOOL-029 security_scan | downstream | `app/core/api_key_validator.py` is scanned for timing-attack patterns (must use `hmac.compare_digest` not `==` for token comparison) and for hardcoded key prefixes; any CRITICAL finding in the key handling path blocks merge |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

If `add_api_key_auth` produces broken state, the rollback procedure is:

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/api_key.py app/core/api_key_*.py \
  app/crud/api_key.py app/api/routes/api_keys.py app/schemas/api_key.py \
  app/api/main.py app/core/config.py
rm alembic/versions/*_add_api_key_auth.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
This drops the `api_keys` table.

### Data preservation rollback
If issued keys must be preserved for re-enable:
```sql
CREATE TABLE _api_keys_archive AS SELECT * FROM api_keys;
-- Then run alembic downgrade -1
```

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_api_key_auth.py`
- Re-run tool

### Emergency: a key is leaked
1. Revoke immediately: `POST /api-keys/{key_id}/revoke`
2. Audit `last_used_*` columns to assess scope of misuse
3. Notify the affected user
4. If multiple keys affected, revoke all keys for the user, force re-issue

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no User model | Tool errors: "API keys require a User model. Add auth first." |
| EC-2 | Project has no Alembic | Tool errors: "Alembic not initialized." |
| EC-3 | API_KEY_PEPPER env var missing | App startup fails with clear error |
| EC-4 | A key with `expires_at` set to a past timestamp via patch | Next request 401, status auto-updated to `expired` |
| EC-5 | A key with > 100 scopes | Pydantic validator caps scopes list at 100 |
| EC-6 | A scope with whitespace or special chars | Pydantic regex `^[a-z][a-z0-9:_-]{0,63}$` rejects |
| EC-7 | Two requests with the same valid key in same millisecond | Both succeed; rate limit counts both; `last_used_at` reflects latest |
| EC-8 | A user is deleted while their keys exist | FK CASCADE drops the keys |
| EC-9 | Token contains only `api_<id>` (no secret) | Parsed as malformed → 401; the operation returns a structured error response and no side effects persist |
| EC-10 | Secret contains special chars | URL-safe base64; verified by `verify_secret` byte-equality |
| EC-11 | Redis goes down during rate limit check | Falls back to in-process counter; service stays up |
| EC-12 | Argon2 algorithm chosen but argon2-cffi not installed | Tool warns at install: "argon2-cffi missing; pip install argon2-cffi or use sha256_pepper" |
| EC-13 | Migration fails on restricted DB user | Migration uses standard DDL; should work for any user with CREATE TABLE; tool documents needed grants |
| EC-14 | Two superadmins create keys with the same `name` | Allowed (name is not unique; only key_id is) |
| EC-15 | Verification benchmarks show > 5 ms p99 | Acceptance criteria fails; switch to sha256_pepper or add an in-memory cache |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 30 CC verified by automated check
2. ✅ All 25 user stories have passing acceptance tests
3. ✅ All 30 test cases pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified by integration tests
7. ✅ Rollback procedure tested end-to-end
8. ✅ Performance SLOs measured and met
9. ✅ Re-audit by Opus (fresh context, brutal mode): ≥ 9.5/10
10. ✅ One human dev issues a key, calls 5 endpoints, rotates, revokes, without confusion

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Alembic initialized
- [ ] Detect existing `api_keys` table → idempotent skip if found
- [ ] Validate `API_KEY_PEPPER` placeholder added to `.env.example`
- [ ] Verify idempotency: run the tool twice and confirm second invocation returns `status="already_installed"` without creating duplicate `api_keys` table or files
- [ ] Confirm `API_KEY_PEPPER` placeholder exists in `.env.example` via `grep -q "API_KEY_PEPPER" .env.example` (exits 0)

### 15.2 Settings
- [ ] Add `API_KEY_PEPPER: str` to settings (Field with no default → required)
- [ ] Add `API_KEY_RATE_LIMIT_PER_MINUTE: int = 600` to settings
- [ ] Add `.env.example` line: `API_KEY_PEPPER=change-me-to-a-256-bit-random-value`
- [ ] Confirm the app raises `ValidationError` on startup when `API_KEY_PEPPER` is unset by running `pytest tests/test_api_key_auth.py::test_app_refuses_start_without_pepper`
- [ ] Run `ruff check app/core/config.py` and `mypy app/core/config.py --strict` with zero new findings after the two settings additions
- [ ] Add `## [Unreleased]` CHANGELOG entry describing `API_KEY_PEPPER` as a required secret and `API_KEY_RATE_LIMIT_PER_MINUTE` as a new throttle setting

### 15.3 Hasher module
- [ ] Create `app/core/api_key_hasher.py`
- [ ] Implement `generate_secret`, `generate_key_id`, `hash_secret`, `verify_secret`
- [ ] argon2 path uses `argon2-cffi`
- [ ] sha256 path uses `hmac.compare_digest`
- [ ] Verify file parses
- [ ] Confirm `verify_secret` timing is constant for valid vs invalid keys: run a `timeit` benchmark in `tests/test_api_key_hasher.py::test_verify_secret_constant_time` and assert the ratio `t_invalid / t_valid` is between 0.8 and 1.2
- [ ] Confirm `verify_secret` with a completely unknown `key_id` still executes the dummy `hash_secret` call (prevents timing oracle): spy on `hash_secret` in `tests/test_api_key_auth.py::test_unknown_key_id_calls_dummy_verify`

### 15.4 Rate-limit module
- [ ] Create `app/core/api_key_rate_limit.py`
- [ ] Implement `check_rate_limit` with Redis pipeline (INCR + EXPIRE)
- [ ] Implement in-process fallback `_check_in_process`
- [ ] Verify file parses
- [ ] Confirm `check_rate_limit` raises HTTP 429 after `API_KEY_RATE_LIMIT_PER_MINUTE` calls within 60 s in `tests/test_api_key_rate_limit.py::test_rate_limit_exceeded_returns_429`
- [ ] Verify in-process fallback engages when Redis is unreachable: mock `redis.pipeline` to raise `ConnectionError` and assert `_check_in_process` is called instead in `tests/test_api_key_rate_limit.py::test_fallback_to_in_process_on_redis_error`
- [ ] Run `ruff check app/core/api_key_rate_limit.py` with zero findings

### 15.5 Dependency module
- [ ] Create `app/core/api_key_deps.py`
- [ ] Implement `_parse_header` for `Bearer api_<id>_<secret>` format
- [ ] Implement `get_current_api_key` with: parse → lookup → verify → status check → expiry check → rate limit → audit update
- [ ] Implement `require_scope`
- [ ] Always execute fake `verify_secret` on unknown key_id (constant time)
- [ ] Verify file parses
- [ ] Run `tests/test_api_key_auth.py::test_expired_key_returns_401` and confirm a key past `expires_at` returns HTTP 401, not 403
- [ ] Confirm `require_scope("write")` returns HTTP 403 when the key only has `["read"]` scope, via `tests/test_api_key_auth.py::test_insufficient_scope_returns_403`

### 15.6 Model
- [ ] Create `app/models/api_key.py`
- [ ] Add CheckConstraints + composite index `(user_id, status)`
- [ ] Verify file parses
- [ ] Confirm composite index `(user_id, status)` exists in `pg_indexes` after `alembic upgrade head` by running `SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix_api_keys_user%'`
- [ ] Run `ruff check app/models/api_key.py` and `mypy app/models/api_key.py --strict` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG entry documenting `api_keys` table and the one-way `hashed_secret` storage (plaintext never persisted)

### 15.7 CRUD
- [ ] Create `app/crud/api_key.py` with `create/get_by_key_id/list_for_user/revoke`
- [ ] Verify file parses
- [ ] Confirm `crud_api_key.create` stores only the hashed secret, never plaintext: assert `APIKey.hashed_secret != plaintext_token` in `tests/test_api_key_auth.py::test_create_stores_hash_not_plaintext`
- [ ] Run `ruff check app/crud/api_key.py` and `mypy app/crud/api_key.py --strict` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG note that `revoke` sets `status="revoked"` and writes `revoked_at` timestamp
- [ ] Add structured log event `api_key.used` with fields `key_id`, `user_id`, `scopes`, `latency_ms` in `get_current_api_key` after a successful verify

### 15.8 Schemas
- [ ] Create `app/schemas/api_key.py`
- [ ] `APIKeyCreate`: name, description, scopes, expires_at
- [ ] `APIKeyPublic`: id, key_id, name, scopes, status, created_at, last_used_at — NO secret
- [ ] `APIKeyCreatedResponse`: api_key (Public) + plaintext_token + warning
- [ ] Validators on scopes (max 100, regex `^[a-z][a-z0-9:_-]{0,63}$`)
- [ ] Verify file parses
- [ ] Confirm `APIKeyPublic` serialization never includes `hashed_secret` or `secret`: assert `"hashed_secret" not in APIKeyPublic.model_fields` and `"secret" not in APIKeyPublic.model_fields` in `tests/test_api_key_schemas.py::test_public_schema_has_no_secret_fields`

### 15.9 Routes
- [ ] Create `app/api/routes/api_keys.py` with create/list/rotate/revoke
- [ ] All require `CurrentUser`
- [ ] Owner check on rotate/revoke (404 if mismatch)
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Confirm a non-owner calling `DELETE /api-keys/{id}` receives HTTP 404 (not 403, to avoid key enumeration) in `tests/test_api_key_auth.py::test_revoke_wrong_owner_returns_404`
- [ ] Confirm `POST /api-keys/{id}/rotate` returns a new `plaintext_token` and invalidates the old one in `tests/test_api_key_auth.py::test_rotate_invalidates_old_secret`

### 15.10 Migration
- [ ] Generate `0NNN_add_api_key_auth.py`
- [ ] `upgrade()` creates table + indexes + check constraints
- [ ] `downgrade()` drops in reverse
- [ ] Verify migration parses
- [ ] Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a clean Postgres container and assert each step exits with code 0
- [ ] Verify `api_keys` table and its check constraints exist after upgrade via `psql -c "\d api_keys"` showing the `status` constraint
- [ ] Run `ruff check alembic/versions/0NNN_add_api_key_auth.py` with zero findings

### 15.11 Test generation
- [ ] Create `tests/test_api_key_auth.py` with all 30 tests
- [ ] Use existing fixtures + new `api_key_factory` fixture
- [ ] Verify file parses
- [ ] Run `pytest tests/test_api_key_auth.py -v` and confirm all 30 cases pass including timing and scope tests
- [ ] Run `ruff check tests/test_api_key_auth.py` and `mypy tests/test_api_key_auth.py` with zero findings
- [ ] Add `## [Unreleased]` CHANGELOG entry documenting 30 new test cases covering create, list, rotate, revoke, expiry, and rate limiting

### 15.12 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created table on failure
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure
- [ ] Inject a failure after writing `app/core/api_key_hasher.py` but before `app/core/api_key_rate_limit.py` and assert `app/core/api_key_hasher.py` is removed from disk in `tests/test_tool_atomicity.py::test_api_key_rollback_on_rate_limit_write`
- [ ] Verify no stale `.tmp` files under `app/core/` after forced failure: `list(Path('app/core').glob('*.tmp'))` must be empty
- [ ] Run `ruff check app/core/api_key_deps.py app/api/routes/api_keys.py` with zero findings post-rollback

### 15.13 Documentation
- [ ] Append API key section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Confirm `manifest.yaml` contains `fastapi_add_api_key_auth` entry: `python -c "import yaml; d=yaml.safe_load(open('manifest.yaml')); assert any(t['name']=='fastapi_add_api_key_auth' for t in d['tools'])"`
- [ ] Verify `core/KNOWLEDGE.md` API key section documents the `Bearer api_<id>_<secret>` header format, pepper rotation procedure, and scope regex
- [ ] Run `ruff check app/schemas/api_key.py app/crud/api_key.py` with zero findings

### 15.14 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure verify p99
- [ ] Measure rate-limit p99

---

## 16. Documentation Output

When the tool succeeds, it returns a structured report:

```json
{
  "status": "success",
  "files_created": [
    "app/models/api_key.py",
    "app/core/api_key_hasher.py",
    "app/core/api_key_deps.py",
    "app/core/api_key_rate_limit.py",
    "app/crud/api_key.py",
    "app/schemas/api_key.py",
    "app/api/routes/api_keys.py",
    "alembic/versions/0010_add_api_key_auth.py",
    "tests/test_api_key_auth.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 3578,
    "files_changed": 12,
    "lines_added": 943,
    "lines_removed": 2,
    "hash_algorithm": "sha256_pepper",
    "rate_limit_per_minute": 600
  },
  "next_steps": [
    "Set API_KEY_PEPPER in your .env (256-bit random; e.g. `openssl rand -hex 32`)",
    "Run: alembic upgrade head",
    "Run: pytest tests/test_api_key_auth.py -v",
    "Issue your first key: POST /api-keys/ {name:'CI', scopes:['read']}",
    "Use it: curl -H 'Authorization: Bearer api_<id>_<secret>' http://localhost:8000/api/v1/items/"
  ],
  "warnings": [
    "API_KEY_PEPPER is REQUIRED. The app will refuse to start without it.",
    "If you chose argon2id, every verification costs ~50 ms. For high-traffic APIs, sha256_pepper is recommended.",
    "Rate limiting falls back to per-worker in-process counter when Redis is unavailable. This is best-effort; install Redis for accurate distributed rate limiting."
  ],
  "notes": [
    "API key auth installed with hash_algorithm=sha256_pepper, rate_limit=600/min.",
    "One new table: api_keys.",
    "Plaintext token returned ONLY at creation/rotation. APIKeyPublic schema strips it.",
    "Owner-only management: users can only rotate/revoke their own keys.",
    "Existing tests still pass: 53/53."
  ]
}
```
