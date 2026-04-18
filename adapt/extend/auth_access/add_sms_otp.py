"""TOOL-076: add_sms_otp — SMS OTP authentication via Twilio/Vonage.

Generates all files required for SMS-based one-time password authentication:
an ``OtpCode`` SQLAlchemy model (phone, code, expires_at, verified),
an ``SmsOtpService`` class with lazy Twilio import, Pydantic schemas, and
two route handlers:
  POST /auth/sms/send
  POST /auth/sms/verify

Rate limiting: maximum 5 OTP requests per phone per hour enforced via the
OtpCode table (no Redis required).  Codes expire after OTP_EXPIRY_SECONDS.

The tool is idempotent: a second run detects the ``OtpCode`` model fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_sms_otp import add_sms_otp

    result = add_sms_otp(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/models/otp_code.py, ...]
    print(result.next_steps)     # ["pip install twilio", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_sms_otp",
    "description": (
        "Add SMS OTP authentication via Twilio/Vonage with rate limiting to a FastAPI project."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_sms_otp",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_sms_otp(inp: ToolInput) -> ToolResult:
    """Add SMS OTP authentication to a FastAPI project.

    Writes all necessary files for SMS-based OTP login: OtpCode model,
    SmsOtpService with lazy Twilio import, schemas, routes with rate
    limiting (5/hour per phone), and Alembic migration.

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
    model_file = app_dir / "models" / "otp_code.py"
    if model_file.exists() and "OtpCode" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["OtpCode model already present — SMS OTP auth already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) ----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create SMS OTP files (Twilio/Vonage).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: OtpCode model
    _write_model(model_file)
    files_created.append(str(model_file))

    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("otp_code", "OtpCode")],
    )

    # Step 2: SmsOtpService with lazy twilio
    sms_otp_file = app_dir / "auth" / "sms_otp.py"
    _write_sms_otp_service(sms_otp_file)
    files_created.append(str(sms_otp_file))

    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    # Step 3: Schemas
    schema_file = app_dir / "schemas" / "otp.py"
    _write_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 4: Routes
    routes_file = app_dir / "api" / "routes" / "sms_auth.py"
    _write_routes(routes_file)
    files_created.append(str(routes_file))

    # Step 5: Register router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 6: Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration = _write_migration(versions_dir)
        files_created.append(str(migration))

    # Step 7: Patch config
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
            "SMS OTP via Twilio (default) or Vonage (SMS_PROVIDER=vonage).",
            "twilio SDK imported lazily inside send_sms — not required at boot.",
            "Rate limit: max 5 OTPs per phone per hour (DB-enforced, no Redis).",
            "OTP codes expire after OTP_EXPIRY_SECONDS (default: 300).",
            "OTP_LENGTH configures code digit count (default: 6).",
            "Phone numbers stored in E.164 format.",
        ],
        next_steps=[
            "pip install twilio  # or vonage",
            "Add SMS_PROVIDER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
            "TWILIO_FROM_NUMBER, OTP_LENGTH, OTP_EXPIRY_SECONDS to settings.",
            "alembic upgrade head",
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
    """Inject SMS OTP config fields into Settings class idempotently.

    Args:
        config_file: Path to app/core/config.py.
    """
    content = config_file.read_text()
    if "TWILIO_ACCOUNT_SID" in content:
        return
    # Fields must be 4-space indented to sit inside the Settings class body
    fields = (
        "\n"
        "    # SMS OTP (TOOL-076)\n"
        '    SMS_PROVIDER: str = "twilio"\n'
        '    TWILIO_ACCOUNT_SID: str = ""\n'
        '    TWILIO_AUTH_TOKEN: str = ""\n'
        '    TWILIO_FROM_NUMBER: str = ""\n'
        "    OTP_LENGTH: int = 6\n"
        "    OTP_EXPIRY_SECONDS: int = 300\n"
        "    OTP_RATE_LIMIT_MAX: int = 5\n"
        "    OTP_RATE_LIMIT_WINDOW_SECONDS: int = 3600\n"
    )
    if "settings = Settings()" in content:
        content = content.replace("settings = Settings()", fields + "\nsettings = Settings()")
    else:
        content += fields
    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register sms_auth router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Path to app/routes/__init__.py.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.sms_auth import router as sms_auth_router"
    include_line = "api_router.include_router(sms_auth_router)"
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
    """Write app/models/otp_code.py with the OtpCode SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for SMS one-time password codes.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import Boolean, DateTime, String, Uuid, func
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class OtpCode(Base):
            \"\"\"SMS one-time password code record.

            One row per OTP send attempt.  Rows are never deleted; verified
            and expired codes are kept for audit purposes.

            Attributes:
                id: Primary key UUID.
                phone: Phone number in E.164 format.
                code: Plain-text OTP digits (short-lived, not a secret at rest).
                expires_at: UTC timestamp when this code expires.
                verified: True once the user has successfully verified this code.
                created_at: Creation timestamp.
            \"\"\"

            __tablename__ = "otp_codes"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
            code: Mapped[str] = mapped_column(String(10), nullable=False)
            expires_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), nullable=False
            )
            verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
    """)
    dest.write_text(content)


def _write_sms_otp_service(dest: Path) -> None:
    """Write app/auth/sms_otp.py with SmsOtpService and lazy twilio import.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SMS OTP service with lazy Twilio/Vonage import.\"\"\"

        from __future__ import annotations

        import logging
        import os
        import secrets

        logger = logging.getLogger(__name__)

        _DEFAULT_OTP_LENGTH = 6
        _DEFAULT_OTP_EXPIRY = 300
        _RATE_LIMIT_MAX = 5
        _RATE_LIMIT_WINDOW = 3600


        def generate_otp(length: int | None = None) -> str:
            \"\"\"Generate a cryptographically secure numeric OTP code.

            Args:
                length: Number of digits (defaults to OTP_LENGTH env var or 6).

            Returns:
                Zero-padded numeric OTP string of the requested length.
            \"\"\"
            n = length or int(os.environ.get("OTP_LENGTH", str(_DEFAULT_OTP_LENGTH)))
            return str(secrets.randbelow(10 ** n)).zfill(n)


        def verify_otp(stored_code: str, submitted_code: str) -> bool:
            \"\"\"Constant-time comparison of OTP codes.

            Args:
                stored_code: Code stored in the database.
                submitted_code: Code submitted by the user.

            Returns:
                True when the codes match.
            \"\"\"
            return secrets.compare_digest(stored_code.strip(), submitted_code.strip())


        async def send_sms(phone: str, message: str) -> None:
            \"\"\"Send an SMS message via the configured provider.

            Provider is selected via SMS_PROVIDER env var ('twilio' or 'vonage').
            Both SDKs are imported lazily inside this function.

            Args:
                phone: Recipient phone number in E.164 format.
                message: SMS message body.

            Raises:
                RuntimeError: If the provider is unknown or sending fails.
            \"\"\"
            provider = os.environ.get("SMS_PROVIDER", "twilio").lower()
            if provider == "twilio":
                await _send_via_twilio(phone, message)
            elif provider == "vonage":
                await _send_via_vonage(phone, message)
            else:
                raise RuntimeError(f"Unknown SMS_PROVIDER: {provider!r}")


        async def _send_via_twilio(phone: str, message: str) -> None:
            \"\"\"Dispatch an SMS via Twilio REST API.

            Args:
                phone: Recipient in E.164 format.
                message: Message body.

            Raises:
                RuntimeError: If any required env var is missing.
            \"\"\"
            import twilio.rest  # lazy import — not required at app boot

            account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
            from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
            if not account_sid or not auth_token or not from_number:
                raise RuntimeError(
                    "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER must be set"
                )
            client = twilio.rest.Client(account_sid, auth_token)
            client.messages.create(body=message, from_=from_number, to=phone)
            logger.info("SMS sent via Twilio to %s", _mask_phone(phone))


        async def _send_via_vonage(phone: str, message: str) -> None:
            \"\"\"Dispatch an SMS via Vonage REST API.

            Args:
                phone: Recipient in E.164 format.
                message: Message body.

            Raises:
                RuntimeError: If any required env var is missing.
            \"\"\"
            import vonage  # lazy import — not required at app boot

            api_key = os.environ.get("VONAGE_API_KEY", "")
            api_secret = os.environ.get("VONAGE_API_SECRET", "")
            from_name = os.environ.get("VONAGE_FROM_NAME", "App")
            if not api_key or not api_secret:
                raise RuntimeError("VONAGE_API_KEY and VONAGE_API_SECRET must be set")
            client = vonage.Client(key=api_key, secret=api_secret)
            sms = vonage.Sms(client)
            response = sms.send_message(
                {"from": from_name, "to": phone.lstrip("+"), "text": message}
            )
            if response["messages"][0]["status"] != "0":
                raise RuntimeError(
                    f"Vonage error: {response['messages'][0].get('error-text', 'unknown')}"
                )
            logger.info("SMS sent via Vonage to %s", _mask_phone(phone))


        def _mask_phone(phone: str) -> str:
            \"\"\"Return a masked phone number for logging (last 4 digits visible).

            Args:
                phone: Phone number string.

            Returns:
                Masked string like '***1234'.
            \"\"\"
            if len(phone) <= 4:
                return "****"
            return "*" * (len(phone) - 4) + phone[-4:]
    """)
    dest.write_text(content)


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/otp.py with Pydantic schemas for SMS OTP endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for SMS OTP authentication endpoints.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, Field


        class OtpSendRequest(BaseModel):
            \"\"\"Request body for sending an OTP code.

            Attributes:
                phone: Recipient phone number in E.164 format (e.g. +15555550100).
            \"\"\"

            phone: str = Field(..., description="Recipient phone in E.164 format")


        class OtpSendResponse(BaseModel):
            \"\"\"Response after successfully dispatching an OTP.

            Attributes:
                message: Human-readable confirmation.
                expires_in_seconds: Validity window for the code.
            \"\"\"

            message: str
            expires_in_seconds: int


        class OtpVerifyRequest(BaseModel):
            \"\"\"Request body for verifying an OTP code.

            Attributes:
                phone: Phone number that received the OTP.
                code: The OTP code entered by the user.
            \"\"\"

            phone: str = Field(..., description="Phone number that received the OTP")
            code: str = Field(..., description="OTP code entered by the user")


        class OtpVerifyResponse(BaseModel):
            \"\"\"Response after successful OTP verification.

            Attributes:
                verified: Always True on success.
                phone: Phone number that was verified.
            \"\"\"

            verified: bool
            phone: str
    """)
    dest.write_text(content)


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/sms_auth.py with send and verify endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SMS OTP authentication routes: send and verify.\"\"\"

        from __future__ import annotations

        import logging
        import os
        from datetime import datetime, timedelta, timezone

        from fastapi import APIRouter, Depends, HTTPException
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.auth.sms_otp import generate_otp, send_sms, verify_otp
        from app.core.session import get_session
        from app.models.otp_code import OtpCode
        from app.schemas.otp import (
            OtpSendRequest,
            OtpSendResponse,
            OtpVerifyRequest,
            OtpVerifyResponse,
        )

        logger = logging.getLogger(__name__)
        router = APIRouter(prefix="/auth/sms", tags=["sms-otp"])

        _RATE_LIMIT_MAX = 5
        _RATE_LIMIT_WINDOW_SECONDS = 3600


        @router.post("/send", response_model=OtpSendResponse)
        async def send_otp(
            body: OtpSendRequest,
            session: AsyncSession = Depends(get_session),
        ) -> OtpSendResponse:
            \"\"\"Send an OTP code to the given phone number.

            Rate limited to OTP_RATE_LIMIT_MAX requests per OTP_RATE_LIMIT_WINDOW_SECONDS.

            Args:
                body: Phone number in E.164 format.
                session: SQLAlchemy async session dependency.

            Returns:
                ``OtpSendResponse`` with confirmation and expiry seconds.

            Raises:
                HTTPException 429: Rate limit exceeded.
                HTTPException 500: SMS sending failed.
            \"\"\"
            await _enforce_rate_limit(session, body.phone)
            expiry_seconds = int(os.environ.get("OTP_EXPIRY_SECONDS", "300"))
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
            code = generate_otp()
            record = OtpCode(phone=body.phone, code=code, expires_at=expires_at)
            session.add(record)
            await session.flush()
            try:
                await send_sms(body.phone, f"Your verification code is: {code}")
            except Exception as exc:
                logger.error("SMS send failed for %s: %s", body.phone[-4:], exc)
                raise HTTPException(
                    status_code=500, detail={"detail": "Failed to send SMS"}
                ) from exc
            await session.commit()
            return OtpSendResponse(
                message="OTP sent successfully", expires_in_seconds=expiry_seconds
            )


        @router.post("/verify", response_model=OtpVerifyResponse)
        async def verify_otp_code(
            body: OtpVerifyRequest,
            session: AsyncSession = Depends(get_session),
        ) -> OtpVerifyResponse:
            \"\"\"Verify a submitted OTP code.

            Finds the most recent unverified, unexpired code for the phone number,
            performs constant-time comparison, and marks it as verified on success.

            Args:
                body: Phone number and submitted OTP code.
                session: SQLAlchemy async session dependency.

            Returns:
                ``OtpVerifyResponse`` confirming the verified phone.

            Raises:
                HTTPException 400: Invalid or expired OTP code.
            \"\"\"
            now = datetime.now(timezone.utc)
            stmt = (
                select(OtpCode)
                .where(
                    OtpCode.phone == body.phone,
                    OtpCode.verified.is_(False),
                    OtpCode.expires_at > now,
                )
                .order_by(OtpCode.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record is None or not verify_otp(record.code, body.code):
                raise HTTPException(
                    status_code=400, detail={"detail": "Invalid or expired OTP code"}
                )
            record.verified = True
            await session.flush()
            await session.commit()
            return OtpVerifyResponse(verified=True, phone=body.phone)


        async def _enforce_rate_limit(session: AsyncSession, phone: str) -> None:
            \"\"\"Raise HTTP 429 if the phone has exceeded the OTP send rate limit.

            Args:
                session: Active async database session.
                phone: Phone number in E.164 format.

            Raises:
                HTTPException 429: When the rate limit is exceeded.
            \"\"\"
            max_requests = int(os.environ.get("OTP_RATE_LIMIT_MAX", str(_RATE_LIMIT_MAX)))
            window_seconds = int(
                os.environ.get("OTP_RATE_LIMIT_WINDOW_SECONDS", str(_RATE_LIMIT_WINDOW_SECONDS))
            )
            window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
            count_stmt = select(func.count()).where(
                OtpCode.phone == phone,
                OtpCode.created_at >= window_start,
            )
            result = await session.execute(count_stmt)
            count = result.scalar_one()
            if count >= max_requests:
                raise HTTPException(
                    status_code=429,
                    detail={"detail": "Too many OTP requests. Please wait before trying again."},
                )
    """)
    dest.write_text(content)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the otp_codes table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent(f"""\
        \"\"\"Add otp_codes table for SMS OTP authentication.

        Revision ID: 0076_add_sms_otp
        Revises: {down_rev}
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0076_add_sms_otp"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create otp_codes table.\"\"\"
            op.create_table(
                "otp_codes",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("phone", sa.String(20), nullable=False),
                sa.Column("code", sa.String(10), nullable=False),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index("ix_otp_codes_phone", "otp_codes", ["phone"])


        def downgrade() -> None:
            \"\"\"Drop otp_codes table.\"\"\"
            op.drop_index("ix_otp_codes_phone", table_name="otp_codes")
            op.drop_table("otp_codes")
    """)
    migration_file = versions_dir / "0076_add_sms_otp.py"
    migration_file.write_text(content)
    return migration_file
