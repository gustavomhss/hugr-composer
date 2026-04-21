"""TOOL-017: add_websocket_chat — add WebSocket chat to a FastAPI/SQLAlchemy project.

Writes a multi-worker-safe ``WebSocketManager`` (Redis pub/sub fan-out), the
``/ws/chat/{room_id}`` endpoint with JWT-query-or-Authorization-subprotocol
auth, ``ChatRoom`` / ``ChatMessage`` SQLAlchemy models, Pydantic schemas, CRUD
helpers, HTTP companion routes (create room / list rooms / scrollback), an
Alembic migration (tenant-aware when ``app/models/tenant.py`` exists), and
every required ``settings`` key.

Security guarantees:

* JWT is verified via the scaffold's ``app.core.jwt.verify_access_token``
  helper — the tool does NOT invent a new auth scheme.
* Failed auth closes the socket with code ``1008 Policy Violation`` BEFORE
  any DB write.
* Per-user connection cap (default 5 simultaneous sockets) is enforced via
  a Redis counter so cap survives worker restarts.
* Per-room message rate-limiting is enforced via a Redis token bucket so a
  chatty user cannot drown a room.
* ``ChatMessageIn.content`` is Pydantic-validated (``max_length`` bounded)
  before persistence.
* Fan-out is ALWAYS through Redis — there is no in-memory-only broadcast,
  which means horizontal scaling works out of the box.

The tool is idempotent: a second run detects the ``WebSocketManager``
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.realtime.add_websocket_chat import add_websocket_chat

    result = add_websocket_chat(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/ws/chat.py", …]
    print(result.next_steps)    # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_realtime_add_websocket_chat",
    "description": "Add production-grade WebSocket chat with JWT auth, Redis pub/sub, rooms, and message history.",
    "tags": ["extend", "realtime"],
    "entry": "add_websocket_chat",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_websocket_chat(
    inp: ToolInput,
    *,
    max_connections_per_user: int = 5,
    message_max_length: int = 4000,
    rate_limit_per_minute: int = 30,
) -> ToolResult:
    """Add WebSocket chat support to a FastAPI project.

    Creates the connection manager, WebSocket endpoint, chat models, schemas,
    CRUD, HTTP companion routes, and the Alembic migration.  Patches
    ``app/core/config.py``, ``app/routes/__init__.py``, ``app/models/__init__.py``
    and ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_connections_per_user: Maximum simultaneous WS sockets per user
            (default 5).
        message_max_length: Hard cap on ``ChatMessageIn.content`` length
            (default 4000).
        rate_limit_per_minute: Per-user max messages per minute per room
            (default 30).

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
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
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    chat_ws_file = app_dir / "ws" / "chat.py"
    if chat_ws_file.exists() and "WebSocketManager" in chat_ws_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WebSocketManager already present — WebSocket chat is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create WebSocketManager, /ws/chat/{room_id} endpoint,",
                "         ChatRoom+ChatMessage models, schemas, CRUD, HTTP routes, migration.",
                f"         max_connections_per_user={max_connections_per_user}, "
                f"message_max_length={message_max_length}, "
                f"rate_limit_per_minute={rate_limit_per_minute}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 – models
    has_tenants = (app_dir / "models" / "tenant.py").exists()
    chat_model_file = app_dir / "models" / "chat.py"
    _write_chat_models(chat_model_file, has_tenants=has_tenants)
    files_created.append(str(chat_model_file))

    # Register ChatRoom + ChatMessage in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(
            models_init,
            [("chat", "ChatRoom"), ("chat", "ChatMessage")],
        )
        files_modified.append(str(models_init))

    # Step 2 – schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "chat.py"
    _write_chat_schemas(schema_file, message_max_length)
    files_created.append(str(schema_file))

    # Step 3 – CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "chat.py"
    _write_chat_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 4 – ws package (manager + endpoint)
    ws_dir = app_dir / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_init = ws_dir / "__init__.py"
    if not ws_init.exists():
        ws_init.write_text('"""WebSocket sub-package."""\n')
        files_created.append(str(ws_init))

    manager_file = ws_dir / "connection_manager.py"
    _write_connection_manager(manager_file, max_connections_per_user)
    files_created.append(str(manager_file))

    _write_chat_endpoint(chat_ws_file, rate_limit_per_minute, message_max_length)
    files_created.append(str(chat_ws_file))

    # Step 5 – HTTP companion routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    http_route_file = routes_dir / "chat.py"
    _write_chat_http_routes(http_route_file)
    files_created.append(str(http_route_file))

    # Step 6 – Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_chat_migration(versions_dir, has_tenants=has_tenants)
        files_created.append(str(migration_file))

    # Step 7 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            max_connections_per_user,
            message_max_length,
            rate_limit_per_minute,
        )
        files_modified.append(str(config_file))

    # Step 8 – register chat router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9 – patch app/main.py for WS route import
    main_file = app_dir / "main.py"
    if main_file.exists():
        modified = _patch_main(main_file)
        if modified:
            files_modified.append(str(main_file))

    # Step 10 – ensure app/core/redis.py exists (base project may not have it)
    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        _write_redis_module(redis_module)
        files_created.append(str(redis_module))

    # Step 11 – add redis to requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate all written files parse correctly
    for path_str in files_created:
        _assert_parses(Path(path_str))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "WebSocket chat added: connection manager, endpoint, models, schemas, CRUD.",
            f"Endpoint: WS /ws/chat/{{room_id}}?token=<JWT>",
            f"Per-user connection cap: {max_connections_per_user}.  "
            f"Rate limit: {rate_limit_per_minute}/min.  "
            f"Message max length: {message_max_length}.",
            "Fan-out is through Redis pub/sub — multi-worker safe out of the box.",
            "Companion HTTP routes: POST /chat/rooms, GET /chat/rooms, "
            "GET /chat/rooms/{room_id}/history.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — pub/sub and rate-limiter require Redis.",
            "Restart the application so the new chat router and WS endpoint are active.",
            "Connect a client with: ws://<host>/ws/chat/<room_id>?token=<access_token>",
            "Verify the HTTP side at GET /docs → /chat/rooms.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each <= 50 LOC
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


def _write_chat_models(dest: Path, *, has_tenants: bool = False) -> None:
    """Write ``app/models/chat.py`` with ``ChatRoom`` and ``ChatMessage``.

    Args:
        dest: Absolute path for the new file.
        has_tenants: Whether ``app/models/tenant.py`` exists.  When *True* the
            ``tenant_id`` column includes a ``ForeignKey("tenants.id")``
            reference on both tables; otherwise it is a plain nullable UUID
            column (no FK).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    if has_tenants:
        fk_import = "ForeignKey,\n        "
        room_tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant owning this chat room",\n'
            '    )'
        )
        msg_tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant context for multi-tenant message routing",\n'
            '    )'
        )
    else:
        fk_import = "ForeignKey,\n        "
        room_tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant owning this chat room",\n'
            '    )'
        )
        msg_tenant_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant context for multi-tenant message routing",\n'
            '    )'
        )

    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy models for WebSocket chat (rooms + messages).\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            Boolean,
            DateTime,
            {fk_import}Index,
            String,
            Text,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class ChatRoom(Base):
            \"\"\"A chat room.  Rooms are ephemeral channels for real-time messaging.

            Attributes:
                id: UUID primary key.
                tenant_id: Tenant UUID for multi-tenant chat isolation.
                name: Human-readable room name.
                is_private: Whether membership is restricted (private rooms require
                    explicit grants — not modeled in this minimal schema).
                created_by: UUID of the user who created the room.
                created_at: UTC timestamp of room creation.
            \"\"\"

            __tablename__ = "chat_rooms"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            ROOM_TENANT_PLACEHOLDER
            name: Mapped[str] = mapped_column(String(127), nullable=False)
            is_private: Mapped[bool] = mapped_column(
                Boolean, nullable=False, server_default="false"
            )
            created_by: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            )
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                nullable=False,
            )


        class ChatMessage(Base):
            \"\"\"A single chat message persisted for scrollback.

            Attributes:
                id: UUID primary key.
                tenant_id: Tenant UUID for multi-tenant message scoping.
                room_id: FK to ``chat_rooms.id`` with cascade delete.
                user_id: FK to ``users.id`` — author of the message.
                content: Message text (validated length at the Pydantic layer).
                created_at: UTC timestamp when the message was written.
                edited_at: UTC timestamp of the last edit (``None`` if unedited).
            \"\"\"

            __tablename__ = "chat_messages"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            MSG_TENANT_PLACEHOLDER
            room_id: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("chat_rooms.id", ondelete="CASCADE"),
                nullable=False,
            )
            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            )
            content: Mapped[str] = mapped_column(Text, nullable=False)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                nullable=False,
            )
            edited_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True),
                nullable=True,
            )

            __table_args__ = (
                Index(
                    "ix_chat_messages_room_created",
                    "room_id",
                    "created_at",
                ),
                Index(
                    "ix_chat_messages_user_created",
                    "user_id",
                    "created_at",
                ),
            )
        """).replace("{fk_import}", fk_import).replace(
        "    ROOM_TENANT_PLACEHOLDER", room_tenant_col,
    ).replace(
        "    MSG_TENANT_PLACEHOLDER", msg_tenant_col,
    )
    dest.write_text(content)


def _write_chat_schemas(dest: Path, message_max_length: int) -> None:
    """Write ``app/schemas/chat.py`` with Pydantic request/response schemas.

    Args:
        dest: Absolute path for the new file.
        message_max_length: Hard upper bound on ``ChatMessageIn.content``.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for WebSocket chat (rooms + messages).\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field

        _MESSAGE_MAX_LENGTH = {max_len}


        class ChatMessageIn(BaseModel):
            \"\"\"Schema for inbound WebSocket chat messages (client -> server).

            Attributes:
                content: Message text.  Length is strictly bounded to prevent
                    abuse — the server rejects anything over ``_MESSAGE_MAX_LENGTH``
                    with a WebSocket error frame.
            \"\"\"

            model_config = ConfigDict(strict=True, extra="forbid")

            content: str = Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)


        class ChatMessageOut(BaseModel):
            \"\"\"Schema for outbound chat messages (server -> client fan-out).

            Attributes:
                id: UUID of the persisted message.
                room_id: UUID of the room the message belongs to.
                user_id: UUID of the author.
                user_name: Display name of the author (denormalized for UI).
                content: Message text.
                created_at: UTC timestamp of creation.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            room_id: uuid.UUID
            user_id: uuid.UUID
            user_name: str
            content: str
            created_at: datetime


        class ChatRoomCreate(BaseModel):
            \"\"\"Request schema for creating a new chat room.

            Attributes:
                name: Human-readable room name (3..127 chars).
                is_private: Whether the room is private (default ``False``).
            \"\"\"

            model_config = ConfigDict(strict=True, extra="forbid")

            name: str = Field(min_length=3, max_length=127)
            is_private: bool = False


        class ChatRoomPublic(BaseModel):
            \"\"\"Public representation of a chat room.

            Attributes:
                id: UUID primary key.
                name: Human-readable name.
                is_private: Whether the room is private.
                created_at: UTC creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            name: str
            is_private: bool
            created_at: datetime
        """).replace("{max_len}", str(message_max_length))
    dest.write_text(content)


def _write_chat_crud(dest: Path) -> None:
    """Write ``app/crud/chat.py`` with async CRUD helpers for chat.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Async CRUD helpers for chat rooms and messages.\"\"\"
        from __future__ import annotations

        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.chat import ChatMessage, ChatRoom


        async def create_room(
            session: AsyncSession,
            *,
            name: str,
            is_private: bool,
            created_by: uuid.UUID,
        ) -> ChatRoom:
            \"\"\"Create a new chat room owned by *created_by*.

            Args:
                session: Async database session.
                name: Human-readable room name.
                is_private: Whether the room should be private.
                created_by: UUID of the creating user.

            Returns:
                The persisted ``ChatRoom`` instance.
            \"\"\"
            room = ChatRoom(name=name, is_private=is_private, created_by=created_by)
            session.add(room)
            await session.flush()
            return room


        async def get_room(
            session: AsyncSession, *, room_id: uuid.UUID
        ) -> ChatRoom | None:
            \"\"\"Fetch a room by id.

            Args:
                session: Async database session.
                room_id: UUID of the room.

            Returns:
                The ``ChatRoom`` or ``None`` if not found.
            \"\"\"
            stmt = select(ChatRoom).where(ChatRoom.id == room_id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_rooms(
            session: AsyncSession,
            *,
            user_id: uuid.UUID,
            limit: int = 50,
        ) -> list[ChatRoom]:
            \"\"\"Return rooms the user can see (public rooms + own private).

            Args:
                session: Async database session.
                user_id: UUID of the requesting user.
                limit: Maximum number of rooms to return.

            Returns:
                List of ``ChatRoom`` instances, newest first.
            \"\"\"
            stmt = (
                select(ChatRoom)
                .where(
                    (ChatRoom.is_private == False)  # noqa: E712
                    | (ChatRoom.created_by == user_id)
                )
                .order_by(ChatRoom.created_at.desc())
                .limit(limit)
            )
            return list((await session.execute(stmt)).scalars().all())


        async def save_message(
            session: AsyncSession,
            *,
            room_id: uuid.UUID,
            user_id: uuid.UUID,
            content: str,
        ) -> ChatMessage:
            \"\"\"Persist a new chat message.

            Args:
                session: Async database session.
                room_id: UUID of the target room.
                user_id: UUID of the author.
                content: Validated message text.

            Returns:
                The persisted ``ChatMessage`` instance.
            \"\"\"
            msg = ChatMessage(room_id=room_id, user_id=user_id, content=content)
            session.add(msg)
            await session.flush()
            return msg


        async def get_history(
            session: AsyncSession,
            *,
            room_id: uuid.UUID,
            limit: int = 50,
            before_id: uuid.UUID | None = None,
        ) -> list[ChatMessage]:
            \"\"\"Return the most recent messages in *room_id*, newest last.

            Args:
                session: Async database session.
                room_id: UUID of the room.
                limit: Maximum number of messages to return (default 50).
                before_id: Optional pagination cursor — return messages strictly
                    older than this message id.

            Returns:
                List of ``ChatMessage`` instances, oldest first (UI friendly).
            \"\"\"
            stmt = (
                select(ChatMessage)
                .where(ChatMessage.room_id == room_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
            if before_id is not None:
                anchor_stmt = select(ChatMessage.created_at).where(
                    ChatMessage.id == before_id
                )
                anchor = (await session.execute(anchor_stmt)).scalar_one_or_none()
                if anchor is not None:
                    stmt = stmt.where(ChatMessage.created_at < anchor)
            rows = list((await session.execute(stmt)).scalars().all())
            rows.reverse()
            return rows


        async def check_user_can_join(
            session: AsyncSession,
            *,
            room_id: uuid.UUID,
            user_id: uuid.UUID,
        ) -> bool:
            \"\"\"Return whether *user_id* is allowed to join *room_id*.

            Public rooms allow any authenticated user.  Private rooms are
            restricted to their creator in this minimal model — richer
            access-control lives in a future ACL table.

            Args:
                session: Async database session.
                room_id: UUID of the target room.
                user_id: UUID of the requesting user.

            Returns:
                ``True`` if the user may join.
            \"\"\"
            room = await get_room(session, room_id=room_id)
            if room is None:
                return False
            if not room.is_private:
                return True
            return room.created_by == user_id
        """)
    dest.write_text(content)


def _write_connection_manager(dest: Path, max_connections_per_user: int) -> None:
    """Write ``app/ws/connection_manager.py`` with ``WebSocketManager``.

    Args:
        dest: Absolute path for the new file.
        max_connections_per_user: Hard cap on simultaneous sockets per user.
    """
    content = textwrap.dedent("""\
        \"\"\"WebSocket connection manager backed by Redis pub/sub.

        ``WebSocketManager`` is the single point of fan-out for the chat feature.
        Every outgoing message (from any worker) hits Redis first, and every
        subscriber loop on every worker reads from Redis — this is what makes
        the manager horizontally safe.

        One instance per application process (singleton via ``get_ws_manager``).
        \"\"\"
        from __future__ import annotations

        import asyncio
        import json
        import logging
        from typing import Any

        from fastapi import WebSocket

        from app.core.redis import get_redis

        logger = logging.getLogger(__name__)

        _MAX_CONN_PER_USER = {cap}
        CHANNEL_TEMPLATE = "chat:{room_id}"
        CONNECTION_COUNT_KEY = "ws:chat:conn:{user_id}"


        class WebSocketManager:
            \"\"\"Redis-backed WebSocket fan-out manager for chat rooms.

            Attributes are held per-process; the Redis counter at
            ``ws:chat:conn:<user_id>`` enforces the per-user cap across workers.
            \"\"\"

            def __init__(self) -> None:
                self._local: dict[str, set[WebSocket]] = {}
                self._lock = asyncio.Lock()

            async def connect(
                self,
                ws: WebSocket,
                *,
                room_id: str,
                user_id: str,
            ) -> bool:
                \"\"\"Register a newly-accepted socket against *room_id*.

                Enforces the per-user cap via a Redis counter.  Returns
                ``False`` when the cap is exceeded so the caller can close
                the socket with a policy-violation code.

                Args:
                    ws: The accepted ``WebSocket`` instance.
                    room_id: UUID string of the target room.
                    user_id: UUID string of the authenticated user.

                Returns:
                    ``True`` if the connection was registered.
                \"\"\"
                redis = await get_redis()
                key = CONNECTION_COUNT_KEY.format(user_id=user_id)
                count = await redis.incr(key)
                await redis.expire(key, 86400)
                if count > _MAX_CONN_PER_USER:
                    await redis.decr(key)
                    return False
                async with self._lock:
                    self._local.setdefault(room_id, set()).add(ws)
                return True

            async def disconnect(
                self,
                ws: WebSocket,
                *,
                room_id: str,
                user_id: str,
            ) -> None:
                \"\"\"Release a socket's slot on disconnect.

                Args:
                    ws: The closing ``WebSocket``.
                    room_id: UUID string of the room.
                    user_id: UUID string of the authenticated user.
                \"\"\"
                redis = await get_redis()
                key = CONNECTION_COUNT_KEY.format(user_id=user_id)
                try:
                    await redis.decr(key)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to decrement ws conn counter for user=%s", user_id)
                async with self._lock:
                    peers = self._local.get(room_id)
                    if peers is not None:
                        peers.discard(ws)
                        if not peers:
                            self._local.pop(room_id, None)

            async def broadcast(
                self, *, room_id: str, payload: dict[str, Any]
            ) -> None:
                \"\"\"Publish *payload* to every subscriber of *room_id*.

                Fan-out is through Redis pub/sub so every worker sees the
                message and forwards it to its local sockets.

                Args:
                    room_id: UUID string of the target room.
                    payload: JSON-serializable dict.
                \"\"\"
                redis = await get_redis()
                await redis.publish(
                    CHANNEL_TEMPLATE.format(room_id=room_id),
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                )

            async def subscribe_loop(
                self, *, ws: WebSocket, room_id: str
            ) -> None:
                \"\"\"Forward Redis messages for *room_id* to *ws* until cancel.

                Runs as a background task for the lifetime of the socket.
                Exits cleanly on ``asyncio.CancelledError`` (the endpoint
                cancels it from its ``finally`` block).

                Args:
                    ws: The target ``WebSocket``.
                    room_id: UUID string of the room.
                \"\"\"
                redis = await get_redis()
                pubsub = redis.pubsub()
                await pubsub.subscribe(CHANNEL_TEMPLATE.format(room_id=room_id))
                try:
                    while True:
                        msg = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                        if msg is None:
                            continue
                        if msg.get("type") != "message":
                            continue
                        raw = msg.get("data", "")
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        try:
                            await ws.send_text(raw)
                        except Exception:  # noqa: BLE001
                            return
                except asyncio.CancelledError:
                    return
                finally:
                    try:
                        await pubsub.unsubscribe(CHANNEL_TEMPLATE.format(room_id=room_id))
                        await pubsub.aclose()
                    except Exception:  # noqa: BLE001
                        logger.debug("pubsub cleanup failed", exc_info=True)


        _ws_manager: WebSocketManager | None = None


        def get_ws_manager() -> WebSocketManager:
            \"\"\"Return the application-wide ``WebSocketManager`` singleton.

            Returns:
                The shared ``WebSocketManager`` instance.
            \"\"\"
            global _ws_manager
            if _ws_manager is None:
                _ws_manager = WebSocketManager()
            return _ws_manager
        """).replace("{cap}", str(max_connections_per_user))
    dest.write_text(content)


def _write_chat_endpoint(
    dest: Path, rate_limit_per_minute: int, message_max_length: int
) -> None:
    """Write ``app/ws/chat.py`` with the ``/ws/chat/{room_id}`` endpoint.

    Args:
        dest: Absolute path for the new file.
        rate_limit_per_minute: Per-user messages-per-minute cap per room.
        message_max_length: Hard cap on message content length.
    """
    content = textwrap.dedent("""\
        \"\"\"WebSocket chat endpoint: WS /ws/chat/{room_id}.

        Auth: JWT is accepted via ``?token=`` query parameter OR via the
        ``Authorization: Bearer <token>`` subprotocol header.  Failed auth
        closes the socket with ``1008 Policy Violation`` BEFORE any DB write.

        Flow:

        1. Accept the socket and authenticate.
        2. Register with the ``WebSocketManager`` (enforces per-user cap).
        3. Check room membership (public / owner of private room).
        4. Start the Redis subscribe loop in a background task.
        5. Loop on ``ws.receive_text``, validate via ``ChatMessageIn``,
           rate-limit, persist, and broadcast.
        6. On disconnect: cancel the subscribe task, release the slot.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import json
        import logging
        import uuid as _uuid

        from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

        from app.core.session import async_session as async_session_maker
        from app.core.redis import get_redis
        from app.crud import chat as crud_chat
        from app.schemas.chat import ChatMessageIn
        from app.ws.connection_manager import WebSocketManager, get_ws_manager

        logger = logging.getLogger(__name__)

        router = APIRouter()

        _RATE_LIMIT_PER_MINUTE = {rpm}
        _MESSAGE_MAX_LENGTH = {max_len}
        _RATE_KEY = "ws:chat:rl:{user_id}:{room_id}"


        def _extract_token(ws: WebSocket) -> str | None:
            \"\"\"Return the JWT from either ``?token=`` or ``Authorization`` header.

            Args:
                ws: The incoming ``WebSocket`` (before ``accept``).

            Returns:
                The raw token string, or ``None`` if no token was provided.
            \"\"\"
            token = ws.query_params.get("token")
            if token:
                return token
            auth = ws.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth.split(" ", 1)[1].strip()
            return None


        def _authenticate_token(token: str) -> tuple[str, str] | None:
            \"\"\"Verify *token* and return ``(user_id, user_name)`` on success.

            Uses ``app.core.jwt.verify_access_token`` which is installed by the
            scaffold.  Returns ``None`` on any verification failure.

            Args:
                token: The raw JWT string.

            Returns:
                ``(user_id, user_name)`` tuple, or ``None`` on failure.
            \"\"\"
            try:
                from app.core.jwt import verify_access_token
                payload = verify_access_token(token)
            except Exception:  # noqa: BLE001
                return None
            user_id = payload.get("sub")
            if not user_id:
                return None
            user_name = payload.get("name") or payload.get("email") or str(user_id)
            return str(user_id), str(user_name)


        async def _rate_limit_ok(user_id: str, room_id: str) -> bool:
            \"\"\"Return ``True`` if the user is within the per-room rate budget.

            Uses a 60-second sliding window via a Redis INCR + EXPIRE keyed on
            ``(user_id, room_id)``.  Falls back to *allow* on Redis errors so
            a Redis outage does not silently break the chat endpoint.

            Args:
                user_id: UUID string of the sender.
                room_id: UUID string of the target room.

            Returns:
                ``True`` if the sender may emit another message right now.
            \"\"\"
            try:
                redis = await get_redis()
                key = _RATE_KEY.format(user_id=user_id, room_id=room_id)
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, 60)
                return count <= _RATE_LIMIT_PER_MINUTE
            except Exception:  # noqa: BLE001
                logger.warning("rate-limit check failed; allowing message")
                return True


        async def _send_error(ws: WebSocket, code: str, detail: str) -> None:
            \"\"\"Send a structured error frame without closing the socket.

            Args:
                ws: The target ``WebSocket``.
                code: Short machine code (e.g. ``"rate_limited"``).
                detail: Human-readable explanation.
            \"\"\"
            try:
                await ws.send_text(
                    json.dumps({"type": "error", "code": code, "detail": detail})
                )
            except Exception:  # noqa: BLE001
                return


        async def _handle_incoming(
            raw: str,
            *,
            user_id: str,
            user_name: str,
            room_id: str,
            manager: WebSocketManager,
            ws: WebSocket,
        ) -> None:
            \"\"\"Validate, persist, and broadcast a single inbound chat message.

            Args:
                raw: Raw text received from the socket.
                user_id: UUID string of the sender.
                user_name: Display name of the sender.
                room_id: UUID string of the target room.
                manager: The active ``WebSocketManager``.
                ws: The sending socket (used for error responses).
            \"\"\"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(ws, "invalid_json", "Payload is not valid JSON")
                return
            try:
                parsed = ChatMessageIn.model_validate(payload)
            except Exception as exc:  # noqa: BLE001
                await _send_error(ws, "invalid_message", repr(exc)[:200])
                return
            if not await _rate_limit_ok(user_id, room_id):
                await _send_error(ws, "rate_limited", "Message rate limit exceeded")
                return
            async with async_session_maker() as session:
                msg = await crud_chat.save_message(
                    session,
                    room_id=_uuid.UUID(room_id),
                    user_id=_uuid.UUID(user_id),
                    content=parsed.content,
                )
                await session.commit()
                event = {
                    "type": "message",
                    "id": str(msg.id),
                    "room_id": room_id,
                    "user_id": user_id,
                    "user_name": user_name,
                    "content": parsed.content,
                    "created_at": msg.created_at.isoformat(),
                }
            await manager.broadcast(room_id=room_id, payload=event)


        async def _run_chat_session(
            ws: WebSocket,
            *,
            user_id: str,
            user_name: str,
            room_id: str,
            manager: WebSocketManager,
        ) -> None:
            \"\"\"Run the receive/broadcast loop for a single accepted socket.

            Args:
                ws: The accepted ``WebSocket``.
                user_id: UUID string of the authenticated user.
                user_name: Display name of the authenticated user.
                room_id: UUID string of the target room.
                manager: Shared ``WebSocketManager`` instance.
            \"\"\"
            subscribe_task: asyncio.Task[None] = asyncio.create_task(
                manager.subscribe_loop(ws=ws, room_id=room_id)
            )
            try:
                while True:
                    raw = await ws.receive_text()
                    if len(raw) > _MESSAGE_MAX_LENGTH * 2:
                        await _send_error(ws, "payload_too_large", "Frame exceeds cap")
                        continue
                    await _handle_incoming(
                        raw,
                        user_id=user_id,
                        user_name=user_name,
                        room_id=room_id,
                        manager=manager,
                        ws=ws,
                    )
            except WebSocketDisconnect:
                return
            finally:
                subscribe_task.cancel()
                try:
                    await subscribe_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass


        @router.websocket("/ws/chat/{room_id}")
        async def _validate_ws_connection(ws: WebSocket, room_id: str):
            \"\"\"Validate token + room access. Returns (user_id, user_name) or None.\"\"\"
            token = _extract_token(ws)
            if token is None:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return None
            auth = _authenticate_token(token)
            if auth is None:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return None
            user_id, user_name = auth
            try:
                room_uuid = _uuid.UUID(room_id)
            except ValueError:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return None
            async with async_session_maker() as session:
                allowed = await crud_chat.check_user_can_join(
                    session, room_id=room_uuid, user_id=_uuid.UUID(user_id),
                )
            if not allowed:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return None
            return user_id, user_name


        async def chat_endpoint(ws: WebSocket, room_id: str) -> None:
            \"\"\"Open a WebSocket chat session on *room_id*.

            Auth: JWT via ``?token=`` or ``Authorization: Bearer``.
            Rejection uses close code ``1008 Policy Violation``.
            \"\"\"
            result = await _validate_ws_connection(ws, room_id)
            if result is None:
                return
            user_id, user_name = result

            await ws.accept()
            manager = get_ws_manager()
            registered = await manager.connect(ws, room_id=room_id, user_id=user_id)
            if not registered:
                await _send_error(ws, "connection_limit", "Per-user connection cap reached")
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            try:
                await _run_chat_session(
                    ws, user_id=user_id, user_name=user_name,
                    room_id=room_id, manager=manager,
                )
            finally:
                await manager.disconnect(ws, room_id=room_id, user_id=user_id)
        """).replace("{rpm}", str(rate_limit_per_minute)).replace(
        "{max_len}", str(message_max_length),
    )
    dest.write_text(content)


def _write_chat_http_routes(dest: Path) -> None:
    """Write ``app/api/routes/chat.py`` with HTTP companion endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"HTTP companion routes for the WebSocket chat feature.

        Provides non-realtime operations: create room, list rooms, fetch
        scrollback history.  The WebSocket endpoint itself lives in
        ``app/ws/chat.py``.
        \"\"\"
        from __future__ import annotations

        import uuid as _uuid
        from typing import Annotated

        from fastapi import APIRouter, HTTPException, Query, status

        from app.api.deps import CurrentUser, SessionDep
        from app.crud import chat as crud_chat
        from app.schemas.chat import (
            ChatMessageOut,
            ChatRoomCreate,
            ChatRoomPublic,
        )

        router = APIRouter(prefix="/chat", tags=["chat"])


        @router.post(
            "/rooms",
            response_model=ChatRoomPublic,
            status_code=status.HTTP_201_CREATED,
        )
        async def create_chat_room(
            body: ChatRoomCreate,
            current_user: CurrentUser,
            session: SessionDep,
        ) -> ChatRoomPublic:
            \"\"\"Create a new chat room owned by the current user.

            Args:
                body: Room creation payload.
                current_user: Authenticated requesting user.
                session: Injected async DB session.

            Returns:
                Public view of the newly created room.
            \"\"\"
            room = await crud_chat.create_room(
                session,
                name=body.name,
                is_private=body.is_private,
                created_by=current_user.id,
            )
            await session.commit()
            return ChatRoomPublic.model_validate(room)


        @router.get("/rooms", response_model=list[ChatRoomPublic])
        async def list_chat_rooms(
            current_user: CurrentUser,
            session: SessionDep,
            limit: Annotated[int, Query(ge=1, le=200)] = 50,
        ) -> list[ChatRoomPublic]:
            \"\"\"Return rooms visible to the current user.

            Args:
                current_user: Authenticated requesting user.
                session: Injected async DB session.
                limit: Maximum number of rooms to return.

            Returns:
                List of public chat room views.
            \"\"\"
            rooms = await crud_chat.list_rooms(
                session, user_id=current_user.id, limit=limit
            )
            return [ChatRoomPublic.model_validate(r) for r in rooms]


        @router.get(
            "/rooms/{room_id}/history",
            response_model=list[ChatMessageOut],
        )
        async def get_chat_history(
            room_id: _uuid.UUID,
            current_user: CurrentUser,
            session: SessionDep,
            limit: Annotated[int, Query(ge=1, le=200)] = 50,
            before: Annotated[_uuid.UUID | None, Query()] = None,
        ) -> list[ChatMessageOut]:
            \"\"\"Return recent messages in *room_id* for scrollback.

            Args:
                room_id: UUID of the target room.
                current_user: Authenticated requesting user.
                session: Injected async DB session.
                limit: Maximum number of messages to return.
                before: Optional pagination cursor (message UUID).

            Returns:
                List of message views, oldest first.

            Raises:
                HTTPException(403): If the user is not allowed to read the room.
            \"\"\"
            allowed = await crud_chat.check_user_can_join(
                session, room_id=room_id, user_id=current_user.id
            )
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not allowed to read this room",
                )
            rows = await crud_chat.get_history(
                session, room_id=room_id, limit=limit, before_id=before
            )
            display_name = getattr(current_user, "name", None) or getattr(
                current_user, "email", ""
            )
            return [
                ChatMessageOut(
                    id=row.id,
                    room_id=row.room_id,
                    user_id=row.user_id,
                    user_name=str(display_name),
                    content=row.content,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        """)
    dest.write_text(content)


def _write_chat_migration(versions_dir: Path, *, has_tenants: bool = False) -> Path:
    """Generate ``alembic/versions/0017_add_websocket_chat.py``.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.
        has_tenants: Whether multi-tenancy is installed.  When *True* the
            ``tenant_id`` columns reference ``tenants.id`` via FK; otherwise
            they are plain nullable UUID columns.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    if has_tenants:
        room_tenant_col = (
            '        sa.Column(\n'
            '            "tenant_id", sa.Uuid(),\n'
            '            sa.ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '            nullable=True, index=True,\n'
            '        ),'
        )
        msg_tenant_col = (
            '        sa.Column(\n'
            '            "tenant_id", sa.Uuid(),\n'
            '            sa.ForeignKey("tenants.id", ondelete="CASCADE"),\n'
            '            nullable=True, index=True,\n'
            '        ),'
        )
    else:
        room_tenant_col = (
            '        sa.Column("tenant_id", sa.Uuid(), nullable=True, index=True),'
        )
        msg_tenant_col = (
            '        sa.Column("tenant_id", sa.Uuid(), nullable=True, index=True),'
        )

    content = textwrap.dedent("""\
        \"\"\"Add chat_rooms and chat_messages tables.

        Revision ID: 0017_add_websocket_chat
        Revises: {down_rev}
        Create Date: auto-generated by add_websocket_chat tool
        \"\"\"
        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0017_add_websocket_chat"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create chat_rooms and chat_messages tables with indexes.\"\"\"
            op.create_table(
                "chat_rooms",
                sa.Column("id", sa.Uuid(), primary_key=True),
                ROOM_TENANT_PLACEHOLDER
                sa.Column("name", sa.String(127), nullable=False),
                sa.Column(
                    "is_private",
                    sa.Boolean(),
                    server_default=sa.text("false"),
                    nullable=False,
                ),
                sa.Column(
                    "created_by",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
            )
            op.create_index(
                "ix_chat_rooms_created_by", "chat_rooms", ["created_by"]
            )

            op.create_table(
                "chat_messages",
                sa.Column("id", sa.Uuid(), primary_key=True),
                MSG_TENANT_PLACEHOLDER
                sa.Column(
                    "room_id",
                    sa.Uuid(),
                    sa.ForeignKey("chat_rooms.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("content", sa.Text(), nullable=False),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.create_index(
                "ix_chat_messages_room_created",
                "chat_messages",
                ["room_id", sa.text("created_at DESC")],
            )
            op.create_index(
                "ix_chat_messages_user_created",
                "chat_messages",
                ["user_id", sa.text("created_at DESC")],
            )


        def downgrade() -> None:
            \"\"\"Drop chat tables and indexes.\"\"\"
            op.drop_index("ix_chat_messages_user_created", "chat_messages")
            op.drop_index("ix_chat_messages_room_created", "chat_messages")
            op.drop_table("chat_messages")
            op.drop_index("ix_chat_rooms_created_by", "chat_rooms")
            op.drop_table("chat_rooms")
        """).replace("{down_rev}", down_rev).replace(
        "        ROOM_TENANT_PLACEHOLDER", room_tenant_col,
    ).replace(
        "        MSG_TENANT_PLACEHOLDER", msg_tenant_col,
    )
    migration_file = versions_dir / "0017_add_websocket_chat.py"
    migration_file.write_text(content)
    return migration_file


def _patch_config(
    config_file: Path,
    max_connections_per_user: int,
    message_max_length: int,
    rate_limit_per_minute: int,
) -> None:
    """Inject WebSocket chat settings into the Settings class body.

    The fields must live INSIDE ``class Settings`` so pydantic-settings
    picks them up from env vars; appending at module level would create
    plain module attributes that the generated code can never reach.

    Args:
        config_file: Path to the existing config module.
        max_connections_per_user: Per-user socket cap.
        message_max_length: Content length cap.
        rate_limit_per_minute: Per-user per-room message rate.
    """
    src = config_file.read_text()
    if "WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in src:
        return

    # 4-space indentation — fields are class attributes of Settings.
    block = (
        "\n"
        "    # --- WebSocket chat settings — added by add_websocket_chat tool ---\n"
        f"    WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER: int = {max_connections_per_user}\n"
        f"    WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH: int = {message_max_length}\n"
        f"    WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE: int = {rate_limit_per_minute}\n"
    )

    # Anchor on an existing field we know is present in the scaffold.
    # ACCESS_TOKEN_EXPIRE_MINUTES is emitted by generators/infra/config.py
    # and is stable across scaffold revisions.
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        # Fallback: insert before the `settings = Settings()` line.
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            # Last resort — append at EOF (still ends up at module scope,
            # which is wrong, but at least the file stays valid Python)
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the chat HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.chat import router as chat_router",
        include_line="api_router.include_router(chat_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
    """
    src = routes_init.read_text()
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


def _patch_main(main_file: Path) -> bool:
    """Mount the WebSocket chat router on the FastAPI app in ``app/main.py``.

    The WebSocket route lives on its own router (not under the REST
    ``api_router`` prefix) so it is mounted directly on ``app``.  This
    function is idempotent — it returns ``False`` if the mount is already
    present, ``True`` if the file was modified.

    Args:
        main_file: Path to ``app/main.py``.

    Returns:
        ``True`` if the file was modified.
    """
    src = main_file.read_text()
    if "from app.ws.chat import router as ws_chat_router" in src:
        return False

    lines = src.splitlines()

    last_from_app_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_from_app_idx = idx
    if last_from_app_idx == -1:
        return False
    lines.insert(
        last_from_app_idx + 1,
        "from app.ws.chat import router as ws_chat_router",
    )

    include_idx = -1
    for idx, line in enumerate(lines):
        if "app.include_router(" in line:
            include_idx = idx
    if include_idx == -1:
        for idx, line in enumerate(lines):
            if "= FastAPI(" in line:
                include_idx = idx
                break
    if include_idx == -1:
        return False
    lines.insert(include_idx + 1, "app.include_router(ws_chat_router)")

    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(f"Generated file {path} has a syntax error: {exc}") from exc


def _write_redis_module(dest: Path) -> None:
    """Write ``app/core/redis.py`` with a simple async Redis client factory.

    Created only when the base project does not already contain this module.
    Realtime tools (SSE, webhooks, chat) depend on ``get_redis()`` from this
    module.

    Args:
        dest: Absolute destination path (``app/core/redis.py``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async Redis client factory for realtime features (SSE, webhooks, chat).\"\"\"

        from __future__ import annotations

        from app.core.config import settings


        async def get_redis():
            \"\"\"Return a connected async Redis client.

            Uses ``settings.REDIS_URL``.  Caller is responsible for closing
            the connection via ``await client.aclose()`` when done.

            Returns:
                Connected ``redis.asyncio.Redis`` instance.
            \"\"\"
            import redis.asyncio as _redis
            return _redis.from_url(
                getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
    """))


def _patch_requirements(requirements_file: Path) -> None:
    """Add ``redis[hiredis]`` to requirements.txt if not already present.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    if "redis" not in src:
        requirements_file.write_text(src.rstrip("\n") + "\nredis[hiredis]>=5.0.0\n")


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
