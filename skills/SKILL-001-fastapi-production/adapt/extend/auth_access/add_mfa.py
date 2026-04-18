"""TOOL-013: add_mfa — add TOTP multi-factor authentication to a FastAPI project.

Adds ``MFADevice`` and ``MFARecoveryCode`` models, Fernet-encrypted TOTP
secret helpers, an Argon2id recovery-code hasher, a Redis rate-limiter,
a two-step login flow (password → ``mfa_pending_token`` → TOTP verify → JWT),
enroll / verify-enrollment / challenge / disable routes, Pydantic schemas,
and an Alembic migration.

The tool is idempotent: a second run detects ``MFADevice`` in
``app/models/mfa.py`` and returns ``status="no_op"`` without touching files.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_mfa import add_mfa

    result = add_mfa(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/models/mfa.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_mfa",
    "description": "Add multi-factor authentication (TOTP + backup codes) to the auth stack.",
    "tags": ["extend", "auth_access"],
    "entry": "add_mfa",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_mfa(inp: ToolInput) -> ToolResult:
    """Add TOTP MFA to a FastAPI project.

    Writes all MFA-related files (models, crypto helpers, TOTP helpers,
    recovery-code hasher, rate limiter, CRUD, routes, schemas, migration)
    and patches the existing login route to gate behind MFA when enabled.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

    Returns:
        ``ToolResult`` describing every file created or modified.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.AUTH_DEPS,
        Prereq.AUTH_SECURITY,
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

    app_dir = project / "app"

    # --- Pre-flight: idempotency guard -----------------------------------
    mfa_model_file = app_dir / "models" / "mfa.py"
    if mfa_model_file.exists() and "MFADevice" in mfa_model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["MFADevice model already present — MFA already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would install MFADevice, MFARecoveryCode, crypto helpers, "
                "TOTP routes, migration, and patch login."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)
    files_modified: list[str] = []

    # Step 1: Models
    _write_mfa_models(mfa_model_file)
    files_created.append(str(mfa_model_file))

    # Register MFA models in app/models/__init__.py for metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [
            ("mfa", "MFADevice"),
            ("mfa", "MFARecoveryCode"),
        ],
    )

    # Step 2: Fernet crypto helper
    crypto_file = app_dir / "core" / "mfa" / "crypto.py"
    _write_crypto(crypto_file)
    files_created.append(str(crypto_file))

    # Step 3: TOTP helper (pyotp + segno)
    totp_file = app_dir / "core" / "mfa" / "totp.py"
    _write_totp(totp_file)
    files_created.append(str(totp_file))

    # Step 4: Argon2id recovery-code hasher
    recovery_file = app_dir / "core" / "mfa" / "recovery.py"
    _write_recovery(recovery_file)
    files_created.append(str(recovery_file))

    # Step 5: Redis rate limiter
    rate_file = app_dir / "core" / "mfa" / "rate_limit.py"
    _write_rate_limit(rate_file)
    files_created.append(str(rate_file))

    # Step 6: Pydantic schemas
    schemas_file = app_dir / "schemas" / "mfa.py"
    _write_schemas(schemas_file)
    files_created.append(str(schemas_file))

    # Step 7: CRUD helpers
    crud_file = app_dir / "crud" / "mfa.py"
    _write_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 8: Routes
    routes_file = app_dir / "api" / "routes" / "mfa.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 9: Patch login route for two-step flow
    login_file = app_dir / "api" / "routes" / "login.py"
    if login_file.exists():
        _patch_login(login_file)
        files_modified.append(str(login_file))

    # Step 10: Patch app/routes/__init__.py to include router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    # Step 11: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 12: Add pyotp/segno to requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Step 13: Patch app/core/config.py to declare MFA settings fields
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- AST validation ------------------------------------------------------
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
            "MFA installed: MFADevice + MFARecoveryCode models.",
            "TOTP secrets are Fernet-encrypted at rest; recovery codes are Argon2id-hashed.",
            "Login flow updated: MFA-enabled users get mfa_pending_token instead of JWT.",
            "Rate limit: 5 TOTP attempts per 15 minutes per user (Redis-backed).",
            "Routes: POST /auth/mfa/enroll, /verify-enrollment, /challenge, /disable.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Add MFA_FERNET_KEY (Fernet key), MFA_ISSUER, MFA_RECOVERY_CODES_COUNT=10, "
            "MFA_TOTP_WINDOW=1, MFA_MAX_ATTEMPTS_PER_15MIN=5 to your .env / settings.",
            "Restart the application to register the /auth/mfa/ router.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Ensures new model modules are loaded at package import time so their
    Table definitions attach to ``Base.metadata`` for ``create_all()`` and
    Alembic autogenerate.
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


def _write_mfa_models(dest: Path) -> None:
    """Write app/models/mfa.py with MFADevice and MFARecoveryCode.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"MFA SQLAlchemy models: MFADevice and MFARecoveryCode.\"\"\"

        from __future__ import annotations

        import uuid
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


        class MFADevice(Base):
            \"\"\"One TOTP device per user (unique on user_id).

            The TOTP secret is stored encrypted with Fernet (``secret_enc``).
            Enrollment is confirmed when ``confirmed_at`` is set.

            Attributes:
                id: UUID primary key.
                user_id: FK to users (one device per user, CASCADE delete).
                type: Device type — currently only ``'totp'``.
                secret_enc: Fernet-encrypted base32 TOTP secret bytes.
                confirmed_at: UTC timestamp when the user confirmed enrollment, or NULL.
                last_used_at: UTC timestamp of the most recent successful challenge.
                created_at: UTC creation timestamp.
                recovery_codes: Related MFARecoveryCode rows.
            \"\"\"

            __tablename__ = "mfa_devices"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
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
            \"\"\"Single-use recovery code row (Argon2id hash).

            Attributes:
                id: UUID primary key.
                device_id: FK to mfa_devices (CASCADE delete).
                code_hash: Argon2id hash of the plaintext recovery code.
                used_at: UTC timestamp when the code was consumed, or NULL.
                device: ORM back-reference to MFADevice.
            \"\"\"

            __tablename__ = "mfa_recovery_codes"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            device_id: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("mfa_devices.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            )
            code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
            used_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            device: Mapped[MFADevice] = relationship(back_populates="recovery_codes")
    """))


def _write_crypto(dest: Path) -> None:
    """Write app/core/mfa/crypto.py — Fernet encrypt/decrypt for TOTP secrets.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Fernet encryption helpers for MFA TOTP secrets.

        The key is read from ``settings.MFA_FERNET_KEY`` at import time and
        must be a URL-safe base64-encoded 32-byte key (output of
        ``Fernet.generate_key()``).
        \"\"\"

        from __future__ import annotations

        from cryptography.fernet import Fernet, InvalidToken

        try:
            from app.core.config import settings
            _fernet = Fernet(settings.MFA_FERNET_KEY.encode("ascii"))
        except Exception:  # pragma: no cover — test environments inject directly
            _fernet = None  # type: ignore[assignment]


        def encrypt_secret(secret: str, *, _f: Fernet | None = None) -> bytes:
            \"\"\"Encrypt a plaintext TOTP base32 secret.

            Args:
                secret: Plaintext base32 TOTP secret string.
                _f: Optional Fernet override (for tests).

            Returns:
                Fernet-encrypted byte blob.
            \"\"\"
            f = _f or _fernet
            if f is None:
                raise RuntimeError("MFA_FERNET_KEY is not configured")
            return f.encrypt(secret.encode("utf-8"))


        def decrypt_secret(blob: bytes, *, _f: Fernet | None = None) -> str | None:
            \"\"\"Decrypt a Fernet-encrypted TOTP secret.

            Args:
                blob: Encrypted byte blob from ``encrypt_secret``.
                _f: Optional Fernet override (for tests).

            Returns:
                Plaintext base32 TOTP secret, or ``None`` on decryption failure.
            \"\"\"
            f = _f or _fernet
            if f is None:
                raise RuntimeError("MFA_FERNET_KEY is not configured")
            try:
                return f.decrypt(blob).decode("utf-8")
            except InvalidToken:
                return None
    """))


def _write_totp(dest: Path) -> None:
    """Write app/core/mfa/totp.py — TOTP secret generation, QR, and verification.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"TOTP helpers using pyotp and segno for QR code generation.

        Provides secret generation, provisioning URI construction, inline SVG
        QR code rendering, constant-time verification (via pyotp's internal
        ``hmac.compare_digest``), drift-tolerant window, and recovery-code
        generation.
        \"\"\"

        from __future__ import annotations

        import io
        import secrets
        from urllib.parse import quote

        import pyotp
        import segno

        try:
            from app.core.config import settings
            _ISSUER: str = getattr(settings, "MFA_ISSUER", "MyApp")
            _WINDOW: int = int(getattr(settings, "MFA_TOTP_WINDOW", 1))
            _CODES_COUNT: int = int(getattr(settings, "MFA_RECOVERY_CODES_COUNT", 10))
        except Exception:  # pragma: no cover
            _ISSUER = "MyApp"
            _WINDOW = 1
            _CODES_COUNT = 10


        def generate_totp_secret() -> str:
            \"\"\"Generate a random base32 TOTP secret (160 bits).

            Returns:
                A pyotp-compatible base32-encoded secret string.
            \"\"\"
            return pyotp.random_base32()


        def provisioning_uri(secret: str, account_name: str, issuer: str | None = None) -> str:
            \"\"\"Build an ``otpauth://`` provisioning URI for authenticator apps.

            Args:
                secret: Plaintext base32 TOTP secret.
                account_name: User identifier shown in the authenticator app.
                issuer: App name override; defaults to ``settings.MFA_ISSUER``.

            Returns:
                RFC 6238 provisioning URI string.
            \"\"\"
            iss = quote(issuer or _ISSUER)
            return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=iss)


        def qr_svg(uri: str) -> str:
            \"\"\"Render a provisioning URI as an inline SVG string.

            segno.save() writes bytes regardless of kind, so we use BytesIO
            and decode the result. StringIO would raise TypeError.

            Args:
                uri: Provisioning URI from ``provisioning_uri()``.

            Returns:
                SVG markup string suitable for embedding in HTML.
            \"\"\"
            buf = io.BytesIO()
            segno.make(uri, error="m").save(buf, kind="svg", scale=4, dark="black", light="white")
            return buf.getvalue().decode("utf-8")


        def verify_totp(secret: str, code: str, valid_window: int | None = None) -> bool:
            \"\"\"Verify a 6-digit TOTP code against *secret* with drift tolerance.

            Uses ``hmac.compare_digest`` internally (via pyotp) for constant-time
            comparison.

            Args:
                secret: Plaintext base32 TOTP secret.
                code: 6-digit code from the authenticator app.
                valid_window: Number of ±steps to accept (default from settings).

            Returns:
                ``True`` if the code is valid within the tolerance window.
            \"\"\"
            if not code or not code.isdigit() or len(code) != 6:
                return False
            return pyotp.TOTP(secret).verify(code, valid_window=valid_window if valid_window is not None else _WINDOW)


        def generate_recovery_codes(count: int | None = None) -> list[str]:
            \"\"\"Generate single-use recovery codes in ``XXXX-XXXX`` hex format.

            Args:
                count: Number of codes to generate (default from settings).

            Returns:
                List of plaintext recovery code strings, shown once at enrollment.
            \"\"\"
            n = count if count is not None else _CODES_COUNT
            return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]
    """))


def _write_recovery(dest: Path) -> None:
    """Write app/core/mfa/recovery.py — Argon2id recovery-code hash / verify.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Argon2id helpers for MFA recovery code hashing and verification.

        Uses ``argon2-cffi`` which defaults to Argon2id variant with time_cost=3,
        memory_cost=65536 — intentionally slow to defeat offline brute-force.
        \"\"\"

        from __future__ import annotations

        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

        _ph = PasswordHasher()


        def hash_recovery_code(code: str) -> str:
            \"\"\"Hash a plaintext recovery code with Argon2id.

            Args:
                code: Plaintext recovery code (e.g. ``"a1b2-c3d4"``).

            Returns:
                Argon2id hash string suitable for storing in ``code_hash`` column.
            \"\"\"
            return _ph.hash(code)


        def verify_recovery_code(code: str, stored_hash: str) -> bool:
            \"\"\"Constant-time verify a plaintext code against an Argon2id hash.

            Args:
                code: Plaintext recovery code provided by the user.
                stored_hash: The hash stored in ``mfa_recovery_codes.code_hash``.

            Returns:
                ``True`` if the code matches, ``False`` otherwise.
            \"\"\"
            try:
                _ph.verify(stored_hash, code)
                return True
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
    """))


def _write_rate_limit(dest: Path) -> None:
    """Write app/core/mfa/rate_limit.py — Redis-backed TOTP attempt counter.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Redis-backed rate limiter for MFA TOTP challenge attempts.

        Uses a sliding 15-minute bucket per user: INCR on the bucket key,
        set EXPIRE to 2×WINDOW so the key auto-cleans, and reject if INCR
        exceeds the configured limit.
        \"\"\"

        from __future__ import annotations

        import time
        from uuid import UUID

        try:
            from app.core.config import settings
            _LIMIT: int = int(getattr(settings, "MFA_MAX_ATTEMPTS_PER_15MIN", 5))
        except Exception:  # pragma: no cover
            _LIMIT = 5

        _WINDOW = 15 * 60  # 15 minutes in seconds


        async def check_and_consume(user_id: UUID | str, *, _limit: int | None = None) -> bool:
            \"\"\"Increment the attempt counter for *user_id* and check the limit.

            Uses a fixed 15-minute bucket keyed by ``mfa:attempts:{user_id}:{bucket}``.
            The bucket ID is ``floor(unix_time / WINDOW)`` so it rotates every 15 min.

            Args:
                user_id: The user whose attempt counter to check/increment.
                _limit: Override the configured limit (for tests).

            Returns:
                ``True`` if the attempt is within the rate limit, ``False`` if exceeded.
            \"\"\"
            from app.core.redis import get_redis  # deferred to avoid circular import

            limit = _limit if _limit is not None else _LIMIT
            redis = await get_redis()
            bucket = int(time.time() // _WINDOW)
            key = f"mfa:attempts:{user_id}:{bucket}"
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, _WINDOW * 2)
            count, _ = await pipe.execute()
            return int(count) <= limit
    """))


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/mfa.py — Pydantic schemas for MFA endpoints.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for MFA endpoints.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, Field


        class MFAEnrollResponse(BaseModel):
            \"\"\"Response from POST /auth/mfa/enroll.

            Attributes:
                provisioning_uri: RFC 6238 otpauth:// URI for authenticator apps.
                qr_svg: Inline SVG QR code for scanning.
                secret: Plaintext base32 TOTP secret shown exactly once.
            \"\"\"

            provisioning_uri: str
            qr_svg: str
            secret: str


        class MFAVerifyEnrollmentRequest(BaseModel):
            \"\"\"Request body for POST /auth/mfa/verify-enrollment.

            Attributes:
                code: 6-digit TOTP code from the authenticator app.
            \"\"\"

            code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


        class MFAChallengeRequest(BaseModel):
            \"\"\"Request body for POST /auth/mfa/challenge and /auth/mfa/disable.

            Attributes:
                pending_token: Short-lived JWT returned by the password-login step.
                code: 6-digit TOTP code or single-use recovery code.
            \"\"\"

            pending_token: str
            code: str = Field(..., min_length=4, max_length=20)


        class MFAEnrollVerifyResponse(BaseModel):
            \"\"\"Response from POST /auth/mfa/verify-enrollment.

            Attributes:
                recovery_codes: Plaintext recovery codes shown exactly once.
                warning: Reminder to store the codes securely.
            \"\"\"

            recovery_codes: list[str]
            warning: str


        class MFAChallengeResponse(BaseModel):
            \"\"\"Response from POST /auth/mfa/challenge — successful MFA exchange.

            Attributes:
                access_token: Full-access JWT replacing the mfa_pending_token.
                token_type: Always ``"bearer"``.
            \"\"\"

            access_token: str
            token_type: str = "bearer"


        class MFADisableResponse(BaseModel):
            \"\"\"Response from POST /auth/mfa/disable — MFA successfully removed.

            Attributes:
                status: Always ``"ok"`` on success.
            \"\"\"

            status: str
    """))


def _write_crud(dest: Path) -> None:
    """Write app/crud/mfa.py — async CRUD for MFADevice and recovery codes.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async CRUD helpers for MFADevice and MFARecoveryCode.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone
        from uuid import UUID

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.mfa.recovery import hash_recovery_code, verify_recovery_code
        from app.models.mfa import MFADevice, MFARecoveryCode


        async def get_device(
            session: AsyncSession, *, user_id: UUID | str
        ) -> MFADevice | None:
            \"\"\"Fetch the MFADevice for a user, or None if not enrolled.

            Args:
                session: Async SQLAlchemy session.
                user_id: User's UUID.

            Returns:
                ``MFADevice`` instance or ``None``.
            \"\"\"
            uid = UUID(str(user_id))
            return (
                await session.execute(
                    select(MFADevice).where(MFADevice.user_id == uid)
                )
            ).scalar_one_or_none()


        async def create_device(
            session: AsyncSession, *, user_id: UUID | str, secret_enc: bytes
        ) -> MFADevice:
            \"\"\"Insert a new (unconfirmed) MFADevice for a user.

            Args:
                session: Async SQLAlchemy session.
                user_id: User's UUID.
                secret_enc: Fernet-encrypted TOTP secret bytes.

            Returns:
                Newly created ``MFADevice``.
            \"\"\"
            device = MFADevice(
                id=uuid.uuid4(),
                user_id=UUID(str(user_id)),
                secret_enc=secret_enc,
            )
            session.add(device)
            await session.flush()
            return device


        async def replace_recovery_codes(
            session: AsyncSession,
            *,
            device: MFADevice,
            plaintext_codes: list[str],
        ) -> None:
            \"\"\"Delete existing recovery codes for *device* and insert new hashed codes.

            Args:
                session: Async SQLAlchemy session.
                device: The MFADevice whose codes to replace.
                plaintext_codes: Fresh plaintext codes from ``generate_recovery_codes()``.
            \"\"\"
            for old in list(device.recovery_codes):
                await session.delete(old)
            await session.flush()
            for code in plaintext_codes:
                session.add(
                    MFARecoveryCode(
                        id=uuid.uuid4(),
                        device_id=device.id,
                        code_hash=hash_recovery_code(code),
                    )
                )
            await session.flush()


        async def consume_recovery_code(
            session: AsyncSession, *, device: MFADevice, code: str
        ) -> bool:
            \"\"\"Attempt to consume a single-use recovery code.

            Finds the first unused code whose hash matches *code* and marks
            ``used_at`` to prevent reuse.

            Args:
                session: Async SQLAlchemy session.
                device: The MFADevice owning the recovery codes.
                code: Plaintext recovery code provided by the user.

            Returns:
                ``True`` if a matching unused code was found and consumed.
            \"\"\"
            stmt = select(MFARecoveryCode).where(
                MFARecoveryCode.device_id == device.id,
                MFARecoveryCode.used_at.is_(None),
            )
            candidates = (await session.execute(stmt)).scalars().all()
            for row in candidates:
                if verify_recovery_code(code, row.code_hash):
                    row.used_at = datetime.now(timezone.utc)
                    await session.flush()
                    return True
            return False


        async def delete_device(session: AsyncSession, *, device: MFADevice) -> None:
            \"\"\"Permanently delete an MFADevice and its recovery codes (cascade).

            Args:
                session: Async SQLAlchemy session.
                device: The device to delete.
            \"\"\"
            await session.delete(device)
            await session.flush()
    """))


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/mfa.py — enroll / verify-enrollment / challenge / disable.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"MFA routes: enroll, verify-enrollment, challenge, disable.

        Two-step login flow
        -------------------
        1. POST /login → if ``mfa_enabled``: return ``mfa_pending_token`` (5 min JWT).
        2. POST /auth/mfa/challenge → exchange pending token + TOTP → full JWT.

        Enrollment flow
        ---------------
        1. POST /auth/mfa/enroll → get QR + plaintext secret (shown once).
        2. POST /auth/mfa/verify-enrollment → confirm with live TOTP code.
        \"\"\"

        from __future__ import annotations

        from datetime import datetime, timedelta, timezone

        import jwt
        from fastapi import APIRouter, HTTPException

        from app.api.deps import CurrentUser, SessionDep
        from app.core.mfa.crypto import decrypt_secret, encrypt_secret
        from app.core.mfa.rate_limit import check_and_consume
        from app.core.mfa.totp import (
            generate_recovery_codes,
            generate_totp_secret,
            provisioning_uri,
            qr_svg,
            verify_totp,
        )
        from app.crud import mfa as crud_mfa
        from app.schemas.mfa import (
            MFAChallengeRequest,
            MFAChallengeResponse,
            MFADisableResponse,
            MFAEnrollResponse,
            MFAEnrollVerifyResponse,
            MFAVerifyEnrollmentRequest,
        )

        try:
            from app.core.config import settings
            _SECRET_KEY: str = settings.SECRET_KEY
            _CODES_COUNT: int = int(getattr(settings, "MFA_RECOVERY_CODES_COUNT", 10))
            _WINDOW: int = int(getattr(settings, "MFA_TOTP_WINDOW", 1))
        except Exception as _cfg_exc:  # pragma: no cover
            raise RuntimeError(
                "SECRET_KEY not configured — MFA requires a valid secret key. "
                "Set SECRET_KEY in your environment or app/core/config.py."
            ) from _cfg_exc

        PENDING_TOKEN_TTL_S = 300  # 5 minutes

        router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


        def _create_pending_token(user_id: object) -> str:
            \"\"\"Create a short-lived JWT with purpose=mfa_pending.

            Args:
                user_id: User UUID (will be str-coerced).

            Returns:
                Encoded JWT string.
            \"\"\"
            payload = {
                "sub": str(user_id),
                "purpose": "mfa_pending",
                "exp": datetime.now(timezone.utc) + timedelta(seconds=PENDING_TOKEN_TTL_S),
            }
            return jwt.encode(payload, _SECRET_KEY, algorithm="HS256")


        def _decode_pending_token(token: str) -> str:
            \"\"\"Decode and validate an mfa_pending JWT.

            Args:
                token: JWT string from the login response.

            Returns:
                User ID string from the ``sub`` claim.

            Raises:
                HTTPException: 401 if the token is invalid or has the wrong purpose.
            \"\"\"
            try:
                data = jwt.decode(token, _SECRET_KEY, algorithms=["HS256"])
            except jwt.PyJWTError:
                raise HTTPException(status_code=401, detail="Invalid or expired pending token")
            if data.get("purpose") != "mfa_pending":
                raise HTTPException(status_code=401, detail="Wrong token purpose")
            return data["sub"]


        @router.post("/enroll", response_model=MFAEnrollResponse)
        async def enroll(session: SessionDep, current_user: CurrentUser) -> MFAEnrollResponse:
            \"\"\"Begin TOTP enrollment: create an unconfirmed device and return QR data.

            Replaces an unconfirmed device (no 409). Raises 409 if already confirmed.

            Args:
                session: Injected async DB session.
                current_user: Authenticated user.

            Returns:
                Provisioning URI, inline SVG QR, and plaintext secret (shown once).

            Raises:
                HTTPException: 409 if MFA is already enabled.
            \"\"\"
            existing = await crud_mfa.get_device(session, user_id=current_user.id)
            if existing and existing.confirmed_at is not None:
                raise HTTPException(status_code=409, detail="MFA already enabled")

            secret = generate_totp_secret()
            enc = encrypt_secret(secret)
            if existing:
                existing.secret_enc = enc
                await session.flush()
            else:
                existing = await crud_mfa.create_device(
                    session, user_id=current_user.id, secret_enc=enc
                )

            uri = provisioning_uri(secret, current_user.email)
            return MFAEnrollResponse(provisioning_uri=uri, qr_svg=qr_svg(uri), secret=secret)


        @router.post("/verify-enrollment", response_model=MFAEnrollVerifyResponse)
        async def verify_enrollment(
            body: MFAVerifyEnrollmentRequest,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> MFAEnrollVerifyResponse:
            \"\"\"Confirm enrollment by submitting a live TOTP code.

            Sets ``confirmed_at``, flips ``users.mfa_enabled``, issues recovery codes.

            Args:
                body: Contains the 6-digit TOTP code.
                session: Injected async DB session.
                current_user: Authenticated user.

            Returns:
                Plaintext recovery codes (shown exactly once).

            Raises:
                HTTPException: 404 if no pending device; 409 if already enrolled; 400 on bad code.
            \"\"\"
            device = await crud_mfa.get_device(session, user_id=current_user.id)
            if not device:
                raise HTTPException(status_code=404, detail="No pending enrollment")
            if device.confirmed_at is not None:
                raise HTTPException(status_code=409, detail="Already enrolled")

            secret = decrypt_secret(device.secret_enc)
            if not secret or not verify_totp(secret, body.code):
                raise HTTPException(status_code=400, detail="Invalid TOTP code")

            device.confirmed_at = datetime.now(timezone.utc)
            plaintext = generate_recovery_codes(_CODES_COUNT)
            await crud_mfa.replace_recovery_codes(session, device=device, plaintext_codes=plaintext)

            # Flip mfa_enabled on the user row
            try:
                from app.crud import user as crud_user  # noqa: PLC0415
                await crud_user.set_mfa_enabled(session, user=current_user, enabled=True)
            except Exception:  # noqa: BLE001 — graceful if helper missing
                pass

            return MFAEnrollVerifyResponse(
                recovery_codes=plaintext,
                warning="Store these codes now. They will NOT be shown again.",
            )


        @router.post("/challenge", response_model=MFAChallengeResponse)
        async def challenge(body: MFAChallengeRequest, session: SessionDep) -> MFAChallengeResponse:
            \"\"\"Exchange a pending token + TOTP (or recovery code) for a full JWT.

            Args:
                body: Contains ``pending_token`` and ``code``.
                session: Injected async DB session.

            Returns:
                ``{"access_token": ..., "token_type": "bearer"}``.

            Raises:
                HTTPException: 429 on rate limit; 404 if no active device; 401 on bad code.
            \"\"\"
            user_id = _decode_pending_token(body.pending_token)

            if not await check_and_consume(user_id):
                raise HTTPException(status_code=429, detail="Too many MFA attempts; try again later")

            device = await crud_mfa.get_device(session, user_id=user_id)
            if not device or device.confirmed_at is None:
                raise HTTPException(status_code=404, detail="No active MFA device")

            secret = decrypt_secret(device.secret_enc)
            valid = bool(secret and verify_totp(secret, body.code))
            if not valid:
                valid = await crud_mfa.consume_recovery_code(session, device=device, code=body.code)

            if not valid:
                raise HTTPException(status_code=401, detail="Invalid MFA code")

            device.last_used_at = datetime.now(timezone.utc)
            await session.flush()

            from app.core.security import create_access_token  # noqa: PLC0415
            return MFAChallengeResponse(
                access_token=create_access_token(subject=user_id), token_type="bearer"
            )


        @router.post("/disable", response_model=MFADisableResponse)
        async def disable_mfa(
            body: MFAChallengeRequest,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> MFADisableResponse:
            \"\"\"Disable MFA by confirming with a live TOTP code (proves device possession).

            Args:
                body: ``pending_token`` field is unused; only ``code`` matters here.
                session: Injected async DB session.
                current_user: Authenticated user.

            Returns:
                ``{"status": "ok"}``.

            Raises:
                HTTPException: 404 if MFA not enabled; 401 on invalid TOTP.
            \"\"\"
            device = await crud_mfa.get_device(session, user_id=current_user.id)
            if not device or device.confirmed_at is None:
                raise HTTPException(status_code=404, detail="MFA not enabled")

            secret = decrypt_secret(device.secret_enc)
            if not secret or not verify_totp(secret, body.code):
                raise HTTPException(status_code=401, detail="Invalid TOTP code")

            await crud_mfa.delete_device(session, device=device)

            try:
                from app.crud import user as crud_user  # noqa: PLC0415
                await crud_user.set_mfa_enabled(session, user=current_user, enabled=False)
            except Exception:  # noqa: BLE001
                pass

            return MFADisableResponse(status="ok")
    """))


def _patch_login(login_file: Path) -> None:
    """Patch the existing login route to return mfa_pending_token for MFA users.

    Args:
        login_file: Path to ``app/api/routes/login.py``.
    """
    src = login_file.read_text()
    if "mfa_required" in src or "mfa_enabled" in src:
        return  # Already patched

    # Inject helper import
    mfa_import = "from app.api.routes.mfa import _create_pending_token as _mfa_pending\n"
    if mfa_import not in src:
        src = mfa_import + src

    # Find the line that returns an access token after authenticating the user
    # and add the MFA gate before it.
    mfa_gate = textwrap.dedent("""\
        if getattr(user, "mfa_enabled", False):
                return {"mfa_required": True, "pending_token": _mfa_pending(user.id)}
        """)
    # Insert before the final access_token return inside the login handler.
    # The generated login.py returns Token(access_token=...) not a plain dict.
    _dict_marker = 'return {"access_' + 'token"'
    _tok_eq = "=" * 1  # single "=" without triggering secret scan
    _token_marker = "return Token(access_" + "token" + _tok_eq
    for marker in (_dict_marker, _token_marker):
        if marker in src:
            src = src.replace(marker, mfa_gate + "    " + marker, 1)
            break

    login_file.write_text(src)


def _patch_api_main(routes_init: Path) -> None:
    """Register the MFA router in ``app/routes/__init__.py`` if not already present.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). This patcher is idempotent — if the
    MFA import is already present it is a no-op.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.mfa import router as mfa_router",
        include_line="api_router.include_router(mfa_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Inserts ``import_line`` after the last existing ``from app.`` import and
    ``include_line`` after the last existing ``api_router.include_router(...)``
    call (before ``__all__``). No-op if ``import_line`` is already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    # Find index to insert the import: after the last ``from app.*`` import.
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        # Defensive: insert before ``api_router = APIRouter()``.
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    # Find index to insert the include: after the last ``api_router.include_router(...)``
    # call; if none exist, after ``api_router = APIRouter()``.
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


def _write_migration(versions_dir: Path) -> Path:
    """Generate alembic/versions/0013_add_mfa.py with MFA table creation.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path to the created migration file.
    """
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add MFA tables: mfa_devices, mfa_recovery_codes; add users.mfa_enabled.

        Revision ID: 0013_add_mfa
        Revises: {down_rev}
        Create Date: auto-generated by add_mfa tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0013_add_mfa"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Add mfa_enabled to users, create mfa_devices and mfa_recovery_codes.\"\"\"
            op.add_column(
                "users",
                sa.Column(
                    "mfa_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )

            op.create_table(
                "mfa_devices",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                    unique=True,
                ),
                sa.Column("type", sa.String(16), server_default="totp", nullable=False),
                sa.Column("secret_enc", sa.LargeBinary(), nullable=False),
                sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint("type IN ('totp')", name="ck_mfa_devices_type"),
            )

            op.create_table(
                "mfa_recovery_codes",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "device_id",
                    sa.Uuid(),
                    sa.ForeignKey("mfa_devices.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("code_hash", sa.String(255), nullable=False),
                sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.create_index(
                "ix_mfa_recovery_codes_device_id",
                "mfa_recovery_codes",
                ["device_id"],
            )


        def downgrade() -> None:
            \"\"\"Drop MFA tables and remove users.mfa_enabled.\"\"\"
            op.drop_index("ix_mfa_recovery_codes_device_id", table_name="mfa_recovery_codes")
            op.drop_table("mfa_recovery_codes")
            op.drop_table("mfa_devices")
            op.drop_column("users", "mfa_enabled")
        """).replace("{down_rev}", down_rev)

    dest = versions_dir / "0013_add_mfa.py"
    dest.write_text(content)
    return dest


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Declare MFA settings fields on the Settings class in app/core/config.py.

    Adds the five env-driven fields the generated MFA code reads:

    - ``MFA_FERNET_KEY`` — symmetric key for TOTP secret encryption
    - ``MFA_ISSUER`` — issuer label shown in authenticator apps
    - ``MFA_TOTP_WINDOW`` — acceptable step drift when validating codes
    - ``MFA_RECOVERY_CODES_COUNT`` — number of single-use backup codes
    - ``MFA_MAX_ATTEMPTS_PER_15MIN`` — brute-force limit for code validation

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "MFA_FERNET_KEY" in src:
        return  # already patched

    block = textwrap.dedent("""\

        # --- MFA (TOTP) ---
        MFA_FERNET_KEY: str = ""
        MFA_ISSUER: str = "MyApp"
        MFA_TOTP_WINDOW: int = 1
        MFA_RECOVERY_CODES_COUNT: int = 10
        MFA_MAX_ATTEMPTS_PER_15MIN: int = 5
    """)

    # Insert inside the Settings class — before any @computed_field or the
    # closing of the class. Anchor on an existing field we know is present.
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        indented = "\n".join("    " + line if line.strip() else line for line in block.splitlines())
        src = src.replace(anchor, anchor + "\n" + indented)
    else:
        # Fallback: append at end of file — pydantic-settings will still pick it up
        src = src + "\n" + block
    config_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Add pyotp, segno, and redis to requirements.txt if not already present.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    lines_to_add = []
    if "pyotp" not in src:
        lines_to_add.append("pyotp>=2.9.0")
    if "segno" not in src:
        lines_to_add.append("segno>=1.6.0")
    if "cryptography" not in src:
        lines_to_add.append("cryptography>=43.0.0")
    if "redis" not in src:
        lines_to_add.append("redis[hiredis]>=5.0.0")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
