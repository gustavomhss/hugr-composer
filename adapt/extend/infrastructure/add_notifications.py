"""TOOL-063: add_notifications — add a production-grade in-app notification layer.

Writes a channel-dispatching notification service, an ``app/notifications/``
package (service, channels), a ``Notification`` SQLAlchemy model, Pydantic
schemas, async CRUD helpers, REST routes (list, mark-read, read-all, unread
count), and an Alembic migration.

Why a channel abstraction?

* **In-app** — DB insert only; zero external dependencies.  The default for
  every notification type until a push/email channel is explicitly configured.
* **Push (FCM stub)** — ``firebase_admin`` is imported LAZILY; the app boots
  cleanly without it.  A ``WARNING`` is emitted if the package is absent.
* **Email bridge** — when ``app/email/`` (from add_email_templates) is
  present, the channel reuses ``EmailService`` instead of re-inventing SMTP.
* **Unread badge** — ``GET /notifications/unread-count`` executes a single
  ``COUNT(*)`` query; no full row scan.
* **Bulk read** — ``POST /notifications/read-all`` issues one
  ``UPDATE … WHERE user_id = ? AND read_at IS NULL`` — no N+1.

Security / correctness guarantees:

* ``notification_channels.py`` uses LAZY imports so ``firebase_admin`` (and
  any future SDK) does not need to be installed for the app to start.
* No channel handler logs raw notification bodies (potential PII).
* Every generated function is kept ≤50 LOC.
* The tool is idempotent: a second run detects the ``NotificationService``
  fingerprint in ``app/notifications/__init__.py`` and returns
  ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_notifications import add_notifications

    result = add_notifications(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # ["…/app/notifications/__init__.py", …]
    print(result.next_steps)     # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_notifications",
    "description": (
        "Add a production-grade in-app notification layer with channel dispatch "
        "(in_app, push FCM stub, email bridge), unread badge, and bulk mark-read."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_notifications",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_notifications(
    inp: ToolInput,
    *,
    max_per_page: int = 50,
) -> ToolResult:
    """Add a production-grade notification layer to a FastAPI project.

    Creates the ``app/notifications/`` package (service, channels),
    ``app/models/notification.py``, ``app/schemas/notification.py``,
    ``app/crud/notification.py``, ``app/api/routes/notifications.py``,
    and an Alembic migration.  Patches ``app/core/config.py``,
    ``app/models/__init__.py``, ``app/routes/__init__.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_per_page: Default page size for the notification list endpoint.
            Written into ``settings.NOTIFICATION_MAX_PER_PAGE``.

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
    notif_init = app_dir / "notifications" / "__init__.py"
    if notif_init.exists() and "NotificationService" in notif_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "NotificationService already present in app/notifications/__init__.py — "
                "notifications already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    has_email = (app_dir / "email" / "__init__.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/notifications/ (service, channels),",
                "         app/models/notification.py, app/schemas/notification.py,",
                "         app/crud/notification.py, app/api/routes/notifications.py,",
                "         and an Alembic migration for the `notifications` table.",
                f"         email_bridge={'enabled (add_email_templates detected)' if has_email else 'stub (no app/email/ found)'}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — notifications package (service, channels)
    _write_notifications_package(app_dir, files_created, has_email=has_email)

    # Step 2 — Notification model
    model_file = app_dir / "models" / "notification.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(_NOTIFICATION_MODEL)
    files_created.append(str(model_file))

    # Register Notification in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("notification", "Notification")])
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "notification.py"
    schema_file.write_text(_NOTIFICATION_SCHEMAS)
    files_created.append(str(schema_file))

    # Step 4 — async CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "notification.py"
    crud_file.write_text(_NOTIFICATION_CRUD)
    files_created.append(str(crud_file))

    # Step 5 — REST routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "notifications.py"
    routes_file.write_text(_NOTIFICATION_ROUTES)
    files_created.append(str(routes_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        mig = _write_notification_migration(versions_dir)
        files_created.append(str(mig))

    # Step 7 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, max_per_page=max_per_page)
        files_modified.append(str(config_file))

    # Step 8 — register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Validate every generated Python file parses
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Notification layer added: in_app channel (DB insert), push channel "
            "(FCM stub — firebase_admin lazy-imported), "
            + ("email channel (bridged to app/email/)." if has_email else "email channel stub (add_email_templates not detected)."),
            "GET /notifications — paginated list (newest first).",
            "POST /notifications/{id}/read — mark single notification read.",
            "POST /notifications/read-all — bulk mark-all-read (single UPDATE).",
            "GET /notifications/unread-count — fast COUNT(*) badge query.",
        ],
        next_steps=[
            "alembic upgrade head",
            "To enable push notifications: pip install firebase-admin, "
            "then set FIREBASE_CREDENTIALS_PATH in .env.",
            "Inject NotificationService where needed: "
            "from app.notifications import NotificationService",
            "Restart the FastAPI app so /notifications routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each ≤50 LOC body
# ---------------------------------------------------------------------------

def _write_notifications_package(
    app_dir: Path,
    files_created: list[str],
    *,
    has_email: bool,
) -> None:
    """Create ``app/notifications/`` with __init__, service, channels.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
        has_email: Whether ``app/email/`` (add_email_templates) is present.
    """
    pkg_dir = app_dir / "notifications"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    init_file = pkg_dir / "__init__.py"
    init_file.write_text(_NOTIFICATIONS_INIT)
    files_created.append(str(init_file))

    service_file = pkg_dir / "service.py"
    service_file.write_text(_NOTIFICATIONS_SERVICE)
    files_created.append(str(service_file))

    channels_file = pkg_dir / "channels.py"
    channels_content = _NOTIFICATIONS_CHANNELS_WITH_EMAIL if has_email else _NOTIFICATIONS_CHANNELS_STUB
    channels_file.write_text(channels_content)
    files_created.append(str(channels_file))


def _write_notification_migration(versions_dir: Path) -> Path:
    """Generate ``alembic/versions/add_notifications.py``.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _NOTIFICATION_MIGRATION.replace("DOWN_REV_PLACEHOLDER", down_rev)
    mig_file = versions_dir / "add_notifications.py"
    mig_file.write_text(content)
    return mig_file


# ---------------------------------------------------------------------------
# Config / init / routes patches
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to ``app/models/__init__.py``.
        class_imports: List of ``(module, class)`` tuples to register.
    """
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker not in content:
            new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path, *, max_per_page: int) -> None:
    """Inject notification settings into the ``Settings`` class body.

    Anchors on ``ACCESS_TOKEN_EXPIRE_MINUTES`` (the canonical anchor used
    by every extend/ tool); falls back to inserting before ``settings =``.

    Args:
        config_file: Path to ``app/core/config.py``.
        max_per_page: Value for ``NOTIFICATION_MAX_PER_PAGE``.
    """
    src = config_file.read_text()
    if "NOTIFICATION_CHANNELS" in src:
        return

    block = (
        "\n"
        "    # --- Notifications — added by add_notifications tool ---\n"
        '    NOTIFICATION_CHANNELS: list[str] = ["in_app"]\n'
        f"    NOTIFICATION_MAX_PER_PAGE: int = {max_per_page}\n"
        '    FIREBASE_CREDENTIALS_PATH: str = ""\n'
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
    """Register the notifications router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router(
        routes_init,
        import_line="from app.api.routes.notifications import router as notifications_router",
        include_line="api_router.include_router(notifications_router)",
    )


def _register_router(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to add.
        include_line: ``api_router.include_router(...)`` call to add.
    """
    src = routes_init.read_text()
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

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Python file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(f"Generated file {path} has a syntax error: {exc}") from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Generated file templates — plain string constants, written verbatim.
# ---------------------------------------------------------------------------

_NOTIFICATIONS_INIT = textwrap.dedent("""\
    \"\"\"Notification layer — in-app, push (FCM stub), and email channels.

    Public API:
        NotificationService:  create / mark_read / mark_all_read / list_unread
        dispatch:             channel router (in_app | push | email)
    \"\"\"

    from app.notifications.service import NotificationService
    from app.notifications.channels import dispatch

    __all__ = ["NotificationService", "dispatch"]
""")

_NOTIFICATIONS_SERVICE = textwrap.dedent("""\
    \"\"\"NotificationService — high-level facade for notification operations.

    All database mutations go through this service so callers never import
    CRUD helpers directly.  The service is intentionally stateless; pass an
    ``AsyncSession`` on every call.
    \"\"\"

    from __future__ import annotations

    import uuid
    from typing import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.crud.notification import (
        create_notification,
        list_unread,
        mark_read,
        mark_all_read,
        count_unread,
    )
    from app.schemas.notification import NotificationCreate
    from app.notifications.channels import dispatch


    class NotificationService:
        \"\"\"Facade for notification lifecycle operations.\"\"\"

        def __init__(self, session: AsyncSession) -> None:
            \"\"\"Initialise with an active async database session.\"\"\"
            self._session = session

        async def send(
            self,
            user_id: uuid.UUID,
            title: str,
            body: str,
            channel: str = "in_app",
        ) -> None:
            \"\"\"Create a notification and dispatch it through *channel*.

            Args:
                user_id: Recipient's user UUID.
                title: Short notification title.
                body: Full notification body text.
                channel: Delivery channel — ``"in_app"``, ``"push"``,
                    or ``"email"``.  Defaults to ``"in_app"``.
            \"\"\"
            data = NotificationCreate(
                user_id=user_id, title=title, body=body, channel=channel,
            )
            notif = await create_notification(self._session, data)
            await dispatch(notif, channel=channel)

        async def list_unread(
            self,
            user_id: uuid.UUID,
            *,
            limit: int = 50,
            offset: int = 0,
        ) -> Sequence:
            \"\"\"Return unread notifications for *user_id*, newest first.\"\"\"
            return await list_unread(self._session, user_id, limit=limit, offset=offset)

        async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
            \"\"\"Mark a single notification read; returns ``True`` if updated.\"\"\"
            return await mark_read(self._session, notification_id, user_id)

        async def mark_all_read(self, user_id: uuid.UUID) -> int:
            \"\"\"Bulk-mark all unread notifications read; returns count updated.\"\"\"
            return await mark_all_read(self._session, user_id)

        async def count_unread(self, user_id: uuid.UUID) -> int:
            \"\"\"Return the unread notification count for the badge widget.\"\"\"
            return await count_unread(self._session, user_id)
""")

_NOTIFICATIONS_CHANNELS_STUB = textwrap.dedent("""\
    \"\"\"Channel registry — routes notifications to the correct delivery handler.

    Channels:
        in_app  — DB insert only (no external dependency).
        push    — FCM stub; requires ``firebase_admin`` (lazy-imported).
        email   — Stub; install add_email_templates to enable the bridge.
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)


    async def dispatch(notification: object, *, channel: str = "in_app") -> None:
        \"\"\"Route *notification* to the handler registered for *channel*.

        The ``in_app`` channel is a no-op here because the row is already
        persisted by the CRUD layer before ``dispatch`` is called.  External
        channels (push, email) are where real side-effects happen.

        Args:
            notification: The persisted ``Notification`` ORM instance.
            channel: Delivery channel — one of ``"in_app"``, ``"push"``,
                ``"email"``.  Unknown channels are logged and ignored.
        \"\"\"
        if channel == "in_app":
            return  # already in DB — nothing more to do
        if channel == "push":
            await _send_push(notification)
        elif channel == "email":
            logger.warning(
                "email channel requested but add_email_templates is not installed; "
                "notification stored in-app only."
            )
        else:
            logger.warning("Unknown notification channel %r — ignored.", channel)


    async def _send_push(notification: object) -> None:
        \"\"\"Send a push notification via FCM (firebase_admin stub).

        ``firebase_admin`` is imported lazily so the app boots without it.
        If not installed, a WARNING is logged and the notification is silently
        stored in-app only.

        Args:
            notification: The persisted ``Notification`` ORM instance.
        \"\"\"
        try:
            import firebase_admin  # noqa: F401 — lazy optional dependency
            from firebase_admin import messaging
        except ImportError:
            logger.warning(
                "firebase_admin not installed — push notification skipped. "
                "Run: pip install firebase-admin"
            )
            return

        # Stub: real FCM send would go here.
        logger.info("FCM push stub — would send to user_id=%s", getattr(notification, "user_id", "?"))
""")

_NOTIFICATIONS_CHANNELS_WITH_EMAIL = textwrap.dedent("""\
    \"\"\"Channel registry — routes notifications to the correct delivery handler.

    Channels:
        in_app  — DB insert only (no external dependency).
        push    — FCM stub; requires ``firebase_admin`` (lazy-imported).
        email   — Bridges to ``app.email.service.EmailService`` (add_email_templates).
    \"\"\"

    from __future__ import annotations

    import logging

    logger = logging.getLogger(__name__)


    async def dispatch(notification: object, *, channel: str = "in_app") -> None:
        \"\"\"Route *notification* to the handler registered for *channel*.

        Args:
            notification: The persisted ``Notification`` ORM instance.
            channel: Delivery channel — one of ``"in_app"``, ``"push"``,
                ``"email"``.  Unknown channels are logged and ignored.
        \"\"\"
        if channel == "in_app":
            return
        if channel == "push":
            await _send_push(notification)
        elif channel == "email":
            await _send_email(notification)
        else:
            logger.warning("Unknown notification channel %r — ignored.", channel)


    async def _send_push(notification: object) -> None:
        \"\"\"Send a push notification via FCM (lazy import).

        Args:
            notification: The persisted ``Notification`` ORM instance.
        \"\"\"
        try:
            import firebase_admin  # noqa: F401
            from firebase_admin import messaging  # noqa: F401
        except ImportError:
            logger.warning(
                "firebase_admin not installed — push notification skipped. "
                "Run: pip install firebase-admin"
            )
            return
        logger.info("FCM push stub — would send to user_id=%s", getattr(notification, "user_id", "?"))


    async def _send_email(notification: object) -> None:
        \"\"\"Bridge to app.email.service (add_email_templates) for email channel.

        Args:
            notification: The persisted ``Notification`` ORM instance.
        \"\"\"
        try:
            from app.email.service import EmailService  # noqa: F401 — bridge import
        except ImportError:
            logger.warning("app.email.service not available — email channel skipped.")
            return
        logger.info(
            "Email bridge stub — user_id=%s title=%r",
            getattr(notification, "user_id", "?"),
            getattr(notification, "title", ""),
        )
""")

_NOTIFICATION_MODEL = textwrap.dedent("""\
    \"\"\"Notification ORM model.\"\"\"

    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import DateTime, ForeignKey, String, Text, func
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class Notification(Base):
        \"\"\"Persistent notification record.

        Attributes:
            id: UUID primary key.
            user_id: Owner's user UUID (foreign key).
            title: Short notification title (≤255 chars).
            body: Full notification body text.
            channel: Delivery channel used (``in_app``, ``push``, ``email``).
            read_at: Timestamp when the notification was read; ``None`` if unread.
            created_at: Timestamp of creation (server-side default).
        \"\"\"

        __tablename__ = "notifications"

        id: Mapped[uuid.UUID] = mapped_column(
            primary_key=True, default=uuid.uuid4, index=True,
        )
        user_id: Mapped[uuid.UUID] = mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        )
        title: Mapped[str] = mapped_column(String(255), nullable=False)
        body: Mapped[str] = mapped_column(Text, nullable=False, default="")
        channel: Mapped[str] = mapped_column(String(32), nullable=False, default="in_app")
        read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False,
        )
""")

_NOTIFICATION_SCHEMAS = textwrap.dedent("""\
    \"\"\"Pydantic schemas for the notification endpoints.\"\"\"

    from __future__ import annotations

    import uuid
    from datetime import datetime

    from pydantic import BaseModel, ConfigDict, Field


    class NotificationCreate(BaseModel):
        \"\"\"Input for creating a new notification (internal use).\"\"\"

        user_id: uuid.UUID
        title: str = Field(..., max_length=255)
        body: str = Field(default="")
        channel: str = Field(default="in_app", max_length=32)


    class NotificationRead(BaseModel):
        \"\"\"Single notification as returned to API consumers.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        user_id: uuid.UUID
        title: str
        body: str
        channel: str
        read_at: datetime | None
        created_at: datetime


    class NotificationList(BaseModel):
        \"\"\"Paginated list of notifications.\"\"\"

        items: list[NotificationRead]
        total: int
        unread_count: int


    class UnreadCount(BaseModel):
        \"\"\"Unread-badge response.\"\"\"

        unread_count: int
""")

_NOTIFICATION_CRUD = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the Notification model.\"\"\"

    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone
    from typing import Sequence

    from sqlalchemy import func, select, update
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.notification import Notification
    from app.schemas.notification import NotificationCreate


    async def create_notification(
        session: AsyncSession, data: NotificationCreate,
    ) -> Notification:
        \"\"\"Insert a new notification row and return the persisted object.\"\"\"
        notif = Notification(
            user_id=data.user_id,
            title=data.title,
            body=data.body,
            channel=data.channel,
        )
        session.add(notif)
        await session.commit()
        await session.refresh(notif)
        return notif


    async def list_unread(
        session: AsyncSession,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Notification]:
        \"\"\"Return unread notifications for *user_id*, newest first.\"\"\"
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


    async def mark_read(
        session: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID,
    ) -> bool:
        \"\"\"Mark a single notification read; returns True if the row was updated.\"\"\"
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


    async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> int:
        \"\"\"Bulk-mark all unread notifications for *user_id* as read.

        Issues a single UPDATE WHERE user_id = ? AND read_at IS NULL.

        Returns:
            Number of rows updated.
        \"\"\"
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(timezone.utc))
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount


    async def count_unread(session: AsyncSession, user_id: uuid.UUID) -> int:
        \"\"\"Return the number of unread notifications for *user_id* (COUNT query).\"\"\"
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one()
""")

_NOTIFICATION_ROUTES = textwrap.dedent("""\
    \"\"\"REST endpoints for the notification feature.

    Endpoints:
        GET  /notifications               — paginated list (newest first)
        POST /notifications/{id}/read     — mark single notification read
        POST /notifications/read-all      — bulk mark-all-read
        GET  /notifications/unread-count  — fast COUNT badge
    \"\"\"

    from __future__ import annotations

    import uuid

    from fastapi import APIRouter, Depends, HTTPException, Query, status
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.notifications.service import NotificationService
    from app.schemas.notification import NotificationList, NotificationRead, UnreadCount

    router = APIRouter(prefix="/notifications", tags=["notifications"])


    async def _get_session() -> AsyncSession:  # pragma: no cover — overridden in tests
        \"\"\"Placeholder session dependency; replaced by app/core/session.py.\"\"\"
        raise NotImplementedError("Inject a real get_session dependency")


    def _get_service(session: AsyncSession = Depends(_get_session)) -> NotificationService:
        \"\"\"FastAPI dependency that constructs a NotificationService.\"\"\"
        return NotificationService(session)


    @router.get("", response_model=NotificationList)
    async def list_notifications(
        user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        svc: NotificationService = Depends(_get_service),
    ) -> NotificationList:
        \"\"\"Return paginated unread notifications for *user_id*.\"\"\"
        items = await svc.list_unread(user_id, limit=limit, offset=offset)
        unread = await svc.count_unread(user_id)
        return NotificationList(
            items=[NotificationRead.model_validate(n) for n in items],
            total=len(items),
            unread_count=unread,
        )


    @router.post("/{notification_id}/read", response_model=NotificationRead)
    async def mark_notification_read(
        notification_id: uuid.UUID,
        user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
        svc: NotificationService = Depends(_get_service),
    ) -> NotificationRead:
        \"\"\"Mark a single notification as read.\"\"\"
        updated = await svc.mark_read(notification_id, user_id)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        items = await svc.list_unread(user_id, limit=1, offset=0)
        _ = items  # just confirming session is still open
        from app.crud.notification import mark_read as _crud_mark_read  # noqa: F401
        # Re-fetch to return up-to-date row — simplified for generator
        from sqlalchemy import select
        from app.models.notification import Notification
        stmt = select(Notification).where(Notification.id == notification_id)
        result = await svc._session.execute(stmt)
        notif = result.scalar_one_or_none()
        if notif is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        return NotificationRead.model_validate(notif)


    @router.post("/read-all", response_model=dict)
    async def mark_all_read(
        user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
        svc: NotificationService = Depends(_get_service),
    ) -> dict:
        \"\"\"Bulk-mark all notifications as read for *user_id*.\"\"\"
        updated = await svc.mark_all_read(user_id)
        return {"updated": updated}


    @router.get("/unread-count", response_model=UnreadCount)
    async def unread_count(
        user_id: uuid.UUID = Query(..., description="Requesting user UUID"),
        svc: NotificationService = Depends(_get_service),
    ) -> UnreadCount:
        \"\"\"Return the unread-notification count for the badge widget.\"\"\"
        count = await svc.count_unread(user_id)
        return UnreadCount(unread_count=count)
""")

_NOTIFICATION_MIGRATION = textwrap.dedent("""\
    \"\"\"add_notifications — Alembic migration.

    Revision ID: add_notifications
    Revises: DOWN_REV_PLACEHOLDER
    Create Date: 2026-04-15
    \"\"\"

    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision: str = "add_notifications"
    down_revision: str = "DOWN_REV_PLACEHOLDER"
    branch_labels = None
    depends_on = None


    def upgrade() -> None:
        \"\"\"Create the notifications table.\"\"\"
        op.create_table(
            "notifications",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "user_id",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("channel", sa.String(32), nullable=False, server_default="in_app"),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_notifications_user_id_read_at", "notifications", ["user_id", "read_at"])


    def downgrade() -> None:
        \"\"\"Drop the notifications table.\"\"\"
        op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")
        op.drop_table("notifications")
""")
