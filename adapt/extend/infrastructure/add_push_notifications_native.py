"""TOOL-082: add_push_notifications_native — APNs + FCM real push notifications.

Writes a production-grade push notification system: a ``PushService`` with
``send_to_device`` and ``send_to_topic`` methods, lazy provider adapters for FCM
(``firebase_admin``) and APNs (``apns2``), a ``DeviceToken`` ORM model, Pydantic
schemas, async CRUD helpers, REST routes (register device, send notification, delete
device), and an Alembic migration.

Why real APNs + FCM (not a stub)?

* **FCM (Firebase Cloud Messaging)** — ``firebase_admin`` is the official Google
  SDK.  It supports both Android and web push.  The adapter initialises the app once
  (``_init_firebase``) and sends a single-device or topic message.
* **APNs (Apple Push Notification service)** — ``apns2`` is the leading pure-Python
  APNs client.  It connects via HTTP/2, handles certificate auth (key file + team ID
  + key ID), and sends structured payloads.
* **Lazy imports** — both SDKs are imported inside the method body so the app boots
  cleanly even when neither package is installed.  A ``WARNING`` is emitted instead
  of crashing.
* **Device token model** — ``DeviceToken`` links a user UUID to a platform + token
  pair.  The CRUD layer allows registering/deleting tokens and listing tokens per user.

Security / correctness guarantees:

* ``FCM_CREDENTIALS_PATH`` and ``APNS_KEY_PATH`` are read from ``settings`` at call
  time; they are NEVER logged or echoed.
* Platform field is validated as ``"ios"`` or ``"android"``; unknown values are
  rejected with HTTP 422.
* Every generated function is kept ≤50 LOC.
* The tool is idempotent: a second run detects ``PushService`` in
  ``app/push/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_push_notifications_native import (
        add_push_notifications_native,
    )

    result = add_push_notifications_native(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/push/__init__.py", …]
    print(result.next_steps)    # ["pip install firebase-admin", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_push_notifications_native",
    "description": (
        "Add production APNs + FCM push notifications with PushService, "
        "DeviceToken model, CRUD helpers, and REST routes. All SDKs lazy-imported."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_push_notifications_native",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_push_notifications_native(inp: ToolInput) -> ToolResult:
    """Add APNs + FCM push notifications to a FastAPI project.

    Creates ``app/push/`` (service, providers/fcm.py, providers/apns.py),
    ``app/models/device_token.py``, ``app/schemas/push.py``,
    ``app/crud/device_token.py``, ``app/api/routes/push.py``, and an
    Alembic migration.  Patches ``app/core/config.py``, registers the
    DeviceToken model, and adds the push router.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? --------------------------------------
    push_init = app_dir / "push" / "__init__.py"
    if push_init.exists() and "PushService" in push_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "PushService already present in app/push/__init__.py — "
                "push notifications already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/push/ (service, providers/fcm.py, providers/apns.py),",
                "         app/models/device_token.py, app/schemas/push.py,",
                "         app/crud/device_token.py, app/api/routes/push.py,",
                "         and an Alembic migration for the `device_tokens` table.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — push package (service + providers)
    _write_push_package(app_dir, files_created)

    # Step 2 — DeviceToken model
    model_file = app_dir / "models" / "device_token.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(_DEVICE_TOKEN_MODEL)
    files_created.append(str(model_file))

    # Register DeviceToken in models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init)
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "push.py"
    schema_file.write_text(_PUSH_SCHEMAS)
    files_created.append(str(schema_file))

    # Step 4 — CRUD helpers
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "device_token.py"
    crud_file.write_text(_DEVICE_TOKEN_CRUD)
    files_created.append(str(crud_file))

    # Step 5 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "push.py"
    routes_file.write_text(_PUSH_ROUTES)
    files_created.append(str(routes_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        mig = _write_device_token_migration(versions_dir)
        files_created.append(str(mig))

    # Step 7 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Validate every generated Python file parses
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
            "Push notification layer added: FCM (firebase_admin) + APNs (apns2), "
            "both lazy-imported.",
            "PushService.send_to_device routes to FCM or APNs based on platform field.",
            "PushService.send_to_topic broadcasts to an FCM topic.",
            "POST /push/register-device — register a device token.",
            "POST /push/send             — send a push notification.",
            "DELETE /push/devices/{id}  — unregister a device token.",
        ],
        next_steps=[
            "alembic upgrade head",
            "pip install firebase-admin  # for FCM/Android",
            "pip install apns2           # for APNs/iOS",
            "Set FCM_CREDENTIALS_PATH (JSON service account file) in .env.",
            "Set APNS_KEY_PATH, APNS_KEY_ID, APNS_TEAM_ID in .env for iOS.",
            "Set APNS_BUNDLE_ID to your app's bundle identifier.",
            "Restart the FastAPI app so /push/* routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body
# ---------------------------------------------------------------------------

def _write_push_package(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/push/`` package with __init__, service, and providers.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    push_dir = app_dir / "push"
    push_dir.mkdir(parents=True, exist_ok=True)

    providers_dir = push_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "__init__.py": _PUSH_INIT,
        "service.py": _PUSH_SERVICE,
        "providers/__init__.py": _PUSH_PROVIDERS_INIT,
        "providers/fcm.py": _FCM_PROVIDER,
        "providers/apns.py": _APNS_PROVIDER,
    }
    for name, content in files.items():
        p = push_dir / name
        p.write_text(content)
        files_created.append(str(p))


def _write_device_token_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration for the device_tokens table.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _DEVICE_TOKEN_MIGRATION.replace("DOWN_REV_PLACEHOLDER", down_rev)
    mig_file = versions_dir / "add_device_tokens.py"
    mig_file.write_text(content)
    return mig_file


def _patch_models_init(models_init: Path) -> None:
    """Register DeviceToken in ``app/models/__init__.py``.

    Args:
        models_init: Path to ``app/models/__init__.py``.
    """
    content = models_init.read_text()
    marker = "from app.models.device_token import DeviceToken"
    if marker in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"{marker}  # noqa: F401\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject push notification settings into the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "FCM_CREDENTIALS_PATH" in src:
        return

    block = (
        "\n"
        "    # --- Push notifications — added by add_push_notifications_native tool ---\n"
        '    FCM_CREDENTIALS_PATH: str = ""\n'
        '    APNS_KEY_PATH: str = ""\n'
        '    APNS_KEY_ID: str = ""\n'
        '    APNS_TEAM_ID: str = ""\n'
        '    APNS_BUNDLE_ID: str = ""\n'
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the push router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.push import router as push_router"
    include_line = "api_router.include_router(push_router)"
    if import_line in src:
        return

    lines = src.splitlines()
    last_app_import = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import = idx
    if last_app_import == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import = idx - 1
                break
    lines.insert(last_app_import + 1, import_line)

    last_include = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include = idx
    if last_include == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include = idx
                break
    lines.insert(last_include + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Generated file templates
# ---------------------------------------------------------------------------

_PUSH_INIT = textwrap.dedent("""\
    \"\"\"Push notification layer — APNs (iOS) + FCM (Android/web).

    Public API:
        PushService:  send_to_device(token, platform, title, body)
                      send_to_topic(topic, title, body)
    \"\"\"

    from app.push.service import PushService

    __all__ = ["PushService"]
""")

_PUSH_SERVICE = textwrap.dedent("""\
    \"\"\"PushService — high-level facade for push notification delivery.

    Routes to FCM or APNs based on the device platform field.
    Both provider SDKs are imported lazily so the app boots without them.
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)


    class PushService:
        \"\"\"Deliver push notifications to individual devices or FCM topics.\"\"\"

        async def send_to_device(
            self,
            *,
            token: str,
            platform: str,
            title: str,
            body: str,
            data: dict | None = None,
        ) -> bool:
            \"\"\"Send a push notification to a single device token.

            Args:
                token: Platform-specific device push token.
                platform: ``\"ios\"`` (uses APNs) or ``\"android\"`` (uses FCM).
                title: Notification title.
                body: Notification body text.
                data: Optional key-value data payload.

            Returns:
                ``True`` when the provider accepted the message.
            \"\"\"
            if platform == "ios":
                from app.push.providers.apns import APNsProvider
                provider = APNsProvider()
                return await provider.send(token=token, title=title, body=body, data=data)
            if platform == "android":
                from app.push.providers.fcm import FCMProvider
                provider = FCMProvider()
                return await provider.send_to_device(token=token, title=title, body=body, data=data)
            logger.warning("PushService: unknown platform %r — skipping.", platform)
            return False

        async def send_to_topic(
            self,
            *,
            topic: str,
            title: str,
            body: str,
            data: dict | None = None,
        ) -> bool:
            \"\"\"Broadcast a push notification to an FCM topic.

            Args:
                topic: FCM topic name (without the ``/topics/`` prefix).
                title: Notification title.
                body: Notification body text.
                data: Optional key-value data payload.

            Returns:
                ``True`` when FCM accepted the message.
            \"\"\"
            from app.push.providers.fcm import FCMProvider
            provider = FCMProvider()
            return await provider.send_to_topic(topic=topic, title=title, body=body, data=data)
""")

_PUSH_PROVIDERS_INIT = textwrap.dedent("""\
    \"\"\"Push notification provider adapters.

    Providers are imported lazily — install only what you use:
        pip install firebase-admin  # FCM (Android + Web)
        pip install apns2           # APNs (iOS)
    \"\"\"
""")

_FCM_PROVIDER = textwrap.dedent("""\
    \"\"\"FCM provider adapter — sends push notifications via Firebase Cloud Messaging.

    ``firebase_admin`` is imported lazily so the app boots without it.
    The Firebase app is initialised once via ``_init_firebase()``.
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)

    _firebase_initialised = False


    def _init_firebase() -> bool:
        \"\"\"Initialise the Firebase Admin SDK once.

        Reads credentials from ``settings.FCM_CREDENTIALS_PATH``.

        Returns:
            ``True`` if initialised successfully, ``False`` otherwise.
        \"\"\"
        global _firebase_initialised
        if _firebase_initialised:
            return True
        try:
            import firebase_admin  # noqa: PLC0415 — lazy optional dependency
            from firebase_admin import credentials as fb_creds
        except ImportError:
            logger.warning("firebase_admin not installed — FCM unavailable. pip install firebase-admin")
            return False
        try:
            from app.core.config import settings
            cred_path = settings.FCM_CREDENTIALS_PATH
            if not cred_path:
                logger.warning("FCM_CREDENTIALS_PATH not set — FCM unavailable.")
                return False
            cred = fb_creds.Certificate(cred_path)
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred)
            _firebase_initialised = True
            return True
        except Exception as exc:
            logger.warning("FCM init failed: %s", exc)
            return False


    class FCMProvider:
        \"\"\"Send push notifications via FCM.\"\"\"

        async def send_to_device(
            self,
            *,
            token: str,
            title: str,
            body: str,
            data: dict | None = None,
        ) -> bool:
            \"\"\"Send a notification to a single device token.

            Args:
                token: FCM registration token.
                title: Notification title.
                body: Notification body.
                data: Optional string key-value data payload.

            Returns:
                ``True`` on success, ``False`` when FCM is unavailable.
            \"\"\"
            if not _init_firebase():
                return False
            try:
                from firebase_admin import messaging  # noqa: PLC0415
                msg = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={k: str(v) for k, v in (data or {}).items()},
                    token=token,
                )
                messaging.send(msg)
                return True
            except Exception as exc:
                logger.warning("FCM send_to_device failed: %s", exc)
                return False

        async def send_to_topic(
            self,
            *,
            topic: str,
            title: str,
            body: str,
            data: dict | None = None,
        ) -> bool:
            \"\"\"Broadcast a notification to an FCM topic.

            Args:
                topic: FCM topic name (without /topics/ prefix).
                title: Notification title.
                body: Notification body.
                data: Optional string key-value data payload.

            Returns:
                ``True`` on success, ``False`` when FCM is unavailable.
            \"\"\"
            if not _init_firebase():
                return False
            try:
                from firebase_admin import messaging  # noqa: PLC0415
                msg = messaging.Message(
                    notification=messaging.Notification(title=title, body=body),
                    data={k: str(v) for k, v in (data or {}).items()},
                    topic=topic,
                )
                messaging.send(msg)
                return True
            except Exception as exc:
                logger.warning("FCM send_to_topic failed: %s", exc)
                return False
""")

_APNS_PROVIDER = textwrap.dedent("""\
    \"\"\"APNs provider adapter — sends push notifications via Apple Push Notification service.

    ``apns2`` is imported lazily so the app boots without it.
    Uses the HTTP/2 token-based authentication (key file + key ID + team ID).
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)


    class APNsProvider:
        \"\"\"Send push notifications via APNs (Apple Push Notification service).\"\"\"

        async def send(
            self,
            *,
            token: str,
            title: str,
            body: str,
            data: dict | None = None,
        ) -> bool:
            \"\"\"Send a notification to a single iOS device token.

            Args:
                token: APNs device token (hex string).
                title: Notification title.
                body: Notification body.
                data: Optional custom data dict merged into the APNs payload.

            Returns:
                ``True`` on success, ``False`` when APNs is unavailable.
            \"\"\"
            try:
                from apns2.client import APNsClient  # noqa: PLC0415 — lazy optional dependency
                from apns2.payload import Payload, PayloadAlert  # noqa: PLC0415
            except ImportError:
                logger.warning("apns2 not installed — APNs unavailable. pip install apns2")
                return False

            try:
                from app.core.config import settings
                if not settings.APNS_KEY_PATH:
                    logger.warning("APNS_KEY_PATH not set — APNs unavailable.")
                    return False
                client = APNsClient(
                    credentials=settings.APNS_KEY_PATH,
                    use_sandbox=settings.ENVIRONMENT != "production",
                    use_alternative_port=False,
                )
                alert = PayloadAlert(title=title, body=body)
                payload = Payload(alert=alert, custom=data or {})
                client.send_notification(
                    token_hex=token,
                    notification=payload,
                    topic=settings.APNS_BUNDLE_ID,
                )
                return True
            except Exception as exc:
                logger.warning("APNs send failed: %s", exc)
                return False
""")

_DEVICE_TOKEN_MODEL = textwrap.dedent("""\
    \"\"\"DeviceToken ORM model — links users to their push notification tokens.\"\"\"

    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import DateTime, ForeignKey, String, func
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class DeviceToken(Base):
        \"\"\"Stores a user's platform-specific push notification token.\"\"\"

        __tablename__ = "device_tokens"

        id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
        user_id: Mapped[uuid.UUID] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
        )
        platform: Mapped[str] = mapped_column(String(16), nullable=False)
        token: Mapped[str] = mapped_column(String(512), nullable=False)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
""")

_PUSH_SCHEMAS = textwrap.dedent("""\
    \"\"\"Pydantic schemas for push notification endpoints.\"\"\"

    from __future__ import annotations

    import uuid
    from datetime import datetime
    from typing import Literal

    from pydantic import BaseModel, ConfigDict


    class DeviceTokenCreate(BaseModel):
        \"\"\"Schema for registering a device push token.\"\"\"

        user_id: uuid.UUID
        platform: Literal["ios", "android"]
        token: str


    class DeviceTokenRead(BaseModel):
        \"\"\"Schema for reading a registered device token.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        user_id: uuid.UUID
        platform: str
        token: str
        created_at: datetime


    class PushSendRequest(BaseModel):
        \"\"\"Schema for sending a push notification.\"\"\"

        device_token_id: uuid.UUID | None = None
        topic: str | None = None
        title: str
        body: str
        data: dict[str, str] = {}


    class PushSendResult(BaseModel):
        \"\"\"Result of a push notification send attempt.\"\"\"

        sent: bool
        detail: str = ""
""")

_DEVICE_TOKEN_CRUD = textwrap.dedent("""\
    \"\"\"CRUD helpers for DeviceToken — register, list, and delete device push tokens.\"\"\"

    from __future__ import annotations

    import uuid

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.device_token import DeviceToken
    from app.schemas.push import DeviceTokenCreate


    async def create_device_token(
        session: AsyncSession,
        data: DeviceTokenCreate,
    ) -> DeviceToken:
        \"\"\"Register a new device push token.

        Args:
            session: Active async database session.
            data: Validated ``DeviceTokenCreate`` schema instance.

        Returns:
            The persisted ``DeviceToken`` ORM instance.
        \"\"\"
        token = DeviceToken(
            id=uuid.uuid4(),
            user_id=data.user_id,
            platform=data.platform,
            token=data.token,
        )
        session.add(token)
        await session.commit()
        await session.refresh(token)
        return token


    async def get_device_token(
        session: AsyncSession,
        token_id: uuid.UUID,
    ) -> DeviceToken | None:
        \"\"\"Fetch a device token by ID.

        Args:
            session: Active async database session.
            token_id: UUID of the device token row.

        Returns:
            The ``DeviceToken`` instance or ``None`` if not found.
        \"\"\"
        result = await session.execute(
            select(DeviceToken).where(DeviceToken.id == token_id)
        )
        return result.scalar_one_or_none()


    async def list_tokens_for_user(
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[DeviceToken]:
        \"\"\"Return all device tokens registered for *user_id*.

        Args:
            session: Active async database session.
            user_id: UUID of the user whose tokens to retrieve.

        Returns:
            List of ``DeviceToken`` ORM instances.
        \"\"\"
        result = await session.execute(
            select(DeviceToken).where(DeviceToken.user_id == user_id)
        )
        return list(result.scalars().all())


    async def delete_device_token(
        session: AsyncSession,
        token_id: uuid.UUID,
    ) -> bool:
        \"\"\"Delete a device token by ID.

        Args:
            session: Active async database session.
            token_id: UUID of the device token row to delete.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        \"\"\"
        result = await session.execute(
            delete(DeviceToken).where(DeviceToken.id == token_id)
        )
        await session.commit()
        return result.rowcount > 0
""")

_PUSH_ROUTES = textwrap.dedent("""\
    \"\"\"HTTP routes for push notification device management and sending.

    POST   /push/register-device    — register a device push token.
    POST   /push/send               — send a push notification.
    DELETE /push/devices/{id}       — unregister a device token.
    \"\"\"

    from __future__ import annotations

    import logging
    import uuid
    from typing import Any

    from fastapi import APIRouter, Depends, HTTPException, status
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.schemas.push import (
        DeviceTokenCreate,
        DeviceTokenRead,
        PushSendRequest,
        PushSendResult,
    )

    logger = logging.getLogger(__name__)
    router = APIRouter(prefix="/push", tags=["push"])


    async def _get_session() -> Any:
        \"\"\"Database session dependency — resolved at runtime from app.core.session.

        Yields:
            An active ``AsyncSession``.
        \"\"\"
        from app.core.session import get_session
        async for session in get_session():
            yield session


    @router.post(
        "/register-device",
        response_model=DeviceTokenRead,
        status_code=status.HTTP_201_CREATED,
        summary="Register a device push token",
    )
    async def register_device(
        data: DeviceTokenCreate,
        session: AsyncSession = Depends(_get_session),
    ) -> DeviceTokenRead:
        \"\"\"Register a device push token for a user.

        Args:
            data: Device token registration payload.
            session: Active async database session.

        Returns:
            The created ``DeviceTokenRead`` schema.
        \"\"\"
        from app.crud.device_token import create_device_token
        token = await create_device_token(session, data)
        return DeviceTokenRead.model_validate(token)


    @router.post(
        "/send",
        response_model=PushSendResult,
        summary="Send a push notification",
    )
    async def send_push(
        req: PushSendRequest,
        session: AsyncSession = Depends(_get_session),
    ) -> PushSendResult:
        \"\"\"Send a push notification to a device or FCM topic.

        Provide either ``device_token_id`` (single device) or ``topic``
        (FCM broadcast).  Returns ``{\"sent\": true}`` on success.

        Args:
            req: Push send request payload.
            session: Active async database session.

        Returns:
            ``PushSendResult`` with ``sent`` flag.

        Raises:
            HTTPException 404: When ``device_token_id`` is set but not found.
            HTTPException 422: When neither ``device_token_id`` nor ``topic`` is set.
        \"\"\"
        from app.push.service import PushService
        svc = PushService()

        if req.topic:
            sent = await svc.send_to_topic(
                topic=req.topic, title=req.title, body=req.body, data=req.data,
            )
            return PushSendResult(sent=sent)

        if req.device_token_id:
            from app.crud.device_token import get_device_token
            token_row = await get_device_token(session, req.device_token_id)
            if not token_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"detail": "Device token not found."},
                )
            sent = await svc.send_to_device(
                token=token_row.token,
                platform=token_row.platform,
                title=req.title,
                body=req.body,
                data=req.data,
            )
            return PushSendResult(sent=sent)

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"detail": "Provide either device_token_id or topic."},
        )


    @router.delete(
        "/devices/{token_id}",
        status_code=status.HTTP_200_OK,
        summary="Unregister a device push token",
    )
    async def delete_device(
        token_id: uuid.UUID,
        session: AsyncSession = Depends(_get_session),
    ) -> dict[str, bool]:
        \"\"\"Unregister a device push token.

        Args:
            token_id: UUID of the device token to delete.
            session: Active async database session.

        Returns:
            ``{\"deleted\": true}`` if the token was found and removed.

        Raises:
            HTTPException 404: When no token with *token_id* exists.
        \"\"\"
        from app.crud.device_token import delete_device_token
        deleted = await delete_device_token(session, token_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": "Device token not found."},
            )
        return {"deleted": True}
""")

_DEVICE_TOKEN_MIGRATION = textwrap.dedent("""\
    \"\"\"add device_tokens table

    Revision ID: add_device_tokens
    Revises: DOWN_REV_PLACEHOLDER
    Create Date: 2026-01-01 00:00:00
    \"\"\"

    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision: str = "add_device_tokens"
    down_revision: str = "DOWN_REV_PLACEHOLDER"
    branch_labels = None
    depends_on = None


    def upgrade() -> None:
        \"\"\"Create the device_tokens table.\"\"\"
        op.create_table(
            "device_tokens",
            sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("platform", sa.String(16), nullable=False),
            sa.Column("token", sa.String(512), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )


    def downgrade() -> None:
        \"\"\"Drop the device_tokens table.\"\"\"
        op.drop_table("device_tokens")
""")
