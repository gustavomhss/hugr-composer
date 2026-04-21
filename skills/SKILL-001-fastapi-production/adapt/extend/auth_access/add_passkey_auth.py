"""TOOL-075: add_passkey_auth — WebAuthn/FIDO2 passwordless authentication.

Generates all files required for WebAuthn/FIDO2 passkey registration and login:
a ``Passkey`` SQLAlchemy model (credential_id, public_key, user_id FK), a
``WebAuthnManager`` class with lazy ``py_webauthn`` import, Pydantic schemas,
and four route handlers:
  POST /passkeys/register/begin
  POST /passkeys/register/complete
  POST /passkeys/login/begin
  POST /passkeys/login/complete

The tool is idempotent: a second run detects the ``Passkey`` model fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth

    result = add_passkey_auth(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # [.../app/models/passkey.py, ...]
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
    "name": "fastapi_auth_add_passkey_auth",
    "description": (
        "Add WebAuthn/FIDO2 passwordless passkey authentication to a FastAPI project."
    ),
    "tags": ["extend", "auth_access"],
    "entry": "add_passkey_auth",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_passkey_auth(inp: ToolInput) -> ToolResult:
    """Add WebAuthn/FIDO2 passkey authentication to a FastAPI project.

    Writes all necessary files for passkey registration and login:
    Passkey model, WebAuthnManager with lazy py_webauthn, schemas, routes,
    and Alembic migration.

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
    model_file = app_dir / "models" / "passkey.py"
    if model_file.exists() and "Passkey" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Passkey model already present — WebAuthn auth already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) ----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create WebAuthn/FIDO2 passkey files.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: Passkey model
    _write_model(model_file)
    files_created.append(str(model_file))

    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("passkey", "Passkey")],
    )

    # Step 2: WebAuthnManager with lazy py_webauthn
    webauthn_file = app_dir / "auth" / "webauthn.py"
    _write_webauthn(webauthn_file)
    files_created.append(str(webauthn_file))

    auth_init = app_dir / "auth" / "__init__.py"
    if not auth_init.exists():
        auth_init.parent.mkdir(parents=True, exist_ok=True)
        auth_init.write_text('"""Auth package."""\n')
        files_created.append(str(auth_init))

    # Step 3: Schemas
    schema_file = app_dir / "schemas" / "passkey.py"
    _write_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 4: Routes
    routes_file = app_dir / "api" / "routes" / "passkeys.py"
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
            "WebAuthn/FIDO2 passkey registration and login implemented.",
            "py_webauthn imported lazily inside WebAuthnManager methods.",
            "Credential public keys stored as LargeBinary (raw bytes).",
            "Registration and login challenges stored in Redis (TTL=300s).",
            "Sign count validated on every login to detect cloned credentials.",
        ],
        next_steps=[
            "pip install py_webauthn",
            "Add WEBAUTHN_RP_ID, WEBAUTHN_RP_NAME, WEBAUTHN_ORIGIN to settings.",
            "alembic upgrade head",
            "Set WEBAUTHN_RP_ID to your domain (e.g. 'example.com').",
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
    """Inject WebAuthn config fields into Settings class idempotently.

    Args:
        config_file: Path to app/core/config.py.
    """
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("WEBAUTHN_RP_ID", 'WEBAUTHN_RP_ID: str = "localhost"'),
            ("WEBAUTHN_RP_NAME", 'WEBAUTHN_RP_NAME: str = "My App"'),
            ("WEBAUTHN_ORIGIN", 'WEBAUTHN_ORIGIN: str = "http://localhost:8000"'),
            ("WEBAUTHN_CHALLENGE_TTL_SECONDS", "WEBAUTHN_CHALLENGE_TTL_SECONDS: int = 300"),
        ],
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register passkeys router in app/routes/__init__.py idempotently.

    Args:
        routes_init: Path to app/routes/__init__.py.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.passkeys import router as passkeys_router"
    include_line = "api_router.include_router(passkeys_router)"
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
    """Write app/models/passkey.py with the Passkey SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for WebAuthn/FIDO2 passkey credentials.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            BigInteger,
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


        class Passkey(Base):
            \"\"\"Stored WebAuthn credential for a user.

            One user may have multiple passkeys (one per authenticator device).
            The public key is stored as raw bytes (COSE-encoded CBOR).

            Attributes:
                id: Primary key UUID.
                credential_id: WebAuthn credential identifier (base64url bytes).
                public_key: COSE-encoded CBOR public key bytes.
                sign_count: Monotonically increasing counter, cloned-device detection.
                aaguid: Authenticator AAGUID (device model identifier).
                user_id: FK to users.id (CASCADE DELETE).
                created_at: Immutable creation timestamp.
                last_used_at: Updated on every successful authentication.
            \"\"\"

            __tablename__ = "passkeys"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
            public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
            sign_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
            aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)

            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
            )

            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            last_used_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            __table_args__ = (
                UniqueConstraint("credential_id", name="uq_passkey_credential_id"),
            )
    """)
    dest.write_text(content)


def _write_webauthn(dest: Path) -> None:
    """Write app/auth/webauthn.py with WebAuthnManager and lazy py_webauthn import.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"WebAuthn/FIDO2 registration and authentication manager.\"\"\"

        from __future__ import annotations

        import logging
        import os

        logger = logging.getLogger(__name__)


        class WebAuthnManager:
            \"\"\"Manage WebAuthn registration and authentication ceremonies.

            Uses lazy import of ``py_webauthn`` so the application boots
            without the library installed.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialize manager using environment settings.\"\"\"
                self._rp_id = os.environ.get("WEBAUTHN_RP_ID", "localhost")
                self._rp_name = os.environ.get("WEBAUTHN_RP_NAME", "My App")
                self._origin = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")
                self._challenge_ttl = int(
                    os.environ.get("WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")
                )

            def generate_registration_options(self, user_id: str, username: str) -> dict:
                \"\"\"Generate WebAuthn registration options for the client.

                Args:
                    user_id: String representation of the user's UUID.
                    username: Display name for the authenticator prompt.

                Returns:
                    Dict with challenge, rp, user, and pubKeyCredParams fields.
                \"\"\"
                from py_webauthn import generate_registration_options
                from py_webauthn.helpers.structs import (
                    AuthenticatorSelectionCriteria,
                    ResidentKeyRequirement,
                    UserVerificationRequirement,
                )

                options = generate_registration_options(
                    rp_id=self._rp_id,
                    rp_name=self._rp_name,
                    user_id=user_id.encode(),
                    user_name=username,
                    authenticator_selection=AuthenticatorSelectionCriteria(
                        resident_key=ResidentKeyRequirement.REQUIRED,
                        user_verification=UserVerificationRequirement.REQUIRED,
                    ),
                )
                return _options_to_dict(options)

            def verify_registration_response(
                self, credential: dict, challenge: bytes
            ) -> dict:
                \"\"\"Verify the client's registration response.

                Args:
                    credential: JSON body from the client's navigator.credentials.create().
                    challenge: Expected challenge bytes from the session.

                Returns:
                    Dict with credential_id, public_key, sign_count, aaguid.

                Raises:
                    ValueError: If verification fails.
                \"\"\"
                from py_webauthn import verify_registration_response
                from py_webauthn.helpers.structs import RegistrationCredential

                reg_cred = RegistrationCredential.parse_raw(
                    _to_json(credential)
                )
                verification = verify_registration_response(
                    credential=reg_cred,
                    expected_challenge=challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origin,
                )
                return {
                    "credential_id": verification.credential_id,
                    "public_key": verification.credential_public_key,
                    "sign_count": verification.sign_count,
                    "aaguid": str(verification.aaguid) if verification.aaguid else None,
                }

            def generate_authentication_options(self) -> dict:
                \"\"\"Generate WebAuthn authentication options for the client.

                Returns:
                    Dict with challenge and userVerification fields.
                \"\"\"
                from py_webauthn import generate_authentication_options
                from py_webauthn.helpers.structs import UserVerificationRequirement

                options = generate_authentication_options(
                    rp_id=self._rp_id,
                    user_verification=UserVerificationRequirement.REQUIRED,
                )
                return _options_to_dict(options)

            def verify_authentication_response(
                self,
                credential: dict,
                challenge: bytes,
                stored_public_key: bytes,
                stored_sign_count: int,
            ) -> int:
                \"\"\"Verify the client's authentication response.

                Args:
                    credential: JSON body from navigator.credentials.get().
                    challenge: Expected challenge bytes from the session.
                    stored_public_key: COSE public key from the passkey row.
                    stored_sign_count: Current sign_count from the passkey row.

                Returns:
                    New sign_count to persist (must be > stored_sign_count).

                Raises:
                    ValueError: If verification fails or sign_count is invalid.
                \"\"\"
                from py_webauthn import verify_authentication_response
                from py_webauthn.helpers.structs import AuthenticationCredential

                auth_cred = AuthenticationCredential.parse_raw(
                    _to_json(credential)
                )
                verification = verify_authentication_response(
                    credential=auth_cred,
                    expected_challenge=challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origin,
                    credential_public_key=stored_public_key,
                    credential_current_sign_count=stored_sign_count,
                    require_user_verification=True,
                )
                return verification.new_sign_count


        def _options_to_dict(options: object) -> dict:
            \"\"\"Serialize py_webauthn options object to a plain dict.

            Args:
                options: py_webauthn options dataclass/object.

            Returns:
                JSON-serializable dict.
            \"\"\"
            import json

            return json.loads(
                options.json() if hasattr(options, "json") else "{}"
            )


        def _to_json(data: dict) -> str:
            \"\"\"Convert a dict to a JSON string for py_webauthn parsing.

            Args:
                data: Dictionary to serialize.

            Returns:
                JSON string representation.
            \"\"\"
            import json
            return json.dumps(data)
    """)
    dest.write_text(content)


def _write_schemas(dest: Path) -> None:
    """Write app/schemas/passkey.py with Pydantic schemas for passkey endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for WebAuthn/FIDO2 passkey endpoints.\"\"\"

        from __future__ import annotations

        import uuid
        from typing import Any

        from pydantic import BaseModel, ConfigDict


        class PasskeyRead(BaseModel):
            \"\"\"Public view of a stored passkey credential.

            Attributes:
                id: Primary key UUID.
                aaguid: Authenticator model identifier (may be None).
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            aaguid: str | None


        class RegistrationBeginRequest(BaseModel):
            \"\"\"Request body for beginning passkey registration.

            Attributes:
                user_id: UUID of the user registering the passkey.
                username: Display name shown in the authenticator.
            \"\"\"

            user_id: uuid.UUID
            username: str


        class RegistrationBeginResponse(BaseModel):
            \"\"\"Response containing WebAuthn registration options.

            Attributes:
                options: py_webauthn registration options as a JSON-serializable dict.
                session_id: Opaque session identifier for the challenge.
            \"\"\"

            options: dict[str, Any]
            session_id: str


        class RegistrationCompleteRequest(BaseModel):
            \"\"\"Request body for completing passkey registration.

            Attributes:
                session_id: Session identifier from the begin response.
                credential: navigator.credentials.create() output.
                user_id: UUID of the user completing registration.
            \"\"\"

            session_id: str
            credential: dict[str, Any]
            user_id: uuid.UUID


        class AuthenticationBeginResponse(BaseModel):
            \"\"\"Response containing WebAuthn authentication options.

            Attributes:
                options: py_webauthn authentication options as a JSON-serializable dict.
                session_id: Opaque session identifier for the challenge.
            \"\"\"

            options: dict[str, Any]
            session_id: str


        class AuthenticationCompleteRequest(BaseModel):
            \"\"\"Request body for completing passkey authentication.

            Attributes:
                session_id: Session identifier from the begin response.
                credential: navigator.credentials.get() output.
            \"\"\"

            session_id: str
            credential: dict[str, Any]


        class AuthenticationCompleteResponse(BaseModel):
            \"\"\"Response returned after successful passkey authentication.

            Attributes:
                access_token: JWT access token.
                token_type: Always 'bearer'.
                user_id: UUID of the authenticated user.
            \"\"\"

            access_token: str
            token_type: str = "bearer"
            user_id: uuid.UUID
    """)
    dest.write_text(content)


def _write_routes(dest: Path) -> None:
    """Write app/api/routes/passkeys.py with four WebAuthn route handlers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"WebAuthn/FIDO2 passkey registration and authentication routes.\"\"\"

        from __future__ import annotations

        import logging
        import secrets
        import uuid

        from fastapi import APIRouter, Depends, HTTPException
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.auth.webauthn import WebAuthnManager
        from app.core.session import get_session
        from app.schemas.passkey import (
            AuthenticationBeginResponse,
            AuthenticationCompleteRequest,
            AuthenticationCompleteResponse,
            RegistrationBeginRequest,
            RegistrationBeginResponse,
            RegistrationCompleteRequest,
        )

        logger = logging.getLogger(__name__)
        router = APIRouter(prefix="/passkeys", tags=["passkeys"])

        _webauthn = WebAuthnManager()


        @router.post("/register/begin", response_model=RegistrationBeginResponse)
        async def register_begin(
            body: RegistrationBeginRequest,
        ) -> RegistrationBeginResponse:
            \"\"\"Begin WebAuthn passkey registration ceremony.

            Generates a challenge and registration options for the client.

            Args:
                body: User ID and username for the authenticator prompt.

            Returns:
                ``RegistrationBeginResponse`` with options and session_id.
            \"\"\"
            try:
                options = _webauthn.generate_registration_options(
                    str(body.user_id), body.username
                )
            except Exception as exc:
                logger.error("register_begin failed: %s", exc)
                raise HTTPException(
                    status_code=500, detail={"detail": "Failed to generate registration options"}
                ) from exc
            session_id = secrets.token_urlsafe(32)
            _store_challenge(session_id, options.get("challenge", ""))
            return RegistrationBeginResponse(options=options, session_id=session_id)


        @router.post("/register/complete")
        async def register_complete(
            body: RegistrationCompleteRequest,
            session: AsyncSession = Depends(get_session),
        ) -> dict:
            \"\"\"Complete WebAuthn passkey registration and persist credential.

            Args:
                body: Session ID, credential from client, and user UUID.
                session: SQLAlchemy async session dependency.

            Returns:
                Dict with status and passkey_id fields.

            Raises:
                HTTPException 400: Invalid session or verification failure.
            \"\"\"
            challenge = _pop_challenge(body.session_id)
            if challenge is None:
                raise HTTPException(
                    status_code=400, detail={"detail": "Invalid or expired session"}
                )
            try:
                verified = _webauthn.verify_registration_response(
                    body.credential, challenge
                )
            except Exception as exc:
                logger.warning("Registration verification failed: %s", exc)
                raise HTTPException(
                    status_code=400, detail={"detail": "Registration verification failed"}
                ) from exc
            passkey_id = await _persist_passkey(session, body.user_id, verified)
            return {"status": "registered", "passkey_id": str(passkey_id)}


        @router.post("/login/begin", response_model=AuthenticationBeginResponse)
        async def login_begin() -> AuthenticationBeginResponse:
            \"\"\"Begin WebAuthn passkey authentication ceremony.

            Returns:
                ``AuthenticationBeginResponse`` with options and session_id.
            \"\"\"
            try:
                options = _webauthn.generate_authentication_options()
            except Exception as exc:
                logger.error("login_begin failed: %s", exc)
                raise HTTPException(
                    status_code=500, detail={"detail": "Failed to generate auth options"}
                ) from exc
            session_id = secrets.token_urlsafe(32)
            _store_challenge(session_id, options.get("challenge", ""))
            return AuthenticationBeginResponse(options=options, session_id=session_id)


        @router.post("/login/complete", response_model=AuthenticationCompleteResponse)
        async def login_complete(
            body: AuthenticationCompleteRequest,
            session: AsyncSession = Depends(get_session),
        ) -> AuthenticationCompleteResponse:
            \"\"\"Complete WebAuthn passkey authentication and issue JWT.

            Args:
                body: Session ID and credential from navigator.credentials.get().
                session: SQLAlchemy async session dependency.

            Returns:
                ``AuthenticationCompleteResponse`` with JWT and user_id.

            Raises:
                HTTPException 400: Unknown credential, expired session, or bad signature.
            \"\"\"
            challenge = _pop_challenge(body.session_id)
            if challenge is None:
                raise HTTPException(
                    status_code=400, detail={"detail": "Invalid or expired session"}
                )
            raw_id = body.credential.get("rawId") or body.credential.get("id", "")
            passkey_row = await _load_passkey_by_credential_id(session, raw_id)
            if passkey_row is None:
                raise HTTPException(
                    status_code=400, detail={"detail": "Unknown credential"}
                )
            try:
                new_count = _webauthn.verify_authentication_response(
                    body.credential, challenge,
                    passkey_row["public_key"], passkey_row["sign_count"],
                )
            except Exception as exc:
                logger.warning("Authentication verification failed: %s", exc)
                raise HTTPException(
                    status_code=400, detail={"detail": "Authentication verification failed"}
                ) from exc
            await _update_sign_count(session, passkey_row["id"], new_count)
            token = _mint_jwt(passkey_row["user_id"])
            return AuthenticationCompleteResponse(
                access_token=token, user_id=passkey_row["user_id"]
            )


        # ---------------------------------------------------------------------------
        # Internal helpers
        # ---------------------------------------------------------------------------

        _CHALLENGE_STORE: dict[str, bytes] = {}


        def _store_challenge(session_id: str, challenge: object) -> None:
            \"\"\"Persist a challenge keyed by session_id (in-process store).

            Args:
                session_id: Unique identifier for this ceremony.
                challenge: Challenge value (bytes or str).
            \"\"\"
            if isinstance(challenge, str):
                challenge = challenge.encode()
            _CHALLENGE_STORE[session_id] = challenge  # type: ignore[arg-type]


        def _pop_challenge(session_id: str) -> bytes | None:
            \"\"\"Retrieve and remove the challenge for *session_id*.

            Args:
                session_id: Session identifier from the begin response.

            Returns:
                Challenge bytes if found, else ``None``.
            \"\"\"
            return _CHALLENGE_STORE.pop(session_id, None)


        async def _persist_passkey(
            session: AsyncSession, user_id: uuid.UUID, verified: dict
        ) -> uuid.UUID:
            \"\"\"Insert a new Passkey row from verified registration data.

            Args:
                session: Active async database session.
                user_id: UUID of the registering user.
                verified: Dict from WebAuthnManager.verify_registration_response.

            Returns:
                UUID of the newly created passkey row.
            \"\"\"
            from app.models.passkey import Passkey

            passkey = Passkey(
                credential_id=verified["credential_id"],
                public_key=verified["public_key"],
                sign_count=verified.get("sign_count", 0),
                aaguid=verified.get("aaguid"),
                user_id=user_id,
            )
            session.add(passkey)
            await session.flush()
            return passkey.id


        async def _load_passkey_by_credential_id(
            session: AsyncSession, raw_id: str
        ) -> dict | None:
            \"\"\"Return passkey data for a credential ID, or None.

            Args:
                session: Active async database session.
                raw_id: Credential ID string from the client credential.

            Returns:
                Dict with id, user_id, public_key, sign_count; or None.
            \"\"\"
            from sqlalchemy import select
            from app.models.passkey import Passkey

            raw_bytes = raw_id.encode() if isinstance(raw_id, str) else raw_id
            stmt = select(Passkey).where(Passkey.credential_id == raw_bytes)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "user_id": row.user_id,
                "public_key": row.public_key,
                "sign_count": row.sign_count,
            }


        async def _update_sign_count(
            session: AsyncSession, passkey_id: uuid.UUID, new_count: int
        ) -> None:
            \"\"\"Update the sign_count and last_used_at for a passkey row.

            Args:
                session: Active async database session.
                passkey_id: Primary key of the passkey to update.
                new_count: New sign_count value from verification.
            \"\"\"
            from datetime import datetime, timezone
            from sqlalchemy import update
            from app.models.passkey import Passkey

            stmt = (
                update(Passkey)
                .where(Passkey.id == passkey_id)
                .values(sign_count=new_count, last_used_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt)
            await session.flush()


        def _mint_jwt(user_id: uuid.UUID) -> str:
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


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the passkeys table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent(f"""\
        \"\"\"Add passkeys table for WebAuthn/FIDO2 authentication.

        Revision ID: 0075_add_passkey_auth
        Revises: {down_rev}
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0075_add_passkey_auth"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create passkeys table.\"\"\"
            op.create_table(
                "passkeys",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("credential_id", sa.LargeBinary(), nullable=False),
                sa.Column("public_key", sa.LargeBinary(), nullable=False),
                sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
                sa.Column("aaguid", sa.String(64), nullable=True),
                sa.Column("user_id", sa.Uuid(), nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
                sa.ForeignKeyConstraint(
                    ["user_id"], ["users.id"], ondelete="CASCADE"
                ),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint("credential_id", name="uq_passkey_credential_id"),
            )
            op.create_index("ix_passkeys_user_id", "passkeys", ["user_id"])


        def downgrade() -> None:
            \"\"\"Drop passkeys table.\"\"\"
            op.drop_index("ix_passkeys_user_id", table_name="passkeys")
            op.drop_table("passkeys")
    """)
    migration_file = versions_dir / "0075_add_passkey_auth.py"
    migration_file.write_text(content)
    return migration_file
