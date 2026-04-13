# TOOL-013: add_mfa

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_mfa` |
| Category | EXTEND > Auth & Access |
| Complexity | High |
| Dependencies | Existing project with auth (User), Alembic, Redis (for rate limit + temp tokens), pyotp, segno |
| Signature | `add_mfa(project_dir: str, recovery_codes_count: int = 10, totp_window: int = 1, max_attempts_per_15min: int = 5, issuer: str = "MyApp") -> dict` |
| Parameters | `project_dir`: project root path<br>`recovery_codes_count`: number of single-use recovery codes generated at enrollment<br>`totp_window`: ± step tolerance for clock drift (1 = ±30s)<br>`max_attempts_per_15min`: rate-limit per user<br>`issuer`: name shown in authenticator app |

---

## 2. Purpose

The `fastapi_add_mfa` tool adds Time-based One-Time Password (TOTP, RFC 6238) multi-factor authentication to the existing email/password login flow, closing the single most dangerous remaining weakness in a password-only auth system: a leaked or phished password is no longer sufficient for an attacker to take over an account. MFA is mandatory for SOC 2, HIPAA, PCI, and most enterprise deals, yet rolling it yourself means getting QR-code generation, drift tolerance, constant-time verification, recovery codes, rate limiting, and enrollment UX all correct — and a single bug in any of those lets an attacker bypass the whole mechanism.

Users enroll by scanning a QR code with Google Authenticator, Authy, 1Password, or any RFC 6238-compliant authenticator app, confirming a 6-digit code to prove they captured the secret before it is activated server-side. After enrollment, login becomes a two-step exchange: the existing password endpoint returns a short-lived `mfa_pending_token` (stored in Redis with a 5-minute TTL) instead of a full JWT, and the client exchanges that token for a final JWT by POSTing a valid TOTP code or a single-use recovery code. Key design decisions: TOTP secrets encrypted at rest with Fernet using a key rotated via TOOL-005 audit_log so a database compromise does not leak usable secrets; recovery codes hashed with Argon2id on issue and marked single-use on redemption; failed-attempt rate limiting per user (5 attempts per 15 minutes) with exponential backoff to kill brute-force without locking out legitimate users; ±1-window drift tolerance (30 seconds each side) to handle clock skew; and an opt-in admin-enforced MFA policy so operators can require MFA for specific roles via TOOL-012 RBAC integration.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Dev waits in CLI |
| Files modified | ≤ 5 global files | Predictability |
| Files created | ≥ 9 (model, crypto, totp_helper, deps, crud, routes, schemas, migration, tests) | Predictability |
| Enrollment latency | < 200 ms | Mostly Fernet encrypt + DB write |
| TOTP verification latency | < 5 ms | Constant-time HMAC compare |
| Recovery code verification | < 50 ms | argon2id verify is intentionally slow |
| Rate-limit lookup | < 1 ms (Redis) | INCR + EXPIRE |
| Migration runtime | < 5s | One new table + 3 columns on users |
| Memory overhead | 0 MB | Stateless |

---

## 4. Code Examples (Before / After)

### 4.1 Model (NEW)
```python
# app/models/mfa.py
from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import uuid


class MFADevice(Base):
    __tablename__ = "mfa_devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="totp")
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recovery_codes: Mapped[list["MFARecoveryCode"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("type IN ('totp')", name="ck_mfa_devices_type"),
    )


class MFARecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mfa_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    device: Mapped[MFADevice] = relationship(back_populates="recovery_codes")
```

### 4.2 Crypto helper (NEW)
```python
# app/core/mfa/crypto.py
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet = Fernet(settings.MFA_FERNET_KEY.encode("ascii"))


def encrypt_secret(secret: str) -> bytes:
    return _fernet.encrypt(secret.encode("utf-8"))


def decrypt_secret(blob: bytes) -> str | None:
    try:
        return _fernet.decrypt(blob).decode("utf-8")
    except InvalidToken:
        return None
```

### 4.3 TOTP helper (NEW)
```python
# app/core/mfa/totp.py
import secrets
from urllib.parse import quote

import pyotp
import segno

from app.core.config import settings


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    issuer = quote(settings.MFA_ISSUER)
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=issuer
    )


def qr_svg(uri: str) -> str:
    """Returns the QR code as inline SVG."""
    qr = segno.make(uri, error="m")
    import io

    buf = io.StringIO()
    qr.save(buf, kind="svg", scale=4, dark="black", light="white")
    return buf.getvalue()


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def generate_recovery_codes(count: int) -> list[str]:
    """10 codes of format `XXXX-XXXX` (8 hex chars + dash)."""
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(count)]
```

### 4.4 Recovery code hashing (NEW)
```python
# app/core/mfa/recovery.py
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_recovery_code(code: str) -> str:
    return _ph.hash(code)


def verify_recovery_code(code: str, stored_hash: str) -> bool:
    try:
        _ph.verify(stored_hash, code)
        return True
    except VerifyMismatchError:
        return False
```

### 4.5 Rate limit (NEW)
```python
# app/core/mfa/rate_limit.py
import time
from uuid import UUID

from app.core.config import settings
from app.core.redis import get_redis

WINDOW = 15 * 60
LIMIT = settings.MFA_MAX_ATTEMPTS_PER_15MIN


async def check_and_consume(user_id: UUID) -> bool:
    redis = await get_redis()
    bucket = int(time.time() // WINDOW)
    key = f"mfa:attempts:{user_id}:{bucket}"
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, WINDOW * 2)
    count, _ = await pipe.execute()
    return count <= LIMIT
```

### 4.6 Routes (NEW)
```python
# app/api/routes/mfa.py
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.mfa.crypto import decrypt_secret, encrypt_secret
from app.core.mfa.rate_limit import check_and_consume
from app.core.mfa.recovery import hash_recovery_code, verify_recovery_code
from app.core.mfa.totp import (
    generate_recovery_codes,
    generate_totp_secret,
    provisioning_uri,
    qr_svg,
    verify_totp,
)
from app.core.security import create_access_token
from app.crud import mfa as crud_mfa
from app.crud import user as crud_user
from app.schemas.mfa import (
    MFAChallengeRequest,
    MFAEnrollResponse,
    MFAVerifyEnrollmentRequest,
)

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

PENDING_TOKEN_TTL_S = 300  # 5 minutes


def _create_pending_token(user_id) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": "mfa_pending",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TOKEN_TTL_S),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _decode_pending_token(token: str):
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid pending token")
    if data.get("purpose") != "mfa_pending":
        raise HTTPException(401, "Wrong token purpose")
    return data["sub"]


@router.post("/enroll", response_model=MFAEnrollResponse)
async def enroll(session: SessionDep, current_user: CurrentUser):
    existing = await crud_mfa.get_device(session, user_id=current_user.id)
    if existing and existing.confirmed_at is not None:
        raise HTTPException(409, "MFA already enabled")

    secret = generate_totp_secret()
    if existing:  # Replace unconfirmed device
        existing.secret_enc = encrypt_secret(secret)
        device = existing
    else:
        device = await crud_mfa.create_device(
            session, user_id=current_user.id, secret_enc=encrypt_secret(secret)
        )

    uri = provisioning_uri(secret, current_user.email)
    return MFAEnrollResponse(
        provisioning_uri=uri,
        qr_svg=qr_svg(uri),
        secret=secret,  # Plaintext shown ONCE for manual entry
    )


@router.post("/verify-enrollment")
async def verify_enrollment(
    body: MFAVerifyEnrollmentRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    device = await crud_mfa.get_device(session, user_id=current_user.id)
    if not device:
        raise HTTPException(404, "No pending enrollment")
    if device.confirmed_at is not None:
        raise HTTPException(409, "Already enrolled")

    secret = decrypt_secret(device.secret_enc)
    if not secret or not verify_totp(secret, body.code, valid_window=settings.MFA_TOTP_WINDOW):
        raise HTTPException(400, "Invalid TOTP code")

    device.confirmed_at = datetime.now(timezone.utc)
    plaintext_codes = generate_recovery_codes(settings.MFA_RECOVERY_CODES_COUNT)
    await crud_mfa.replace_recovery_codes(
        session,
        device=device,
        plaintext_codes=plaintext_codes,
    )
    await crud_user.set_mfa_enabled(session, user=current_user, enabled=True)

    return {"recovery_codes": plaintext_codes, "warning": "Store these codes now. They will NOT be shown again."}


@router.post("/challenge")
async def challenge(body: MFAChallengeRequest, session: SessionDep):
    user_id = _decode_pending_token(body.pending_token)

    if not await check_and_consume(user_id):
        raise HTTPException(429, "Too many MFA attempts; try again later")

    device = await crud_mfa.get_device(session, user_id=user_id)
    if not device or device.confirmed_at is None:
        raise HTTPException(404, "No active MFA device")

    secret = decrypt_secret(device.secret_enc)
    valid = secret and verify_totp(secret, body.code, valid_window=settings.MFA_TOTP_WINDOW)

    if not valid:
        # Try recovery codes
        valid = await crud_mfa.consume_recovery_code(session, device=device, code=body.code)

    if not valid:
        raise HTTPException(401, "Invalid MFA code")

    device.last_used_at = datetime.now(timezone.utc)
    return {"access_token": create_access_token(subject=user_id), "token_type": "bearer"}


@router.post("/disable")
async def disable_mfa(
    body: MFAChallengeRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    device = await crud_mfa.get_device(session, user_id=current_user.id)
    if not device or device.confirmed_at is None:
        raise HTTPException(404, "MFA not enabled")

    secret = decrypt_secret(device.secret_enc)
    if not secret or not verify_totp(secret, body.code, valid_window=settings.MFA_TOTP_WINDOW):
        raise HTTPException(401, "Invalid TOTP")

    await crud_mfa.delete_device(session, device=device)
    await crud_user.set_mfa_enabled(session, user=current_user, enabled=False)
    return {"status": "ok"}
```

### 4.7 Login flow change (existing route patched)
```python
# app/api/routes/login.py (fragment, AFTER patch)
@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: SessionDep = ...,
):
    user = await crud_user.authenticate(session, email=form_data.username, password=form_data.password)
    if not user or not user.is_active:
        raise HTTPException(401, "Incorrect email or password")

    if user.mfa_enabled:
        return {
            "mfa_required": True,
            "pending_token": _create_pending_token(user.id),
        }

    return {"access_token": create_access_token(subject=user.id), "token_type": "bearer"}
```

### 4.8 Migration
```python
# alembic/versions/0013_add_mfa.py
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "mfa_devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("type", sa.String(16), server_default="totp", nullable=False),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type IN ('totp')", name="ck_mfa_devices_type"),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("mfa_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mfa_recovery_codes_device_id", "mfa_recovery_codes", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_mfa_recovery_codes_device_id", "mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_devices")
    op.drop_column("users", "mfa_enabled")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **TOTP secret encrypted at rest** | `secret_enc: LargeBinary` Fernet payload; plaintext never stored. |
| QS-2 | **Recovery codes hashed with argon2id** | `hash_recovery_code` uses argon2-cffi; verify uses `argon2.verify`. |
| QS-3 | **Recovery codes are single-use** | `used_at` set on consume; verifier rejects already-used codes. |
| QS-4 | **TOTP verification is constant-time** | `pyotp.TOTP.verify` uses `hmac.compare_digest` internally. |
| QS-5 | **Rate-limited per user** | Redis INCR + EXPIRE; over-limit returns 429. |
| QS-6 | **Pending token is short-lived and purpose-tagged** | JWT with `purpose=mfa_pending` and 5 min TTL; cannot be used as access token. |
| QS-7 | **Plaintext recovery codes shown exactly once** | Returned only at enrollment; never returned later. |
| QS-8 | **Plaintext TOTP secret shown exactly once** | Returned in enrollment response only; never queryable later. |
| QS-9 | **Disable requires fresh TOTP** | Cannot disable MFA without proving possession of the device. |
| QS-10 | **Login flow auto-detects MFA** | Existing login route patched to return `{mfa_required: true, pending_token}` if user has confirmed MFA. |
| QS-11 | **Window is bounded** | `totp_window` defaults to 1 (±30s); larger windows accepted at user's risk. |
| QS-12 | **Fernet key is mandatory** | `MFA_FERNET_KEY` required at startup; raises if missing. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `MFADevice` and `MFARecoveryCode` models exist at `app/models/mfa.py` | File exists |
| CC-02 | `app/core/mfa/crypto.py` exists with encrypt/decrypt | File exists |
| CC-03 | `app/core/mfa/totp.py` exists with secret/uri/verify/recovery generation | File exists |
| CC-04 | `app/core/mfa/recovery.py` exists with hash/verify | File exists |
| CC-05 | `app/core/mfa/rate_limit.py` exists | File exists |
| CC-06 | `app/crud/mfa.py` exists with create/get/replace_recovery/consume_recovery/delete | File exists |
| CC-07 | `app/api/routes/mfa.py` exists with enroll/verify/challenge/disable | File exists |
| CC-08 | `app/schemas/mfa.py` has all schemas | File exists |
| CC-09 | Migration `0013_add_mfa.py` exists | File exists |
| CC-10 | Migration creates 2 tables + adds users.mfa_enabled column | Inspect upgrade() |
| CC-11 | `MFA_FERNET_KEY` settings is required | grep config.py |
| CC-12 | `MFA_RECOVERY_CODES_COUNT`, `MFA_TOTP_WINDOW`, `MFA_MAX_ATTEMPTS_PER_15MIN`, `MFA_ISSUER` settings | grep |
| CC-13 | Existing login route patched to handle mfa_enabled | grep `mfa_required` in login.py |
| CC-14 | Pending token has `purpose=mfa_pending` and 5 min TTL | grep |
| CC-15 | Recovery codes returned only at enrollment, never at verify-enrollment for re-issuance | grep response shape |
| CC-16 | Plaintext TOTP secret returned only at enrollment | grep response shape |
| CC-17 | Routes registered in `app/api/main.py` | grep router include |
| CC-18 | OpenAPI exposes new endpoints | curl /openapi.json |
| CC-19 | New file `tests/test_mfa.py` with 30 tests | File exists |
| CC-20 | Existing tests pass | pytest 0 failures |
| CC-21 | All files parse | Tool internal |
| CC-22 | Tool execution time < 5s | Time measurement |
| CC-23 | TOTP verify p99 < 5 ms | Benchmark T-29 |
| CC-24 | Recovery code verify p99 < 50 ms (argon2 cost) | Benchmark T-30 |
| CC-25 | Rate limit returns 429 after N attempts | T-22 |
| CC-26 | Recovery code single-use enforced | T-15 |
| CC-27 | Idempotent re-run | T-26 |
| CC-28 | Disable requires TOTP | T-19 |
| CC-29 | Pending token cannot be used as access token | T-12 |
| CC-30 | TOTP window respected | T-09 |

---

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 7 Invariants enforced
- [ ] All 25 User Stories pass acceptance tests
- [ ] All 30 Test Cases pass
- [ ] Tool is idempotent
- [ ] Tool is reversible
- [ ] Performance budget met
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-MFA-01 | The TOTP secret is NEVER stored or returned in plaintext after enrollment | `secret_enc` only column; `provision` returns plaintext once and only once | T-13 |
| INV-MFA-02 | A recovery code is consumed exactly once | `used_at` set atomically; verifier filters `WHERE used_at IS NULL` | T-15 |
| INV-MFA-03 | A `pending_token` CANNOT authorize a normal API call | Token has `purpose=mfa_pending`; `get_current_user` rejects | T-12 |
| INV-MFA-04 | An MFA-enabled user CANNOT log in with password alone | Login route checks `mfa_enabled` and short-circuits to pending flow | T-08 |
| INV-MFA-05 | A user CANNOT disable their own MFA without proving possession | `/auth/mfa/disable` requires a fresh TOTP code | T-19 |
| INV-MFA-06 | Brute-force is bounded by rate limit | INCR + EXPIRE; > LIMIT → 429 — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-22 |
| INV-MFA-07 | TOTP verification is constant-time | `pyotp.TOTP.verify` uses `compare_digest` | T-30 |

---

## 9. User Stories

### 9.1 Enrollment Flow (US-01 .. US-05)

**US-01: Initiate TOTP enrollment and receive QR code**
- **As a** user
- **I want** to call `POST /auth/mfa/enroll` on a confirmed account without MFA
- **So that** I receive a `provisioning_uri`, inline `qr_svg`, and plaintext `secret` to scan into Google Authenticator or 1Password
- **Given:** authenticated user with `mfa_enabled = false` and no existing `MFADevice`
- **When:** `POST /auth/mfa/enroll` (valid `Authorization: Bearer <access_token>`)
- **Then:**
  - Response status is `200`; body contains `provisioning_uri`, `qr_svg` (SVG string), and `secret` (base32)
  - `provisioning_uri` follows RFC 6238 format: `otpauth://totp/<issuer>:<email>?secret=...&issuer=...`
  - A new unconfirmed `MFADevice` row exists in DB with `confirmed_at = NULL`
  - Refs: CC-01, CC-03, CC-07, CC-08

**US-02: Confirm enrollment by submitting a valid 6-digit TOTP code**
- **As a** user
- **I want** to call `POST /auth/mfa/verify-enrollment` with a live TOTP code after scanning the QR
- **So that** MFA is activated on my account and I receive my single-use recovery codes
- **Given:** unconfirmed `MFADevice` in DB for the authenticated user
- **When:** `POST /auth/mfa/verify-enrollment {"code": "<valid 6-digit TOTP>"}` within ±1 window
- **Then:**
  - Response status is `200`; body contains `recovery_codes` array of exactly `recovery_codes_count` plaintext codes
  - `MFADevice.confirmed_at` is set to the current UTC timestamp
  - `users.mfa_enabled` flips to `true`
  - `mfa_recovery_codes` table has `recovery_codes_count` rows, each with an argon2id hash and `used_at = NULL`
  - Refs: CC-01, CC-09, CC-10, INV-MFA-01, T-02

**US-03: Re-enrollment replaces an unconfirmed device without 409**
- **As a** user
- **I want** to call `POST /auth/mfa/enroll` again after scanning but before confirming
- **So that** a lost QR or mis-scan does not lock me into an unverifiable device
- **Given:** existing unconfirmed `MFADevice` (`confirmed_at = NULL`) for the user
- **When:** `POST /auth/mfa/enroll` is called a second time
- **Then:**
  - Response status is `200` with a fresh `secret` and `qr_svg`
  - The previous unconfirmed device's `secret_enc` is overwritten in-place (no orphan rows)
  - Calling `POST /auth/mfa/verify-enrollment` with the OLD secret returns `400`
  - Refs: CC-01, CC-07, T-04

**US-04: Enrolling on an already-confirmed account returns 409**
- **As a** user
- **I want** to see a clear error when I accidentally call enroll on an active MFA account
- **So that** I cannot silently overwrite an active device and lose my second factor
- **Given:** `MFADevice` with `confirmed_at` set and `users.mfa_enabled = true`
- **When:** `POST /auth/mfa/enroll`
- **Then:**
  - Response status is `409` with detail `"MFA already enabled"`
  - Existing `MFADevice` and `mfa_recovery_codes` rows are untouched
  - Refs: CC-07, INV-MFA-05, T-05

**US-05: Plaintext TOTP secret is returned exactly once and never queryable again**
- **As a** security engineer
- **I want** the enrollment endpoint to return the raw base32 secret in the response body only once
- **So that** if the enrollment response is intercepted, re-querying the API does not expose the secret a second time
- **Given:** confirmed or unconfirmed `MFADevice`
- **When:** `SELECT secret_enc FROM mfa_devices WHERE user_id = :uid` is executed after enrollment
- **Then:**
  - Column value is a Fernet-encrypted byte blob, not the plaintext base32
  - No GET endpoint exposes `secret` or `secret_enc`; only the initial `POST /enroll` response ever contains it
  - Refs: CC-02, CC-16, INV-MFA-01, T-13

### 9.2 Login Two-Step Exchange (US-06 .. US-10)

**US-06: Password-only login for non-MFA user returns a full access token directly**
- **As a** user
- **I want** `POST /login` to return `access_token` immediately when my account has `mfa_enabled = false`
- **So that** the MFA layer adds zero friction for accounts that have not enrolled
- **Given:** user row with `mfa_enabled = false`, valid credentials
- **When:** `POST /login` with correct email and password
- **Then:**
  - Response is `{"access_token": "...", "token_type": "bearer"}` with HTTP 200
  - No `mfa_required` key is present in the response body
  - The returned JWT can authorize `GET /users/me` successfully
  - Refs: CC-13, T-06

**US-07: Password login for MFA-enabled user returns a short-lived pending token instead of an access token**
- **As a** user
- **I want** `POST /login` to return `{"mfa_required": true, "pending_token": "..."}` when my account has `mfa_enabled = true`
- **So that** my password alone cannot be used to complete authentication
- **Given:** user with `mfa_enabled = true` and a confirmed `MFADevice`
- **When:** `POST /login` with correct credentials
- **Then:**
  - Response is `{"mfa_required": true, "pending_token": "<jwt>"}` with HTTP 200
  - The pending token JWT payload contains `"purpose": "mfa_pending"` and `"exp"` set 5 minutes from issue
  - No `access_token` key appears in the response
  - Refs: CC-13, CC-14, INV-MFA-04, T-07

**US-08: A pending token cannot authorize a protected endpoint**
- **As a** security engineer
- **I want** `Authorization: Bearer <pending_token>` to be rejected on any regular API route
- **So that** an attacker who captures the pending token cannot use it as a session credential
- **Given:** valid `pending_token` returned from `POST /login` for an MFA-enabled user
- **When:** `GET /users/me` with `Authorization: Bearer <pending_token>`
- **Then:**
  - Response is HTTP 401
  - `get_current_user` dependency detects `purpose == "mfa_pending"` and raises `HTTPException(401)`
  - The pending token cannot be exchanged for an `access_token` by calling any route other than `/auth/mfa/challenge`
  - Refs: CC-14, INV-MFA-03, T-08, T-24

**US-09: Valid TOTP code submitted to /challenge exchanges pending token for a full JWT**
- **As a** user
- **I want** `POST /auth/mfa/challenge` to return `{"access_token": "...", "token_type": "bearer"}` when I provide a live TOTP code
- **So that** I complete the two-step login and gain a usable session
- **Given:** valid `pending_token` (< 5 min old) and a live 6-digit TOTP code from my authenticator app
- **When:** `POST /auth/mfa/challenge {"pending_token": "...", "code": "<live TOTP>"}`
- **Then:**
  - Response is HTTP 200 with `access_token` and `token_type: "bearer"`
  - `MFADevice.last_used_at` is updated to the current UTC timestamp
  - The returned `access_token` passes `GET /users/me` without error
  - Refs: CC-07, INV-MFA-04, T-09

**US-10: TOTP code from a step outside the ±1 drift window is rejected**
- **As a** security engineer
- **I want** codes older than ±30 seconds (window = 1) to be refused at `/challenge`
- **So that** a replayed or shoulder-surfed code from a previous login session cannot be reused
- **Given:** `pending_token` and a TOTP code generated 90+ seconds ago (outside window = 1)
- **When:** `POST /auth/mfa/challenge {"pending_token": "...", "code": "<stale TOTP>"}`
- **Then:**
  - Response is HTTP 401
  - `verify_totp` returns `False` because the step counter is outside `valid_window`
  - `MFADevice.last_used_at` is NOT updated
  - Refs: CC-12, CC-30, INV-MFA-07, T-10

### 9.3 Recovery Codes (US-11 .. US-15)

**US-11: A single valid recovery code completes the /challenge flow**
- **As a** user
- **I want** to substitute a recovery code for a TOTP code at `/challenge` when my phone is unavailable
- **So that** I can regain access to my account without the authenticator app
- **Given:** confirmed `MFADevice`, at least one unused recovery code `code_hash` in `mfa_recovery_codes`
- **When:** `POST /auth/mfa/challenge {"pending_token": "...", "code": "<plaintext recovery code>"}`
- **Then:**
  - Response is HTTP 200 with `access_token`
  - `argon2.verify` succeeds against the stored `code_hash`
  - `mfa_recovery_codes.used_at` is set for that row atomically
  - Refs: CC-06, INV-MFA-02, T-11

**US-12: Recovery code is marked used and cannot authenticate a second time**
- **As a** user
- **I want** each recovery code to work exactly once
- **So that** a code leaked in a log or network trace cannot be replayed
- **Given:** recovery code `abc1-def2` submitted successfully at `/challenge` (first use)
- **When:** `POST /auth/mfa/challenge` with the same code `abc1-def2` again
- **Then:**
  - Response is HTTP 401 on the second use
  - `crud_mfa.consume_recovery_code` queries `WHERE used_at IS NULL` and finds no matching row
  - `mfa_recovery_codes` row has `used_at` populated from the first use
  - Refs: CC-26, INV-MFA-02, T-15

**US-13: Exhausting all 10 recovery codes while also having lost TOTP leaves the user locked out**
- **As a** compliance officer
- **I want** the system to have no automatic bypass once all recovery codes are consumed
- **So that** account takeover via brute-forced recovery codes is bounded and escalates to an admin recovery flow
- **Given:** all 10 `mfa_recovery_codes` rows have `used_at` set; no authenticator app available
- **When:** `POST /auth/mfa/challenge` with any TOTP or recovery code
- **Then:**
  - Response is HTTP 401 for every attempt
  - No new recovery codes are generated automatically; user must contact admin
  - Refs: CC-26, INV-MFA-02, T-15

**US-14: Disabling MFA with a valid fresh TOTP deletes the device and all recovery codes**
- **As a** user
- **I want** `POST /auth/mfa/disable` with a live TOTP to remove MFA from my account
- **So that** if I switch authenticator apps I can cleanly re-enroll without orphaned data
- **Given:** confirmed `MFADevice`, `users.mfa_enabled = true`, valid TOTP code in current window
- **When:** `POST /auth/mfa/disable {"code": "<valid TOTP>"}` (authenticated)
- **Then:**
  - Response is HTTP 200 `{"status": "ok"}`
  - `mfa_devices` row deleted via `crud_mfa.delete_device`; cascade removes all `mfa_recovery_codes` rows
  - `users.mfa_enabled` set to `false`
  - Subsequent `POST /login` returns a full `access_token` without the MFA step
  - Refs: CC-07, INV-MFA-05, T-17, T-18

**US-15: Attempting to disable MFA with a wrong or expired TOTP is rejected**
- **As a** security engineer
- **I want** `POST /auth/mfa/disable` to return 401 when the code is invalid
- **So that** a stolen session token alone cannot silently remove the second factor
- **Given:** confirmed `MFADevice`, `users.mfa_enabled = true`
- **When:** `POST /auth/mfa/disable {"code": "000000"}` (wrong code)
- **Then:**
  - Response is HTTP 401 `"Invalid TOTP"`
  - `MFADevice` and `mfa_recovery_codes` rows remain intact
  - `users.mfa_enabled` stays `true`
  - Refs: CC-28, INV-MFA-05, T-19

### 9.4 Rate Limiting & Lockout (US-16 .. US-20)

**US-16: Five consecutive wrong codes are each rejected with 401, not 429**
- **As a** user
- **I want** the first five wrong attempts within a 15-minute window to return 401 (not a lockout)
- **So that** a single transient typo or clock-skew event does not lock me out immediately
- **Given:** confirmed `MFADevice`; Redis key `mfa:attempts:<user_id>:<bucket>` starts at 0
- **When:** `POST /auth/mfa/challenge` with wrong code, repeated 5 times within 15 minutes
- **Then:**
  - Each of the 5 responses is HTTP 401 `"Invalid MFA code"`
  - Redis `INCR` key reaches `5`; `check_and_consume` returns `True` for all 5 calls
  - Refs: INV-MFA-06, T-20

**US-17: The sixth wrong code within the same 15-minute window is rejected with 429**
- **As a** security engineer
- **I want** the system to return HTTP 429 after `max_attempts_per_15min` failures in a single bucket
- **So that** automated brute-force of the 6-digit TOTP space is computationally infeasible
- **Given:** Redis key `mfa:attempts:<user_id>:<bucket>` already at `5`
- **When:** `POST /auth/mfa/challenge` (6th attempt, any code)
- **Then:**
  - Response is HTTP 429 `"Too many MFA attempts; try again later"`
  - `check_and_consume` increments the counter to `6` and returns `False` before code verification
  - The TOTP secret is never decrypted during a rate-limited call
  - Refs: CC-25, INV-MFA-06, T-21

**US-18: Rate-limit bucket is scoped to user_id, not to IP address**
- **As a** security engineer
- **I want** failed attempts for user A to not affect user B even if both come from the same IP
- **So that** a shared corporate NAT does not accidentally lock out unrelated users
- **Given:** user A has exhausted 5 attempts (Redis key for user A at `5`)
- **When:** user B submits a correct TOTP code from the same IP address
- **Then:**
  - User B receives HTTP 200 with `access_token`
  - Redis key for user B is at `1` (or `0` if they had none)
  - Refs: CC-25, INV-MFA-06, T-22

**US-19: Rate-limit bucket resets automatically after 15 minutes**
- **As a** user
- **I want** to retry MFA after 15 minutes even if I previously hit the limit
- **So that** a legitimate user who mis-typed is not permanently locked out
- **Given:** Redis key `mfa:attempts:<user_id>:<bucket>` has TTL set to `WINDOW * 2`
- **When:** the 15-minute window rolls over (new `bucket = int(time.time() // WINDOW)`)
- **Then:**
  - New bucket key starts at `0`; first attempt with correct code returns HTTP 200
  - Old bucket key expires via Redis `EXPIRE WINDOW * 2`
  - Refs: CC-25, INV-MFA-06, T-23

**US-20: Pending token rejected after its 5-minute TTL expires**
- **As a** user
- **I want** `POST /auth/mfa/challenge` to return 401 if I take longer than 5 minutes between login and TOTP submission
- **So that** a stolen or cached pending token has a narrow attack window
- **Given:** `pending_token` issued 6 minutes ago (`exp` in the past)
- **When:** `POST /auth/mfa/challenge {"pending_token": "<expired>", "code": "<valid TOTP>"}`
- **Then:**
  - Response is HTTP 401 `"Invalid pending token"`
  - `_decode_pending_token` raises `HTTPException(401)` because `jwt.decode` raises `ExpiredSignatureError`
  - The TOTP code is never evaluated against the device secret
  - Refs: CC-14, CC-29, INV-MFA-03, T-12

### 9.5 Admin Policy & Edge Cases (US-21 .. US-25)

**US-21: Tool re-run on a project with MFA already installed is a no-op**
- **As a** backend developer
- **I want** running `add_mfa(project_dir)` a second time to make no file or database changes
- **So that** CI pipelines and re-deployments are safe to run without manual checks
- **Given:** all MFA files exist, `mfa_devices` table present in Alembic history
- **When:** `add_mfa(project_dir)` is called again
- **Then:**
  - No source files are overwritten; `git diff HEAD` shows 0 changes
  - Alembic detects the migration already applied and skips it
  - Tool returns `{"status": "already_installed"}` or equivalent
  - Refs: CC-21, CC-27, T-26

**US-22: Admin can force MFA requirement for a specific RBAC role via policy enforcement**
- **As an** admin
- **I want** to configure a role (e.g., `"admin"`) to require confirmed MFA on every request
- **So that** privileged accounts cannot access sensitive endpoints using password-only authentication
- **Given:** TOOL-012 RBAC installed; `MFA_REQUIRED_ROLES = ["admin"]` set in config
- **When:** an `"admin"` user with `mfa_enabled = false` calls a protected admin endpoint
- **Then:**
  - Response is HTTP 403 with detail `"MFA required for this role"`
  - Regular `"user"` role accounts are unaffected by this policy check
  - Refs: CC-11, CC-12, INV-MFA-04

**US-23: Clock drift of ±30 seconds (window = 1) is tolerated during challenge**
- **As a** user
- **I want** a TOTP code generated up to ±30 seconds from server time to be accepted
- **So that** users with slightly unsynchronized device clocks are not constantly rejected
- **Given:** `MFA_TOTP_WINDOW = 1`; user device clock is 25 seconds behind server
- **When:** `POST /auth/mfa/challenge` with a TOTP code from the previous 30-second step
- **Then:**
  - Response is HTTP 200 with `access_token`
  - `pyotp.TOTP.verify(code, valid_window=1)` evaluates steps `t-1`, `t`, and `t+1`
  - Refs: CC-30, T-09

**US-24: Fernet key rotation re-encrypts secrets without invalidating active devices**
- **As a** security engineer
- **I want** to rotate `MFA_FERNET_KEY` by using `MultiFernet([new_key, old_key])` without forcing users to re-enroll
- **So that** a compromised key can be replaced transparently while existing TOTP sessions remain active
- **Given:** `MFADevice` rows encrypted with `old_key`; `MultiFernet` configured with `[new_key, old_key]`
- **When:** `decrypt_secret(device.secret_enc)` is called during a challenge
- **Then:**
  - `MultiFernet.decrypt` succeeds using the old key fallback
  - A background re-encryption job can replace each `secret_enc` with a new-key-only blob
  - After re-encryption, removing `old_key` from the chain does not break any active device
  - Refs: CC-02, CC-11, INV-MFA-01

**US-25: TOTP verification p99 latency stays below 5 ms under load**
- **As a** backend developer
- **I want** `verify_totp(secret, code, valid_window=1)` to complete in under 5 ms at p99
- **So that** the MFA challenge endpoint contributes negligible latency to the overall login SLO
- **Given:** `10_000` confirmed `MFADevice` records in DB; `secret_enc` decrypted to plaintext in memory
- **When:** 1000 consecutive `verify_totp` calls are benchmarked (mix of valid and invalid codes)
- **Then:**
  - p99 latency is < 5 ms (constant-time `hmac.compare_digest` inside `pyotp.TOTP.verify`)
  - Timing variance between correct and incorrect codes is < 1 ms (no timing oracle)
  - Refs: CC-23, CC-24, INV-MFA-07, T-29, T-30

## 10. Test Plan

### 10.1 Enrollment

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Enroll returns secret + QR | logged in | POST /enroll | 200 with secret, qr_svg, uri |
| T-02 | Verify-enrollment with valid code → 200 | enrolled, valid TOTP | POST /verify-enrollment | 200 with recovery_codes |
| T-03 | Verify-enrollment with bad code → 400 | enrolled, bad code | POST /verify-enrollment | 400 |
| T-04 | Re-enroll replaces unconfirmed device | unconfirmed | POST /enroll | new secret; old replaced |
| T-05 | Re-enroll on confirmed device → 409 | confirmed | POST /enroll | 409 |

### 10.2 Login & challenge

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | Login without MFA → access_token | user no mfa | POST /login | normal token |
| T-07 | Login with MFA → pending_token | mfa user | POST /login | mfa_required, pending |
| T-08 | Pending token cannot access protected route | bearer pending | GET /users/me | 401 |
| T-09 | TOTP within window valid | live code | POST /challenge | 200 access_token |
| T-10 | TOTP outside window invalid | drift code | POST /challenge | 401 |
| T-11 | Recovery code completes | use 1 of 10 | POST /challenge | 200 |
| T-12 | Pending token expired → 401 | wait 6 min | challenge | 401 |

### 10.3 Recovery codes & disable

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Plaintext secret not stored | enroll | inspect DB | secret_enc != plaintext |
| T-14 | Recovery codes hashed | enroll + verify | inspect | argon2 hash strings |
| T-15 | Recovery code single-use | use once | use again | 401 |
| T-16 | Recovery code mark used | use once | inspect | used_at populated |
| T-17 | Disable with valid TOTP | confirmed | POST /disable | 200; device gone |
| T-18 | mfa_enabled flips false on disable | confirmed | POST /disable | users.mfa_enabled=false |
| T-19 | Disable without TOTP → 401 | confirmed | POST /disable {wrong} | 401, device intact |

### 10.4 Rate limit & security

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-20 | 5 wrong attempts allowed | 5 wrong | observe | each 401 |
| T-21 | 6th attempt → 429 | 5 wrong | 6th | 429 |
| T-22 | Rate limit per user not IP | userA 5 wrong, userB attempt | userB | allowed |
| T-23 | Window resets after 15 min | wait | retry | allowed |
| T-24 | Pending token wrong purpose rejected | forge `purpose=foo` | challenge | 401 |
| T-25 | TOTP code with 5 chars rejected | "12345" | challenge | 401 |

### 10.5 Idempotency, integration, performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-26 | Tool re-run is no-op | installed | run | no changes |
| T-27 | Audit entry on enroll | audit installed | enroll | audit row written |
| T-28 | OpenAPI exposes endpoints | installed | curl /openapi.json | paths present |
| T-29 | TOTP verify p99 < 5 ms | benchmark | measure | < 5 ms |
| T-30 | TOTP verify constant-time | benchmark right vs wrong | measure | timing variance < 1 ms; recovery argon2 verify p99 < 50 ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_oauth2_provider` | No | ⚠️ Caveat | OAuth login bypasses password but should still trigger MFA challenge if mfa_enabled. Patch needed in OAuth callback. |
| `add_api_key_auth` | No | ✅ Compatible | API keys are independent of MFA; document the trade-off. |
| `add_audit_log` | **Audit first** | ✅ Compatible | Enroll/verify/disable produce audit rows. |
| `add_rbac` | No | ✅ Compatible | MFA is independent of permissions. |
| `add_multi_tenancy` | No | ✅ Compatible | MFA is per-user, not per-tenant. |
| `add_feature_flags` | No | ✅ Compatible | Can flag-gate the MFA enrollment flow. |
| `add_rate_limit` | No | ✅ Compatible | MFA already has its own per-user limit. |
| `add_security_headers` | No | ✅ Compatible | Independent. |
| `add_email_verification` (if exists) | No | ✅ Compatible | Both gate user actions. |
| TOOL-034 performance_baseline | downstream | `/auth/mfa/challenge` latency is captured in the baseline (target p99 < 200 ms) so a future change to Argon2id cost parameters in `app/core/mfa/crypto.py` or to TOTP window validation in `app/core/mfa/totp.py` does not silently slow down the login hot path |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_mfa` is installed but `add_oauth2_provider` is also present without a patch in the OAuth callback and recommends updating `app/api/routes/oauth.py` to redirect to `/auth/mfa/challenge` after OAuth login when `user.mfa_enabled=True` — flagged as HIGH security gap |
| TOOL-029 security_scan | downstream | `app/core/mfa/crypto.py` and `app/core/mfa/rate_limit.py` are scanned for hardcoded TOTP secrets (bandit B105), insecure random in recovery code generation (bandit B311), and missing `hmac.compare_digest` in TOTP verification; any CRITICAL finding blocks merge |

**Conflicts:**
- None identified. **Caveat**: OAuth flow must be patched manually if MFA must apply to OAuth users; document this in next_steps.

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/mfa.py app/core/mfa app/crud/mfa.py \
  app/api/routes/mfa.py app/schemas/mfa.py app/api/routes/login.py \
  app/api/main.py app/core/config.py
rm alembic/versions/*_add_mfa.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `mfa_devices`, `mfa_recovery_codes`, and the `users.mfa_enabled` column. **Warning**: existing MFA-enabled users will lose MFA after downgrade; communicate the change.

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_mfa.py`
- Drop partially-created tables
- Re-run tool

### Emergency: Fernet key compromised
1. Generate a new key
2. Use `MultiFernet([new, old])` so old payloads still decrypt
3. Background job: re-encrypt all secrets with the new key
4. Remove old key from `MultiFernet`
5. If urgent, force every user to re-enroll: `UPDATE mfa_devices SET confirmed_at = NULL` + `UPDATE users SET mfa_enabled = false`

### Emergency: user locked out
- Admin endpoint (out of scope of this tool) can revoke MFA on a user account; mention in next_steps


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

### Failure mode: Fernet key rotation mid-deploy leaves TOTP secrets unreadable
If `MFA_FERNET_KEY` was rotated while enrolled users still have secrets encrypted under the old key, every TOTP verification returns `Invalid code` regardless of the correct OTP:
```bash
# 1. Confirm the symptom: decryption error in logs, not a wrong-code error
grep '"event":"totp_decrypt_error"' /var/log/app/structured.log | tail -20

# 2. Restore MultiFernet with both keys to unlock the transition window
python - <<'EOF'
from cryptography.fernet import Fernet, MultiFernet
import os
new = os.environ["MFA_FERNET_KEY"]
old = os.environ["MFA_FERNET_KEY_OLD"]   # must be set from secrets manager
test = MultiFernet([Fernet(new), Fernet(old)])
print("MultiFernet OK — update app/core/mfa/crypto.py to use both keys")
EOF

# 3. Run the re-encryption migration to move all secrets to the new key
psql $DATABASE_URL -c "SELECT COUNT(*) FROM mfa_devices WHERE confirmed_at IS NOT NULL;"
python scripts/reencrypt_mfa_secrets.py --dry-run   # preview
python scripts/reencrypt_mfa_secrets.py             # execute

# 4. Verify re-encryption by spot-checking one device
psql $DATABASE_URL -c "SELECT id, user_id, created_at FROM mfa_devices LIMIT 5;"
python - <<'EOF'
import os, psycopg2
from cryptography.fernet import Fernet
f = Fernet(os.environ["MFA_FERNET_KEY"].encode())
# spot-decrypt one secret to confirm
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(); cur.execute("SELECT encrypted_secret FROM mfa_devices LIMIT 1")
row = cur.fetchone(); f.decrypt(row[0].encode()); print("decryption OK")
EOF

# 5. Remove old key from MultiFernet and redeploy clean config
```

### Emergency: clock drift causing mass TOTP lockout across all users
If NTP desync pushes server time > 60 s from clients, TOTP codes generated by authenticator apps fail verification even though they are correct (window=1 accepts ±30 s):
```bash
# 1. Check server time vs an NTP reference
date -u && curl -sI https://www.google.com 2>&1 | grep -i "^date:"

# 2. Diagnose NTP daemon status on the host / pod
timedatectl status 2>/dev/null || chronyc tracking 2>/dev/null || ntpstat 2>/dev/null

# 3. Immediate relief: widen the TOTP acceptance window in config (temporary!)
#    Set MFA_TOTP_WINDOW=3 (accepts ±90 s) and redeploy; update .env:
sed -i.bak 's/^MFA_TOTP_WINDOW=.*/MFA_TOTP_WINDOW=3/' .env

# 4. Force NTP resync on the host (requires host-level access or restart)
sudo systemctl restart systemd-timesyncd 2>/dev/null || sudo ntpdate -s time.nist.gov

# 5. Monitor: watch the drift close over the next 5-10 minutes
watch -n5 'date -u && chronyc tracking | grep "RMS offset"'

# 6. Once drift < 5 s, revert MFA_TOTP_WINDOW to 1 and redeploy; confirm logins work
# 7. Record incident: grep for failed verifications during drift window to assess blast radius
grep '"event":"totp_verify_failed"' /var/log/app/structured.log \
  | jq -r '.timestamp' | sort | uniq -c | sort -rn | head -20
```


---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no User model | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | MFA_FERNET_KEY missing | App startup fails; the operation returns a structured error response and no side effects persist |
| EC-3 | pyotp / segno not installed | Tool runs `pip install pyotp segno` or warns |
| EC-4 | User scans QR but never confirms | Unconfirmed device; re-enroll replaces it |
| EC-5 | Clock drift > 30s on user device | Invalid code; user must sync time |
| EC-6 | TOTP code not 6 digits | Reject early without DB hit |
| EC-7 | Recovery code with wrong format | Reject early; the operation returns a structured error response and no side effects persist |
| EC-8 | Concurrent challenges with same recovery code | First wins; second 401; the operation returns a structured error response and no side effects persist |
| EC-9 | User deleted with active MFA | FK CASCADE drops device + codes |
| EC-10 | Replaying a captured TOTP within the same window | pyotp considers it valid; this is a known TOTP property; mitigation = small window |
| EC-11 | All recovery codes used | User must restore TOTP or contact support; flow has no automatic recovery |
| EC-12 | Pending token reused | JWT exp prevents replay after 5 min |
| EC-13 | Disable while challenge in flight | last-write wins; cache clears next request |
| EC-14 | Migration on existing users with no devices | OK; users.mfa_enabled defaults to false |
| EC-15 | Tool installed without Redis | Rate limit fails open or errors; tool warns at install |

---

## 14. Acceptance Criteria

1. ✅ All 30 CC verified
2. ✅ All 25 user stories pass
3. ✅ All 30 tests pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified
7. ✅ Rollback procedure tested
8. ✅ Performance SLOs met
9. ✅ Re-audit by Opus: ≥ 9.5/10
10. ✅ One human dev enrolls, logs out, logs back in with TOTP, uses a recovery code, and disables MFA — all without confusion

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Alembic initialized
- [ ] Validate Redis URL configured
- [ ] Detect existing `mfa_devices` table → idempotent skip if found
- [ ] Validate pyotp + segno + argon2-cffi installed (or run pip install)
- [ ] Assert pre-flight raises `MissingDependencyError` when pyotp is absent via `test_preflight.py::test_missing_pyotp_raises`
- [ ] Assert pre-flight returns `{"skipped": true}` when `mfa_devices` table already exists via `test_preflight.py::test_idempotent_skip_when_table_exists`

### 15.2 Settings
- [ ] Add `MFA_FERNET_KEY: str` (required)
- [ ] Add `MFA_RECOVERY_CODES_COUNT: int = 10`
- [ ] Add `MFA_TOTP_WINDOW: int = 1`
- [ ] Add `MFA_MAX_ATTEMPTS_PER_15MIN: int = 5`
- [ ] Add `MFA_ISSUER: str = "MyApp"`
- [ ] Add to `.env.example`
- [ ] Assert `MFA_FERNET_KEY` missing causes startup `ValidationError` via `test_settings.py::test_missing_fernet_key_raises_validation_error`
- [ ] Assert `MFA_MAX_ATTEMPTS_PER_15MIN` is read from env and applied to rate-limiter via `test_settings.py::test_max_attempts_env_override`

### 15.3 Crypto module
- [ ] Create `app/core/mfa/crypto.py`
- [ ] Implement encrypt/decrypt
- [ ] Verify file parses
- [ ] Assert `decrypt(encrypt(secret)) == secret` for a 32-byte random TOTP secret via `test_crypto.py::test_encrypt_decrypt_roundtrip`
- [ ] Assert `decrypt` raises `InvalidToken` when ciphertext is tampered via `test_crypto.py::test_decrypt_raises_on_tampered_ciphertext`
- [ ] Run `mypy --strict app/core/mfa/crypto.py` — zero errors

### 15.4 TOTP module
- [ ] Create `app/core/mfa/totp.py`
- [ ] Implement generate_secret, provisioning_uri, qr_svg, verify_totp, generate_recovery_codes
- [ ] Verify file parses
- [ ] Assert `verify_totp` accepts a live OTP generated by `pyotp.TOTP(secret).now()` via `test_totp.py::test_verify_totp_accepts_current_code`
- [ ] Assert `verify_totp` rejects a code from 2 windows ago via `test_totp.py::test_verify_totp_rejects_expired_window`
- [ ] Assert `qr_svg` output is valid SVG (starts with `<svg`) via `test_totp.py::test_qr_svg_returns_valid_svg`
- [ ] Run `ruff check app/core/mfa/totp.py` — zero findings

### 15.5 Recovery module
- [ ] Create `app/core/mfa/recovery.py`
- [ ] Implement hash + verify with argon2
- [ ] Verify file parses
- [ ] Assert recovery code single-use enforcement via `test_recovery.py::test_used_code_rejected_on_second_use`
- [ ] Assert argon2 hash of two different codes are not equal via `test_recovery.py::test_hashes_are_unique_per_code`
- [ ] Assert `verify` returns `False` for a code that was never issued via `test_recovery.py::test_unknown_code_returns_false`

### 15.6 Rate limit module
- [ ] Create `app/core/mfa/rate_limit.py`
- [ ] Implement `check_and_consume`
- [ ] Verify file parses
- [ ] Assert the 6th attempt within 15 min raises `RateLimitExceeded` via `test_rate_limit.py::test_sixth_attempt_raises_rate_limit_exceeded`
- [ ] Assert the counter resets after the 15-min window expires via `test_rate_limit.py::test_counter_resets_after_window_expiry`
- [ ] Run `mypy --strict app/core/mfa/rate_limit.py` — zero errors

### 15.7 Model
- [ ] Create `app/models/mfa.py` with MFADevice + MFARecoveryCode
- [ ] Verify file parses via `python -c "import app.models.mfa"` — no ImportError
- [ ] Assert `UniqueConstraint` on `(user_id, device_type)` prevents duplicate device registration via `test_models_mfa.py::test_duplicate_device_raises_integrity_error`
- [ ] Assert `MFARecoveryCode.used_at` is `NULL` on creation and non-null after `consume_recovery_code` via `test_models_mfa.py::test_recovery_code_used_at_lifecycle`
- [ ] Add structured log entry `{"event": "mfa_device_created", "user_id": ..., "device_type": ...}` in `create_device`
- [ ] Assert `MFADevice.secret_encrypted` column is `BYTEA` / `LargeBinary` (not `String`) to store Fernet ciphertext correctly
- [ ] Assert `MFADevice.confirmed_at` is `NULL` until the enrollment verify step succeeds via `test_models_mfa.py::test_confirmed_at_null_pre_enrollment`

### 15.8 CRUD
- [ ] Create `app/crud/mfa.py` with create_device, get_device, replace_recovery_codes, consume_recovery_code, delete_device
- [ ] Verify file parses and all public helpers are importable from `app.crud.mfa`
- [ ] Assert `consume_recovery_code` sets `used_at` and returns `True` on first call, `False` on second via `test_crud_mfa.py::test_consume_recovery_code_single_use`
- [ ] Assert `replace_recovery_codes` deletes all old codes and inserts exactly `MFA_RECOVERY_CODES_COUNT` new ones via `test_crud_mfa.py::test_replace_recovery_codes_count`
- [ ] Add trace span `mfa.crud.consume_recovery_code` with tag `user_id` for observability
- [ ] Assert `delete_device` cascades to recovery codes via `test_crud_mfa.py::test_delete_device_cascades_recovery_codes` (0 rows remain after delete)
- [ ] Assert `get_device` is tenant-scoped via `test_crud_mfa.py::test_get_device_rejects_cross_tenant` (tenant B cannot fetch tenant A's device)

### 15.9 Schemas
- [ ] Create `app/schemas/mfa.py` with MFAEnrollResponse, MFAVerifyEnrollmentRequest, MFAChallengeRequest
- [ ] Pydantic validators on `code` (6-digit string OR recovery format)
- [ ] Verify file parses
- [ ] Assert `MFAChallengeRequest` validator rejects a 5-digit code via `test_schemas_mfa.py::test_code_validator_rejects_five_digit_code`
- [ ] Assert `MFAChallengeRequest` validator accepts a recovery-format code (e.g. `XXXX-XXXX`) via `test_schemas_mfa.py::test_code_validator_accepts_recovery_format`
- [ ] Run `mypy --strict app/schemas/mfa.py` — zero errors

### 15.10 Routes
- [ ] Create `app/api/routes/mfa.py` with enroll/verify-enrollment/challenge/disable
- [ ] Pending token JWT helpers
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Assert `POST /mfa/challenge` returns 200 and a full-access JWT when TOTP is correct via `test_routes_mfa.py::test_challenge_returns_full_access_token_on_correct_code`
- [ ] Assert `POST /mfa/challenge` returns 429 after 5 failed attempts within 15 min via `test_routes_mfa.py::test_challenge_rate_limits_after_max_attempts`
- [ ] Run `ruff check app/api/routes/mfa.py` — zero findings

### 15.11 Login route patch
- [ ] Read `app/api/routes/login.py`
- [ ] Inject MFA branch: if user.mfa_enabled → return pending token
- [ ] Verify file parses
- [ ] Assert login for MFA-enabled user returns a `pending` token (not a full-access token) via `test_routes_login.py::test_login_returns_pending_token_when_mfa_enabled`
- [ ] Assert pending token is rejected by routes that require a full-access token via `test_routes_login.py::test_pending_token_rejected_on_protected_route`
- [ ] Run `mypy app/api/routes/login.py` — zero new errors after the patch

### 15.12 User CRUD extension
- [ ] Add `set_mfa_enabled(user, enabled)` helper to `app/crud/user.py`
- [ ] Assert `set_mfa_enabled(user, True)` sets `user.mfa_enabled = True` and flushes to DB via `test_crud_user.py::test_set_mfa_enabled_persists`
- [ ] Assert disabling MFA also calls `delete_device` via `test_crud_user.py::test_disable_mfa_deletes_device`
- [ ] Run `ruff check app/crud/user.py` — zero new findings
- [ ] Add structured log entry `{"event": "mfa_status_changed", "user_id": ..., "enabled": ...}` in `set_mfa_enabled`
- [ ] Document `MFA_FERNET_KEY` rotation procedure in README under "Security"

### 15.13 Migration
- [ ] Generate `0NNN_add_mfa.py`
- [ ] `upgrade()` adds users.mfa_enabled + creates 2 tables
- [ ] `downgrade()` reverses
- [ ] Verify migration parses
- [ ] Assert `alembic upgrade head` + `alembic downgrade -1` completes cleanly on a blank schema via `test_migrations.py::test_mfa_migration_upgrade_downgrade_roundtrip`
- [ ] Assert `users.mfa_enabled` column is `FALSE` for all pre-existing rows after upgrade via `test_migrations.py::test_mfa_enabled_default_false_for_existing_users`
- [ ] Run `ruff check alembic/versions/0NNN_add_mfa.py` — zero findings

### 15.14 Test generation
- [ ] Create `tests/test_mfa.py` with all 30 tests
- [ ] Use `pyotp` to generate live TOTPs in tests
- [ ] Verify file parses
- [ ] Assert overall line coverage for `app/core/mfa/` is ≥ 90% via `pytest --cov=app.core.mfa --cov-fail-under=90`
- [ ] Assert recovery code single-use scenario is covered in `test_mfa.py::test_recovery_code_used_only_once`
- [ ] Run `ruff check tests/test_mfa.py` — zero findings

### 15.15 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created tables on failure
- [ ] Assert mid-run failure leaves no partial files on disk via `test_atomicity.py::test_rollback_removes_partial_files`
- [ ] Assert returned dict lists every rolled-back file path via `test_atomicity.py::test_error_response_lists_rolled_back_files`
- [ ] Run `mypy app/core/mfa/` — zero errors after rollback path changes

### 15.16 Documentation
- [ ] Append MFA section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Assert `manifest.yaml` entry for `add_mfa` contains `inputs`, `outputs`, and `idempotent: true` fields via `test_manifest.py::test_mfa_tool_manifest_schema`
- [ ] Assert `SKILL.md` tools table row for TOOL-013 links to this spec file via `test_skill_md.py::test_tool_013_row_exists_with_spec_link`
- [ ] Run `ruff check mcp_server.py` — zero new findings after the update

### 15.17 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure verify p99
- [ ] Assert every EC-01..EC-15 from Section 13 has a matching test in `tests/test_mfa_edge_cases.py` that reproduces the Expected column exactly

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/mfa.py",
    "app/core/mfa/__init__.py",
    "app/core/mfa/crypto.py",
    "app/core/mfa/totp.py",
    "app/core/mfa/recovery.py",
    "app/core/mfa/rate_limit.py",
    "app/crud/mfa.py",
    "app/schemas/mfa.py",
    "app/api/routes/mfa.py",
    "alembic/versions/0013_add_mfa.py",
    "tests/test_mfa.py"
  ],
  "files_modified": [
    "app/api/routes/login.py",
    "app/api/main.py",
    "app/core/config.py",
    "app/crud/user.py",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 4076,
    "files_changed": 16,
    "lines_added": 1023,
    "lines_removed": 6,
    "recovery_codes_count": 10,
    "totp_window": 1,
    "max_attempts_per_15min": 5
  },
  "next_steps": [
    "Set MFA_FERNET_KEY in your .env (`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`)",
    "Run: alembic upgrade head",
    "Run: pytest tests/test_mfa.py -v",
    "Test manually: enroll → scan QR with Google Authenticator → /verify-enrollment with the 6-digit code → log out → log in → /challenge with new code",
    "If add_oauth2_provider is installed, manually patch OAuth callback to also enforce MFA when user.mfa_enabled is true (the auto-patch only covers password login)"
  ],
  "warnings": [
    "MFA_FERNET_KEY is REQUIRED. App refuses to start without it.",
    "OAuth login flow is NOT auto-patched for MFA. If your users authenticate via OAuth, manually add the MFA check in the OAuth callback.",
    "API key auth bypasses MFA by design. Document this trade-off if you require MFA for all human access."
  ],
  "notes": [
    "MFA installed with TOTP, 10 recovery codes, ±30s window, 5 attempts / 15 min rate limit.",
    "Two new tables: mfa_devices, mfa_recovery_codes.",
    "users.mfa_enabled column added.",
    "Login route patched to return pending_token when mfa_enabled.",
    "Existing tests still pass: 60/60."
  ]
}
```
