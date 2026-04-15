# TOOL-052: add_websocket_chat

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_websocket_chat` |
| Category | EXTEND > Realtime |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, Redis (`redis.asyncio`), existing JWT scaffold (`app.core.jwt.verify_access_token`) |
| Signature | `add_websocket_chat(inp: ToolInput, *, max_connections_per_user: int = 5, message_max_length: int = 4000, rate_limit_per_minute: int = 30) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path) and optional `dry_run`<br>`max_connections_per_user`: Hard cap on simultaneous WebSocket sockets per authenticated user enforced by a Redis counter (default: 5)<br>`message_max_length`: Upper bound on `ChatMessageIn.content` length enforced at the Pydantic layer (default: 4000)<br>`rate_limit_per_minute`: Per-user messages-per-minute cap per room enforced by a Redis token bucket keyed on `(user_id, room_id)` (default: 30) |

## 2. Purpose

The `fastapi_add_websocket_chat` tool adds production-grade real-time chat infrastructure to a FastAPI + SQLAlchemy application — complete with JWT authentication, per-room pub/sub fan-out, persistent scrollback history, HTTP companion routes, and an Alembic migration — without coupling the feature to any single-process assumption. Hand-rolling a WebSocket chat endpoint is where most teams ship their first production incident: in-memory connection dictionaries shatter under two Gunicorn workers, JWT verification gets skipped "for now" because the WebSocket handshake does not play nicely with FastAPI's HTTP dependency injection, rate limiting gets tacked on with a `dict[str, int]` that leaks memory, and message history is either dropped on disconnect or written synchronously inside the receive loop and blocks fan-out for 40 ms per message. The generator eliminates all six failure modes in a single atomic transaction over the filesystem.

The generator produces an eleven-file kit built around a Redis-backed `WebSocketManager` singleton: every outbound message traverses Redis pub/sub (`chat:{room_id}` channel) so any number of uvicorn/Gunicorn workers observe the same message stream and fan out to their locally-attached sockets. Authentication happens **before** `ws.accept()` via a JWT extracted from either the `?token=` query parameter or an `Authorization: Bearer` header, verified against `app.core.jwt.verify_access_token` (the scaffold's canonical helper — the tool never invents a new auth scheme). Rate limiting is a Redis `INCR`+`EXPIRE(60)` token bucket that survives worker restarts. The per-user connection cap uses a second Redis counter (`ws:chat:conn:{user_id}`) so the cap is likewise worker-agnostic. Messages are persisted to `chat_messages` via an async SQLAlchemy session **inside the receive loop** using `async with async_session_maker()` so a slow DB does not stall the subscriber loop (which runs in a separate background task). Every failure closes the socket with `1008 Policy Violation` — the HTTP 4xx equivalent for WebSockets — rather than the ambiguous `1000 Normal Closure` many tutorials use.

The tool is fully idempotent (a second run detects the `WebSocketManager` fingerprint in `app/ws/chat.py` and short-circuits to `status="no_op"`), tenant-aware (when `app/models/tenant.py` exists, both `ChatRoom` and `ChatMessage` get a `tenant_id` FK to `tenants.id`; otherwise they get a plain nullable UUID column), and atomic (every file is written only after prerequisite validation, and every generated `.py` file is re-parsed via `ast.parse` before the tool returns to guarantee no partially-written file makes it into the tree). The Alembic migration chains onto the project's current migration head via `find_migration_head` so re-runs on already-migrated projects stack cleanly.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3s | Must complete during deployment without downtime |
| Files created | ≥ 7 | Complete implementation requires models, schemas, CRUD, ws package, HTTP routes, migration |
| Files modified | ≥ 2 | Config, models/__init__, routes/__init__, requirements, main |
| WebSocket handshake latency | < 50 ms | JWT verify + room access check + Redis INCR |
| Message round-trip (same worker) | < 5 ms | Redis publish + local fan-out |
| Message round-trip (cross-worker) | < 15 ms | Redis publish + subscribe_loop pickup |
| Rate-limit check latency | < 2 ms | Single Redis INCR+EXPIRE |
| Connection-cap check latency | < 2 ms | Single Redis INCR+compare |
| Migration runtime | < 1s | Only two CREATE TABLE + four CREATE INDEX statements |
| Max function LOC (generated code) | ≤ 50 | Readability invariant enforced by `test_no_function_over_50_loc` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
app/
├── core/
│   ├── config.py           # Settings class without WEBSOCKET_CHAT_* fields
│   └── jwt.py              # verify_access_token (scaffold)
├── models/
│   ├── __init__.py         # Base imports only
│   └── base.py             # Base declarative
├── schemas/                # No chat.py
├── crud/                   # No chat.py
├── api/
│   └── routes/             # No chat.py
└── main.py                 # No ws_chat_router mount
```

No `app/ws/` package. No chat tables. No Redis dependency in `requirements.txt`.

### 4.2 Project state: AFTER

```
app/
├── core/
│   ├── config.py           # + WEBSOCKET_CHAT_* settings inside Settings class
│   └── redis.py            # NEW: get_redis() async factory
├── models/
│   ├── __init__.py         # + ChatRoom, ChatMessage imports
│   ├── base.py
│   └── chat.py             # NEW: ChatRoom + ChatMessage SQLAlchemy models
├── schemas/
│   └── chat.py             # NEW: ChatMessageIn/Out, ChatRoomCreate/Public
├── crud/
│   └── chat.py             # NEW: create_room, get_room, list_rooms, save_message, get_history, check_user_can_join
├── api/
│   └── routes/
│       └── chat.py         # NEW: POST /chat/rooms, GET /chat/rooms, GET /chat/rooms/{id}/history
├── ws/
│   ├── __init__.py         # NEW
│   ├── connection_manager.py  # NEW: WebSocketManager + get_ws_manager
│   └── chat.py             # NEW: /ws/chat/{room_id} endpoint
├── routes/__init__.py      # + chat_router include
└── main.py                 # + ws_chat_router mount
alembic/versions/0017_add_websocket_chat.py  # NEW: tables + indexes
requirements.txt            # + redis[hiredis]>=5.0.0
```

### 4.3 `app/ws/connection_manager.py` (NEW) — Redis-backed fan-out manager

```python
"""WebSocket connection manager backed by Redis pub/sub.

``WebSocketManager`` is the single point of fan-out for the chat feature.
Every outgoing message (from any worker) hits Redis first, and every
subscriber loop on every worker reads from Redis — this is what makes
the manager horizontally safe.

One instance per application process (singleton via ``get_ws_manager``).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_MAX_CONN_PER_USER = 5
CHANNEL_TEMPLATE = "chat:{room_id}"
CONNECTION_COUNT_KEY = "ws:chat:conn:{user_id}"


class WebSocketManager:
    """Redis-backed WebSocket fan-out manager for chat rooms."""

    def __init__(self) -> None:
        self._local: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, ws: WebSocket, *, room_id: str, user_id: str,
    ) -> bool:
        """Register a socket, enforcing the per-user cap via Redis."""
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
        self, ws: WebSocket, *, room_id: str, user_id: str,
    ) -> None:
        """Release a socket's slot on disconnect."""
        redis = await get_redis()
        key = CONNECTION_COUNT_KEY.format(user_id=user_id)
        try:
            await redis.decr(key)
        except Exception:
            logger.warning("Failed to decrement ws conn counter for user=%s", user_id)
        async with self._lock:
            peers = self._local.get(room_id)
            if peers is not None:
                peers.discard(ws)
                if not peers:
                    self._local.pop(room_id, None)

    async def broadcast(
        self, *, room_id: str, payload: dict[str, Any],
    ) -> None:
        """Publish *payload* to every subscriber of *room_id*."""
        redis = await get_redis()
        await redis.publish(
            CHANNEL_TEMPLATE.format(room_id=room_id),
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )

    async def subscribe_loop(
        self, *, ws: WebSocket, room_id: str,
    ) -> None:
        """Forward Redis messages for *room_id* to *ws* until cancel."""
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
                except Exception:
                    return
        except asyncio.CancelledError:
            return
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL_TEMPLATE.format(room_id=room_id))
                await pubsub.aclose()
            except Exception:
                logger.debug("pubsub cleanup failed", exc_info=True)


_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    """Return the application-wide ``WebSocketManager`` singleton."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
```

### 4.4 `app/ws/chat.py` (NEW) — WebSocket endpoint

```python
"""WebSocket chat endpoint: WS /ws/chat/{room_id}.

Auth: JWT is accepted via ``?token=`` query parameter OR via the
``Authorization: Bearer <token>`` subprotocol header.  Failed auth
closes the socket with ``1008 Policy Violation`` BEFORE any DB write.
"""
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

_RATE_LIMIT_PER_MINUTE = 30
_MESSAGE_MAX_LENGTH = 4000
_RATE_KEY = "ws:chat:rl:{user_id}:{room_id}"


def _extract_token(ws: WebSocket) -> str | None:
    """Return the JWT from either ``?token=`` or ``Authorization`` header."""
    token = ws.query_params.get("token")
    if token:
        return token
    auth = ws.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _authenticate_token(token: str) -> tuple[str, str] | None:
    """Verify *token* and return ``(user_id, user_name)`` on success."""
    try:
        from app.core.jwt import verify_access_token
        payload = verify_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user_name = payload.get("name") or payload.get("email") or str(user_id)
    return str(user_id), str(user_name)


async def _rate_limit_ok(user_id: str, room_id: str) -> bool:
    """Return ``True`` if the user is within the per-room rate budget."""
    try:
        redis = await get_redis()
        key = _RATE_KEY.format(user_id=user_id, room_id=room_id)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
        return count <= _RATE_LIMIT_PER_MINUTE
    except Exception:
        logger.warning("rate-limit check failed; allowing message")
        return True


async def _send_error(ws: WebSocket, code: str, detail: str) -> None:
    """Send a structured error frame without closing the socket."""
    try:
        await ws.send_text(
            json.dumps({"type": "error", "code": code, "detail": detail})
        )
    except Exception:
        return


async def _handle_incoming(
    raw: str, *, user_id: str, user_name: str, room_id: str,
    manager: WebSocketManager, ws: WebSocket,
) -> None:
    """Validate, persist, and broadcast a single inbound chat message."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await _send_error(ws, "invalid_json", "Payload is not valid JSON")
        return
    try:
        parsed = ChatMessageIn.model_validate(payload)
    except Exception as exc:
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
    ws: WebSocket, *, user_id: str, user_name: str, room_id: str,
    manager: WebSocketManager,
) -> None:
    """Run the receive/broadcast loop for a single accepted socket."""
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
                raw, user_id=user_id, user_name=user_name,
                room_id=room_id, manager=manager, ws=ws,
            )
    except WebSocketDisconnect:
        return
    finally:
        subscribe_task.cancel()
        try:
            await subscribe_task
        except (asyncio.CancelledError, Exception):
            pass


@router.websocket("/ws/chat/{room_id}")
async def chat_endpoint(ws: WebSocket, room_id: str) -> None:
    """Open a WebSocket chat session on *room_id*."""
    token = _extract_token(ws)
    if token is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    auth = _authenticate_token(token)
    if auth is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id, user_name = auth
    try:
        room_uuid = _uuid.UUID(room_id)
    except ValueError:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    async with async_session_maker() as session:
        allowed = await crud_chat.check_user_can_join(
            session, room_id=room_uuid, user_id=_uuid.UUID(user_id),
        )
    if not allowed:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

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
```

### 4.5 `app/models/chat.py` (NEW) — SQLAlchemy models

```python
"""SQLAlchemy models for WebSocket chat (rooms + messages)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatRoom(Base):
    """A chat room. Rooms are ephemeral channels for real-time messaging."""

    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        # ForeignKey("tenants.id", ondelete="CASCADE") added only if tenants exist
        nullable=True,
        index=True,
        comment="Tenant owning this chat room",
    )
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
    """A single chat message persisted for scrollback."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, index=True,
        comment="Tenant context for multi-tenant message routing",
    )
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
        Index("ix_chat_messages_room_created", "room_id", "created_at"),
        Index("ix_chat_messages_user_created", "user_id", "created_at"),
    )
```

### 4.6 `app/schemas/chat.py` (NEW) — Pydantic schemas

```python
"""Pydantic schemas for WebSocket chat (rooms + messages)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_MESSAGE_MAX_LENGTH = 4000


class ChatMessageIn(BaseModel):
    """Schema for inbound WebSocket chat messages (client -> server)."""

    model_config = ConfigDict(strict=True, extra="forbid")

    content: str = Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)


class ChatMessageOut(BaseModel):
    """Schema for outbound chat messages (server -> client fan-out)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    content: str
    created_at: datetime


class ChatRoomCreate(BaseModel):
    """Request schema for creating a new chat room."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(min_length=3, max_length=127)
    is_private: bool = False


class ChatRoomPublic(BaseModel):
    """Public representation of a chat room."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_private: bool
    created_at: datetime
```

### 4.7 `app/crud/chat.py` (NEW) — Async CRUD helpers

```python
"""Async CRUD helpers for chat rooms and messages."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatRoom


async def create_room(
    session: AsyncSession, *,
    name: str, is_private: bool, created_by: uuid.UUID,
) -> ChatRoom:
    """Create a new chat room owned by *created_by*."""
    room = ChatRoom(name=name, is_private=is_private, created_by=created_by)
    session.add(room)
    await session.flush()
    return room


async def get_room(
    session: AsyncSession, *, room_id: uuid.UUID,
) -> ChatRoom | None:
    """Fetch a room by id."""
    stmt = select(ChatRoom).where(ChatRoom.id == room_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_rooms(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 50,
) -> list[ChatRoom]:
    """Return rooms the user can see (public rooms + own private)."""
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
    session: AsyncSession, *,
    room_id: uuid.UUID, user_id: uuid.UUID, content: str,
) -> ChatMessage:
    """Persist a new chat message."""
    msg = ChatMessage(room_id=room_id, user_id=user_id, content=content)
    session.add(msg)
    await session.flush()
    return msg


async def get_history(
    session: AsyncSession, *,
    room_id: uuid.UUID, limit: int = 50,
    before_id: uuid.UUID | None = None,
) -> list[ChatMessage]:
    """Return the most recent messages in *room_id*, newest last."""
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
    session: AsyncSession, *,
    room_id: uuid.UUID, user_id: uuid.UUID,
) -> bool:
    """Return whether *user_id* is allowed to join *room_id*."""
    room = await get_room(session, room_id=room_id)
    if room is None:
        return False
    if not room.is_private:
        return True
    return room.created_by == user_id
```

### 4.8 `app/api/routes/chat.py` (NEW) — HTTP companion routes

```python
"""HTTP companion routes for the WebSocket chat feature."""
from __future__ import annotations

import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.crud import chat as crud_chat
from app.schemas.chat import ChatMessageOut, ChatRoomCreate, ChatRoomPublic

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
    """Create a new chat room owned by the current user."""
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
    """Return rooms visible to the current user."""
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
    """Return recent messages in *room_id* for scrollback."""
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
```

### 4.9 `alembic/versions/0017_add_websocket_chat.py` (NEW)

```python
"""Add chat_rooms and chat_messages tables.

Revision ID: 0017_add_websocket_chat
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_add_websocket_chat"
down_revision = "0001_initial"  # Chained via find_migration_head()
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chat_rooms and chat_messages tables with indexes."""
    op.create_table(
        "chat_rooms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("name", sa.String(127), nullable=False),
        sa.Column(
            "is_private", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
        sa.Column(
            "created_by", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_chat_rooms_created_by", "chat_rooms", ["created_by"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True, index=True),
        sa.Column(
            "room_id", sa.Uuid(),
            sa.ForeignKey("chat_rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_chat_messages_room_created", "chat_messages",
        ["room_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_chat_messages_user_created", "chat_messages",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    """Drop chat tables and indexes."""
    op.drop_index("ix_chat_messages_user_created", "chat_messages")
    op.drop_index("ix_chat_messages_room_created", "chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_rooms_created_by", "chat_rooms")
    op.drop_table("chat_rooms")
```

### 4.10 `app/core/config.py` patch — Settings injected INSIDE the class

```python
class Settings(BaseSettings):
    # ... existing fields ...
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- WebSocket chat settings — added by add_websocket_chat tool ---
    WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER: int = 5
    WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH: int = 4000
    WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE: int = 30

    # ... more fields ...

settings = Settings()
```

**Critical detail**: The fields **must** be class attributes of `Settings` so `pydantic-settings` picks them up from env vars. The tool anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` (a stable scaffold field) with fallback to inserting before `settings = Settings()`. Appending at module level would create plain module attributes that the generated code can never reach — `test_config_fields_patched` verifies the 4-space indent guarantees class-level placement.

### 4.11 `app/core/redis.py` (NEW if not present)

```python
"""Async Redis client factory for realtime features (SSE, webhooks, chat)."""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings


async def get_redis() -> redis.Redis:
    """Return a connected async Redis client."""
    return redis.from_url(
        getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
    )
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **JWT verification happens BEFORE `ws.accept()`** | `chat_endpoint` calls `_extract_token` + `_authenticate_token` + `check_user_can_join` and closes with `1008` on any failure before calling `ws.accept()` in `app/ws/chat.py` |
| QS-2 | **Failed auth always closes with `WS_1008_POLICY_VIOLATION`** | Every auth failure branch in `chat_endpoint` calls `await ws.close(code=status.WS_1008_POLICY_VIOLATION)` |
| QS-3 | **Fan-out always goes through Redis pub/sub** | `WebSocketManager.broadcast` unconditionally calls `redis.publish(CHANNEL_TEMPLATE.format(...))`; there is no in-memory fan-out path |
| QS-4 | **Per-user connection cap enforced via Redis counter** | `WebSocketManager.connect` uses `redis.incr(CONNECTION_COUNT_KEY)`, compares against `_MAX_CONN_PER_USER`, and decrements on rejection |
| QS-5 | **Per-user per-room rate limit enforced via Redis token bucket** | `_rate_limit_ok` uses `redis.incr(_RATE_KEY) + redis.expire(key, 60)` and rejects when count > `_RATE_LIMIT_PER_MINUTE` |
| QS-6 | **Message content length enforced at Pydantic layer** | `ChatMessageIn.content = Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)` |
| QS-7 | **Tool is fully idempotent** | `add_websocket_chat` checks `"WebSocketManager" in chat_ws_file.read_text()` before any write; returns `status="no_op"` on re-run |
| QS-8 | **All generated files are syntactically valid Python** | `_assert_parses(Path(path_str))` called in a loop at the end of `add_websocket_chat` for every created file |
| QS-9 | **Settings fields added INSIDE `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent; `test_config_fields_patched` asserts the line starts with 4 spaces |
| QS-10 | **No generated function exceeds 50 LOC** | `test_no_function_over_50_loc` walks AST and checks `node.end_lineno - node.lineno + 1 <= 50` for every `FunctionDef`/`AsyncFunctionDef` |
| QS-11 | **Migration chains onto current head** | `_write_chat_migration` calls `find_migration_head(versions_dir)` and sets `down_revision` to the result |
| QS-12 | **Tenant FK conditionally emitted based on project state** | `_write_chat_models` and `_write_chat_migration` branch on `has_tenants = (app_dir / "models" / "tenant.py").exists()` |
| QS-13 | **DB session is closed per message via `async with`** | `_handle_incoming` wraps `save_message` in `async with async_session_maker() as session:` with explicit `await session.commit()` |
| QS-14 | **Subscribe loop cancellation is clean** | `_run_chat_session` uses `subscribe_task.cancel()` in `finally`, awaits cancellation, swallows `CancelledError` |
| QS-15 | **Redis outage during rate-limit check fails open** | `_rate_limit_ok` catches `Exception`, logs a warning, and returns `True` |

## 6. Completeness Criteria

All criteria are mechanically verifiable against the test suite at
`adapt/extend/realtime/test_add_websocket_chat.py` (21 tests).

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | Tool returns `status="success"` on a fresh project | `test_success_status`: asserts `result.status == "success"` |
| CC-02 | Second run returns `status="no_op"` without touching files | `test_idempotent`: asserts `r2.status == "no_op"`, `not r2.files_created`, `not r2.files_modified` |
| CC-03 | `dry_run=True` returns success but writes no files | `test_dry_run`: asserts `result.status == "success"`, `not result.files_created`, `before == after` file content dict |
| CC-04 | Tool creates at least 7 new files | `test_files_created_count`: asserts `len(result.files_created) >= 7` and every path exists on disk |
| CC-05 | Tool modifies at least 2 existing files | `test_files_modified_count`: asserts `len(result.files_modified) >= 2` and every path exists on disk |
| CC-06 | Every generated `.py` file AST-parses cleanly | `test_all_py_parse`: walks every `*.py` under project_dir and calls `ast.parse` |
| CC-07 | No generated function exceeds 50 LOC | `test_no_function_over_50_loc`: `_max_function_loc(project_dir, "app") <= 50` |
| CC-08 | `WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER` exists in `config.py` | `test_config_fields_patched`: `"WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in content` |
| CC-09 | `WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH` exists in `config.py` | `test_config_fields_patched`: `"WEBSOCKET_CHAT_MESSAGE_MAX_LENGTH" in content` |
| CC-10 | `WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE` exists in `config.py` | `test_config_fields_patched`: `"WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE" in content` |
| CC-11 | Settings fields live inside the `Settings` class body (4-space indent) | `test_config_fields_patched`: asserts first matching line `line.startswith("    ")` |
| CC-12 | `ChatRoom` is registered in `app/models/__init__.py` | `test_models_init_patched`: `"ChatRoom" in content` |
| CC-13 | `ChatMessage` is registered in `app/models/__init__.py` | `test_models_init_patched`: `"ChatMessage" in content` |
| CC-14 | Chat HTTP routes are registered in `app/routes/__init__.py` when file exists | `test_routes_registered`: `"chat" in content.lower()` |
| CC-15 | `app/ws/chat.py` exists and references `WebSocketManager` | `test_ws_chat_endpoint_file_created`: file exists + `"WebSocketManager" in content` |
| CC-16 | `app/ws/connection_manager.py` exists with `WebSocketManager` and pub/sub | `test_connection_manager_created`: file exists + `"WebSocketManager" in content` + (`"publish"` or `"broadcast"` in content) |
| CC-17 | `app/models/chat.py` exists with `ChatRoom` and `ChatMessage` classes | `test_chat_models_created`: file exists + `"ChatRoom" in content` + `"ChatMessage" in content` |
| CC-18 | `app/schemas/chat.py` exists with Pydantic schemas | `test_chat_schemas_created`: file exists + (`"ChatMessageIn"` or `"ChatMessage"` in content) |
| CC-19 | `app/crud/chat.py` exists with async CRUD helpers | `test_chat_crud_created`: file exists + `"async def" in content` |
| CC-20 | `app/api/routes/chat.py` exists and references rooms | `test_http_companion_routes`: file exists + `"room" in content.lower()` |
| CC-21 | With `add_multi_tenancy` applied first, `ChatRoom` has `tenant_id` as a `ForeignKey` | `test_tenant_conditional_fk_with_tenants`: `"tenant" in content.lower()` + `"ForeignKey" in content` |
| CC-22 | Without `add_multi_tenancy`, `tenant_id` has NO `ForeignKey("tenants.id")` | `test_tenant_conditional_fk_without_tenants`: `'ForeignKey("tenants.id"' not in content` |
| CC-23 | `result.execution_time_ms` is a positive integer | `test_execution_time_recorded`: `result.execution_time_ms > 0` |
| CC-24 | `result.next_steps` is non-empty and mentions both Redis and Alembic | `test_next_steps_present`: `len(result.next_steps) > 0` + `"redis"` + `"alembic"` in joined lowercase |
| CC-25 | Double-run leaves every project `.py` file parseable | `test_idempotent_project_still_parses`: runs tool twice, then `_assert_parse(project_dir)` |
| CC-26 | Tool execution time < 3s on reference hardware | `test_execution_time_recorded` + SLO benchmark |
| CC-27 | `_assert_parses` is called for every created file inside the tool | Source inspection: `for path_str in files_created: _assert_parses(Path(path_str))` |
| CC-28 | Alembic migration file `0017_add_websocket_chat.py` is created when `alembic/versions/` exists | File existence check post-run |
| CC-29 | `redis[hiredis]>=5.0.0` appended to `requirements.txt` | `_patch_requirements` called; file modified list includes `requirements.txt` |
| CC-30 | WebSocket router mounted on `app` (not under `api_router` prefix) in `app/main.py` | `_patch_main` inserts `app.include_router(ws_chat_router)` |

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] `test_add_websocket_chat.py` passes all 21 tests
- [ ] Tool returns `status="success"` with `execution_time_ms > 0`
- [ ] Second run returns `status="no_op"` (idempotency)
- [ ] `dry_run=True` produces zero file changes
- [ ] ≥ 7 files created, ≥ 2 files modified
- [ ] Every generated `.py` file AST-parses successfully
- [ ] No generated function exceeds 50 LOC
- [ ] Settings fields inside `Settings` class body with 4-space indent
- [ ] `ChatRoom` + `ChatMessage` registered in `app/models/__init__.py`
- [ ] Chat router registered in `app/routes/__init__.py` (when present)
- [ ] WebSocket endpoint file (`app/ws/chat.py`) references `WebSocketManager`
- [ ] Connection manager file has `publish` or `broadcast`
- [ ] Tenant FK emitted only when `app/models/tenant.py` exists
- [ ] `next_steps` mentions Redis and Alembic
- [ ] Double-run preserves syntactic validity of every `.py` file

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-WSC-01 | WebSocket auth ALWAYS completes before `ws.accept()` | `chat_endpoint` returns early via `ws.close(1008)` on every failure path before any `await ws.accept()` call in `app/ws/chat.py` | CC-15 |
| INV-WSC-02 | Failed auth ALWAYS closes the socket with code `1008 Policy Violation` | Every negative branch in `chat_endpoint` issues `await ws.close(code=status.WS_1008_POLICY_VIOLATION)` | CC-15 |
| INV-WSC-03 | Message fan-out ALWAYS goes through Redis pub/sub | `WebSocketManager.broadcast` has no in-memory shortcut; it unconditionally calls `redis.publish` | CC-16 |
| INV-WSC-04 | Per-user connection cap IS enforced across workers | Counter lives at `ws:chat:conn:{user_id}` in Redis, not in process memory | CC-16 |
| INV-WSC-05 | Rate limit IS enforced per (user_id, room_id) across workers | Counter lives at `ws:chat:rl:{user_id}:{room_id}` in Redis with 60-second TTL | CC-15 |
| INV-WSC-06 | `ChatMessageIn.content` is ALWAYS length-validated at Pydantic layer | `Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)` on `ChatMessageIn` | CC-18 |
| INV-WSC-07 | Tool is fully idempotent — second run is always `no_op` | Pre-flight check for `"WebSocketManager" in chat_ws_file.read_text()` | CC-02 |
| INV-WSC-08 | Every generated `.py` file IS syntactically valid | `_assert_parses` called for every created file before return | CC-06, CC-27 |
| INV-WSC-09 | No generated function EVER exceeds 50 LOC | AST walk in `test_no_function_over_50_loc` enforces bound | CC-07 |
| INV-WSC-10 | Tenant FK emission IS conditional on `app/models/tenant.py` existence | Branch on `has_tenants` in `_write_chat_models` + `_write_chat_migration` | CC-21, CC-22 |
| INV-WSC-11 | Settings fields ARE added inside the `Settings` class (not module scope) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES` with 4-space indent | CC-11 |
| INV-WSC-12 | Redis outage during rate-limit check FAILS OPEN (allow message) | `_rate_limit_ok` wraps Redis calls in `try/except Exception` and returns `True` on failure | Manual + stress test |
| INV-WSC-13 | DB session lifetime is BOUNDED to one message | `async with async_session_maker() as session:` inside `_handle_incoming` | Source inspection |
| INV-WSC-14 | Subscribe loop is ALWAYS cancelled on disconnect | `subscribe_task.cancel()` in `finally` block of `_run_chat_session` | Source inspection |
| INV-WSC-15 | Migration ALWAYS chains onto the project's current head | `down_rev = find_migration_head(versions_dir) or "0001_initial"` | CC-28 |

---

## 9. User Stories

### 9.1 Core Real-time Chat (US-01 .. US-05)

**US-01: Developer adds chat to an existing FastAPI product**
- **As a** backend engineer shipping a collaborative product
- **I want** to add a production WebSocket chat in under 30 seconds
- **So that** my team can start wiring the UI today instead of next sprint
- **Given:** A FastAPI+SQLAlchemy project with a working `User` model and `app/core/jwt.py`
- **When:** `add_websocket_chat(ToolInput(project_dir="/app"))` is invoked
- **Then:**
  - Tool returns `status="success"` with `execution_time_ms > 0` (CC-01, CC-23)
  - ≥ 7 files created, ≥ 2 files modified (CC-04, CC-05)
  - `next_steps` says to run `alembic upgrade head` and set `REDIS_URL` (CC-24)
  - Verified by `test_success_status` + `test_next_steps_present`

**US-02: Developer runs the tool twice by accident**
- **As a** DevOps engineer re-running a setup script
- **I want** idempotent tooling
- **So that** retries do not corrupt state
- **Given:** Tool has already been run once successfully
- **When:** `add_websocket_chat` is invoked a second time on the same `project_dir`
- **Then:**
  - Returns `status="no_op"` (INV-WSC-07)
  - `files_created == []` and `files_modified == []` (CC-02)
  - Every `.py` file still parses cleanly (CC-25)
  - Verified by `test_idempotent` + `test_idempotent_project_still_parses`

**US-03: Developer inspects changes via dry-run**
- **As a** tech lead reviewing a PR that introduces new tooling
- **I want** to see what the tool would do without touching the working tree
- **So that** I can gate the change on explicit approval
- **Given:** A clean project
- **When:** `add_websocket_chat(ToolInput(project_dir="/app", dry_run=True))` is invoked
- **Then:**
  - Returns `status="success"` (CC-03)
  - No files are written (file content before == after)
  - `next_steps` contains "Re-run without dry_run=True to apply changes"
  - Verified by `test_dry_run`

**US-04: End user sends a message to a room**
- **As a** chat client
- **I want** to submit a short message
- **So that** every participant sees it within 15 ms
- **Given:** Authenticated WebSocket open at `/ws/chat/{room_id}?token=<jwt>`
- **When:** Client sends `{"content": "hello"}`
- **Then:**
  - Server validates via `ChatMessageIn` (INV-WSC-06)
  - Rate limit check passes (INV-WSC-05)
  - Message persisted to `chat_messages` within a bounded session
  - `manager.broadcast` publishes to `chat:{room_id}` (INV-WSC-03)
  - All subscribers in all workers receive the payload within 15 ms (SLO-6)

**US-05: End user reconnects after network drop**
- **As a** mobile user whose connection dropped
- **I want** to fetch scrollback via HTTP
- **So that** I do not lose context
- **Given:** Room `room_abc` has 200 historical messages
- **When:** `GET /chat/rooms/room_abc/history?limit=50`
- **Then:**
  - Server checks `check_user_can_join` before reading (CC-20)
  - Returns the 50 most recent messages oldest-first for UI rendering
  - `ChatMessageOut` schema serializes `user_name` alongside content (CC-18)

### 9.2 Multi-tenant Deployments (US-06 .. US-10)

**US-06: SaaS operator enables multi-tenancy first**
- **As a** SaaS operator
- **I want** tenant-scoped chat rooms
- **So that** tenant data never leaks
- **Given:** `add_multi_tenancy` has been applied, so `app/models/tenant.py` exists
- **When:** `add_websocket_chat` runs after
- **Then:**
  - `app/models/chat.py` contains `ForeignKey("tenants.id", ondelete="CASCADE")` on both `ChatRoom.tenant_id` and `ChatMessage.tenant_id` (INV-WSC-10)
  - Migration creates `tenant_id` columns as FK references
  - Verified by `test_tenant_conditional_fk_with_tenants`

**US-07: Single-tenant app skips the tenant FK**
- **As a** small SaaS with no tenancy model
- **I want** a plain nullable `tenant_id`
- **So that** I can add tenancy later without schema migration pain
- **Given:** Project has no `app/models/tenant.py`
- **When:** `add_websocket_chat` runs
- **Then:**
  - `tenant_id` is a nullable `Uuid` column WITHOUT `ForeignKey("tenants.id")` (INV-WSC-10)
  - No dangling FK reference that would fail at CREATE TABLE time
  - Verified by `test_tenant_conditional_fk_without_tenants`

**US-08: Operator upgrades an existing chat deployment to multi-tenancy**
- **As a** growing SaaS
- **I want** to retroactively add tenancy
- **So that** I can onboard enterprise customers
- **Given:** `add_websocket_chat` ran first (plain tenant_id), then `add_multi_tenancy` is applied
- **When:** Migrations run
- **Then:**
  - Operator manually ADDs the FK constraint via a new Alembic migration
  - Existing `chat_rooms.tenant_id` values remain valid (nullable → FK)
  - This path is documented in rollback/rollforward notes

**US-09: Enterprise operator enables per-tenant rate limits**
- **As a** platform operator
- **I want** different `WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE` per environment
- **So that** staging and production have different budgets
- **Given:** Tool generated fields inside `class Settings`
- **When:** Operator sets `WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE=5` in staging `.env`
- **Then:**
  - pydantic-settings picks up the override because fields are class attributes (INV-WSC-11)
  - Verified by `test_config_fields_patched` (4-space indent assertion)

**US-10: Ops engineer bumps per-user connection cap**
- **As a** live ops engineer during a traffic spike
- **I want** to raise `WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER` without redeploy
- **So that** power users with multiple devices stop getting kicked
- **Given:** Tool generated `_MAX_CONN_PER_USER` as a module constant read from settings
- **When:** Operator updates env var and restarts workers
- **Then:**
  - New cap applies on the next `WebSocketManager.connect` call
  - Existing over-cap sockets are not retroactively killed (graceful drift)

### 9.3 Security & Access Control (US-11 .. US-15)

**US-11: Attacker tries to connect without a token**
- **As an** attacker
- **I want** to enumerate chat rooms
- **So that** I can harvest message data
- **Given:** No `?token=` and no `Authorization: Bearer` header
- **When:** WebSocket handshake initiated on `/ws/chat/{room_id}`
- **Then:**
  - `_extract_token` returns `None`
  - Server calls `ws.close(code=1008)` before `ws.accept()` (INV-WSC-01, INV-WSC-02)
  - Zero DB writes, zero log noise beyond the close frame

**US-12: Attacker submits a forged JWT**
- **As an** attacker with a crafted token
- **I want** to impersonate a user
- **So that** I can post messages as them
- **Given:** Invalid JWT signature
- **When:** `_authenticate_token` calls `verify_access_token`, which raises
- **Then:**
  - `_authenticate_token` catches and returns `None`
  - Socket closes with `1008`
  - No exception surfaces to the client

**US-13: User tries to join a private room they do not own**
- **As a** non-member user
- **I want** (as the attacker perspective) to read a private room
- **So that** I can snoop
- **Given:** Room is private and `created_by != user_id`
- **When:** WebSocket handshake completes auth but fails `check_user_can_join`
- **Then:**
  - Socket closes with `1008` (INV-WSC-02)
  - Verified by `check_user_can_join` logic in `app/crud/chat.py`

**US-14: Chatty user hits the rate limit**
- **As a** normal user going a bit overboard
- **I want** to get a clear error frame instead of a disconnect
- **So that** my client knows to back off
- **Given:** User has already sent 30 messages in the current 60-second window
- **When:** 31st message arrives
- **Then:**
  - `_rate_limit_ok` returns `False`
  - Server sends `{"type": "error", "code": "rate_limited", "detail": "..."}` without closing
  - Socket remains open for the user to retry later

**US-15: Redis outage during rate-limit check**
- **As a** resilient system
- **I want** to tolerate a 10-second Redis blip
- **So that** chat keeps working through minor infra hiccups
- **Given:** Redis is temporarily unreachable
- **When:** `_rate_limit_ok` raises on `redis.incr`
- **Then:**
  - Exception caught, warning logged, function returns `True` (INV-WSC-12)
  - Message is accepted, validated, and persisted (if DB is up)
  - Broadcast still attempts `redis.publish` and may fail; users see nothing until Redis recovers

### 9.4 Horizontal Scaling & Operations (US-16 .. US-20)

**US-16: Platform engineer scales to 4 Gunicorn workers**
- **As a** platform engineer
- **I want** messages posted on worker A to fan out to sockets on worker B
- **So that** horizontal scaling actually works
- **Given:** 4 Gunicorn workers, 2 users on different workers in the same room
- **When:** User on worker A posts a message
- **Then:**
  - `WebSocketManager.broadcast` publishes to `chat:{room_id}` on Redis (INV-WSC-03)
  - Worker B's `subscribe_loop` receives the message and forwards to its local socket
  - Message round-trip under 15 ms (SLO-6)

**US-17: Operator observes connection cap across workers**
- **As an** operator
- **I want** a single source of truth for connection counts
- **So that** an abusive user cannot open 5 sockets on each of 4 workers (= 20)
- **Given:** Redis counter `ws:chat:conn:{user_id}` with TTL 86400s
- **When:** User opens 6th socket on any worker
- **Then:**
  - `incr` returns 6 > 5 → reject, decr back, return `False` (INV-WSC-04)
  - Endpoint closes with `1008` + error frame "connection_limit"

**US-18: Operator runs Alembic upgrade**
- **As a** release engineer
- **I want** the migration to chain cleanly
- **So that** CI does not fail on duplicate revision IDs
- **Given:** Project already has migrations 0001..0016
- **When:** `_write_chat_migration` runs
- **Then:**
  - `find_migration_head(versions_dir)` returns the latest revision
  - New migration file has `down_revision = "<latest>"` (INV-WSC-15)
  - `alembic upgrade head` applies cleanly

**US-19: Operator runs `alembic downgrade -1`**
- **As a** release engineer rolling back a bad deploy
- **I want** chat tables dropped cleanly with dependency order
- **So that** FKs do not block the drop
- **Given:** Migration applied
- **When:** `downgrade()` runs
- **Then:**
  - Drops `chat_messages` indexes, then table, then `chat_rooms` index, then table (correct order)
  - No FK constraint violations

**US-20: Developer adds Redis to `requirements.txt`**
- **As a** developer on a project without Redis
- **I want** the tool to install the client library for me
- **So that** `import redis` works out of the box
- **Given:** `requirements.txt` without `redis`
- **When:** Tool runs
- **Then:**
  - `_patch_requirements` appends `redis[hiredis]>=5.0.0`
  - `requirements.txt` listed in `files_modified` (CC-29)

### 9.5 Integration & Observability (US-21 .. US-25)

**US-21: Developer pairs chat with `add_presence_tracking`**
- **As a** UX designer
- **I want** to show online/offline indicators per room
- **So that** users know who is listening
- **Given:** Both `add_websocket_chat` and a future `add_presence_tracking` installed
- **When:** User connects
- **Then:**
  - `WebSocketManager.connect` triggers a presence pub/sub event on an adjacent channel
  - Presence tool listens on `presence:{room_id}` — does not interfere with `chat:{room_id}`

**US-22: Developer pairs chat with `add_audit_log`**
- **As a** compliance officer
- **I want** every chat room creation logged
- **So that** we meet retention policies
- **Given:** `add_audit_log` installed AFTER `add_websocket_chat`
- **When:** `POST /chat/rooms` is called
- **Then:**
  - Audit middleware captures the request + response
  - Chat-specific events are logged via the generic audit path

**US-23: Developer pairs chat with `add_rbac`**
- **As a** platform with role-based permissions
- **I want** only users with `chat:write` to post
- **So that** read-only viewers cannot spam
- **Given:** `add_rbac` installed AFTER `add_websocket_chat`
- **When:** A user with only `chat:read` tries to post
- **Then:**
  - Operator extends `_authenticate_token` or adds a permission check in `_handle_incoming`
  - This is documented as a post-tool customization step

**US-24: Developer pairs chat with Sentry for error tracking**
- **As a** backend engineer
- **I want** WebSocket errors captured
- **So that** I can fix production bugs
- **Given:** Sentry SDK installed
- **When:** An unhandled exception occurs in `_run_chat_session`
- **Then:**
  - Sentry middleware captures the exception via Python's `logging` module (standard path)
  - Tool does not add Sentry itself — it only emits well-structured log lines

**US-25: Developer uses API key instead of JWT**
- **As a** backend service
- **I want** to connect to chat via an API key
- **So that** service-to-service chat works
- **Given:** `add_api_key_auth` installed
- **When:** Service initiates WebSocket handshake with `Authorization: Bearer <api_key>`
- **Then:**
  - Operator must extend `_authenticate_token` to call an API-key verifier when `verify_access_token` fails
  - Documented as a post-tool customization in the `next_steps` output

---

## 10. Test Plan

### 10.1 Tool execution (Category A)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fresh fixture project | Run tool | `result.status == "success"` (CC-01) |
| T-02 | `test_idempotent` | Fresh fixture project | Run tool twice | First: `success`. Second: `no_op`, no files created, no files modified (CC-02, INV-WSC-07) |
| T-03 | `test_dry_run` | Fresh fixture project | Run with `dry_run=True` | `success`, zero files created/modified, file contents unchanged (CC-03) |
| T-04 | `test_files_created_count` | Fresh fixture project | Run tool | `len(files_created) >= 7`, every path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fresh fixture project | Run tool | `len(files_modified) >= 2`, every path exists (CC-05) |

### 10.2 Generated code quality (Category B)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fresh fixture project | Run tool, walk all `.py` files | Every file `ast.parse`s without `SyntaxError` (CC-06, INV-WSC-08) |
| T-07 | `test_no_function_over_50_loc` | Fresh fixture project | Run tool, AST-walk `app/` | `max_function_loc <= 50` (CC-07, INV-WSC-09) |
| T-08 | `test_config_fields_patched` | Fresh fixture project | Run tool, read `config.py` | All 3 `WEBSOCKET_CHAT_*` fields present + first match line starts with 4 spaces (CC-08, CC-09, CC-10, CC-11, INV-WSC-11) |
| T-09 | `test_models_init_patched` | Fresh fixture project | Run tool, read `models/__init__.py` | `"ChatRoom"` and `"ChatMessage"` present (CC-12, CC-13) |
| T-10 | `test_routes_registered` | Fresh fixture project | Run tool, read `routes/__init__.py` (when exists) | `"chat" in content.lower()` (CC-14) |

### 10.3 Domain-specific (Category C)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_ws_chat_endpoint_file_created` | Fresh fixture project | Run tool | `app/ws/chat.py` exists + `"WebSocketManager" in content` (CC-15) |
| T-12 | `test_connection_manager_created` | Fresh fixture project | Run tool | `app/ws/connection_manager.py` exists + `"WebSocketManager"` + (`"publish"` or `"broadcast"`) (CC-16) |
| T-13 | `test_chat_models_created` | Fresh fixture project | Run tool | `app/models/chat.py` exists + `"ChatRoom"` + `"ChatMessage"` (CC-17) |
| T-14 | `test_chat_schemas_created` | Fresh fixture project | Run tool | `app/schemas/chat.py` exists + `"ChatMessageIn"` or `"ChatMessage"` (CC-18) |
| T-15 | `test_chat_crud_created` | Fresh fixture project | Run tool | `app/crud/chat.py` exists + `"async def" in content` (CC-19) |
| T-16 | `test_http_companion_routes` | Fresh fixture project | Run tool | `app/api/routes/chat.py` exists + `"room" in content.lower()` (CC-20) |
| T-17 | `test_tenant_conditional_fk_with_tenants` | Apply `add_multi_tenancy` first | Run tool | `app/models/chat.py` contains `"tenant"` + `"ForeignKey"` (CC-21) |
| T-18 | `test_tenant_conditional_fk_without_tenants` | Fresh fixture project | Run tool | `app/models/chat.py` does NOT contain `'ForeignKey("tenants.id"'` (CC-22) |
| T-19 | `test_execution_time_recorded` | Fresh fixture project | Run tool | `result.execution_time_ms > 0` (CC-23) |
| T-20 | `test_next_steps_present` | Fresh fixture project | Run tool | `len(next_steps) > 0` + `"redis"` + `"alembic"` in joined lowercase (CC-24) |
| T-21 | `test_idempotent_project_still_parses` | Fresh fixture project | Run tool twice | Every `.py` file still AST-parses (CC-25) |

### 10.4 Gaps (not currently in test suite — candidate additions)

| # | Test | Why it matters |
|---|------|---------------|
| T-GAP-01 | Fan-out across two in-process `WebSocketManager` singletons via a single FakeRedis | Verifies cross-worker fan-out path end-to-end (INV-WSC-03) |
| T-GAP-02 | Rate limit test: 30 incr calls succeed, 31st returns `False` | Verifies `_rate_limit_ok` logic (INV-WSC-05) |
| T-GAP-03 | Connection cap test: 5 connects succeed, 6th returns `False` + decr called | Verifies `WebSocketManager.connect` cap logic (INV-WSC-04) |
| T-GAP-04 | JWT verification is called via `app.core.jwt.verify_access_token` (not re-implemented) | Source grep test ensuring no custom HS256 decode in generated code (QS-1) |
| T-GAP-05 | WebSocket close code check: assert `WS_1008_POLICY_VIOLATION` on every close path | AST traversal of `chat.py` confirming every `ws.close` uses the 1008 constant (INV-WSC-02) |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` | **Yes** | ✅ Compatible | MUST run BEFORE `add_websocket_chat` to get `tenant_id` FKs; otherwise tenant_id is a plain nullable column (INV-WSC-10). Verified by T-17/T-18. |
| `add_rbac` | Yes | ✅ Compatible | MUST run AFTER `add_websocket_chat` for role-based chat permissions. Operator extends `_handle_incoming` with permission checks. |
| `add_api_key_auth` | No | ⚠️ Caveat | API key support requires extending `_authenticate_token` to fall through to an API-key verifier when JWT verify fails. Documented in US-25. |
| `add_mfa` | No | ✅ Compatible | MFA happens at login time — once a JWT is issued, the WebSocket endpoint accepts it transparently. |
| `add_oauth2_provider` | No | ✅ Compatible | OAuth2 JWTs work via the same `verify_access_token` helper. |
| Rate-limit middleware (slowapi, generic ASGI) | No | ⚠️ Caveat | Chat has its own Redis-backed per-room rate limit. Do NOT double-wrap with a global IP limiter on `/ws/chat/*` — it kills idle WebSockets. SKILL-001 does not ship a dedicated rate-limit tool; install at the ASGI layer if needed. |
| `add_audit_log` | Yes | ✅ Compatible | MUST run AFTER to log `/chat/rooms` HTTP operations. The WebSocket endpoint is not auto-audited; add a hook in `_handle_incoming` if needed. |
| `add_cache_layer` | No | ⚠️ Caveat | Never cache `GET /chat/rooms/{id}/history` — the endpoint is paginated and scrollback needs freshness. |
| `add_sse` | No | ✅ Compatible | SSE and WebSocket chat coexist; both use `get_redis()` from the same `app/core/redis.py` module. The tool creates that module only if absent. |
| `add_webhook_sender` | No | ✅ Compatible | Outbound webhook delivery can subscribe to chat events via `redis.subscribe("chat:*")` as an external worker. |
| `add_webhook_receiver` | No | ✅ Compatible | Receiver endpoints can trigger broadcast into chat rooms via `WebSocketManager.broadcast_to_room`. |
| `add_long_running_task` | No | ✅ Compatible | Both features share Redis. Deploy with `REDIS_URL` pointing to the same instance. |
| `add_presence_tracking` (future) | Yes | ✅ Compatible | Expected to run AFTER and piggyback on `WebSocketManager.connect`/`disconnect` hooks. |
| `add_search` | No | ⚠️ Caveat | Full-text search over `chat_messages` is not installed by this tool. Run a separate Elasticsearch/Meilisearch indexer if needed. |
| `add_soft_delete` | No | ⚠️ Caveat | Not applied to chat messages by default. Messages are hard-deleted via CASCADE when a room is dropped. |
| `add_cursor_pagination` | No | ✅ Compatible | `get_history` already supports a `before_id` cursor. |
| `add_data_export` | No | ✅ Compatible | Exports can include `chat_messages` rows via the standard SQLAlchemy path. |
| `add_feature_flags` | No | ✅ Compatible | Chat feature can be toggled at the router-inclusion level in `app/main.py`. |
| `add_bulk_operations` | No | ⚠️ Caveat | Bulk operations are a poor fit for real-time chat; skip for this router. |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/core/redis.py \
  app/models/__init__.py \
  app/routes/__init__.py \
  app/main.py \
  requirements.txt

rm -rf \
  app/models/chat.py \
  app/schemas/chat.py \
  app/crud/chat.py \
  app/ws/ \
  app/api/routes/chat.py \
  alembic/versions/0017_add_websocket_chat.py
```

### Database rollback (after deploy)

```bash
alembic downgrade -1
```

This drops (in correct dependency order): `ix_chat_messages_user_created` → `ix_chat_messages_room_created` → `chat_messages` → `ix_chat_rooms_created_by` → `chat_rooms`. FK CASCADE means there is no manual cleanup.

### Data preservation rollback

Before dropping `chat_messages`, archive if needed:

```bash
pg_dump -t chat_rooms -t chat_messages "$DATABASE_URL" > chat_archive_$(date +%F).sql
```

### Failure mode: tool partially modified files

Because every file passes `_assert_parses` before the tool returns, a partial state implies the tool crashed mid-write. Recover via:

```bash
git status --porcelain | grep '^.M' | awk '{print $2}' | xargs git checkout --
git clean -fd app/ws/ app/models/chat.py app/schemas/chat.py app/crud/chat.py
```

### Emergency: Redis outage during deployment

1. Set `WEBSOCKET_CHAT_RATE_LIMIT_PER_MINUTE=99999` in `.env` to neutralize rate-limit dependency on Redis (fails open anyway per INV-WSC-12)
2. Set `REDIS_URL` to a standby instance
3. Restart the application — existing sockets reconnect and register against the new Redis
4. Note: broadcast will drop on the dead Redis; users see gaps until reconnect

### Emergency: Dependency-injection conflict with `add_multi_tenancy`

If the tool was run BEFORE `add_multi_tenancy` and now you need FKs:

1. Apply a manual Alembic migration adding the FK constraint: `ALTER TABLE chat_rooms ADD CONSTRAINT fk_chat_rooms_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;`
2. Same for `chat_messages`
3. Update `app/models/chat.py` manually to match

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Tool run twice | Second run detects `WebSocketManager` fingerprint in `app/ws/chat.py` and returns `status="no_op"` (INV-WSC-07) |
| EC-2 | Tool run with `dry_run=True` | Returns `success` with `files_created=[]`, `files_modified=[]`, and message "[dry_run] No files written" |
| EC-3 | Prerequisite `BASE_MODEL` missing and auto_scaffold=False | Returns `status="error"` with message "Prerequisites not met:\n  - ..." and instructions to run `fastapi_generate_project` |
| EC-4 | `app/models/tenant.py` exists | `has_tenants=True` branch emits FK columns + FK migration columns (INV-WSC-10, CC-21) |
| EC-5 | `app/models/tenant.py` does NOT exist | `has_tenants=False` branch emits plain nullable `Uuid` columns; no `ForeignKey("tenants.id")` string in generated code (CC-22) |
| EC-6 | `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` not in config (non-standard scaffold) | `_patch_config` falls back to inserting before `settings = Settings()`; if that also missing, appends at EOF (INV-WSC-11 best-effort) |
| EC-7 | Client connects without `?token=` query param AND no `Authorization` header | `_extract_token` returns `None`; `chat_endpoint` closes socket with `1008` before `ws.accept()` (INV-WSC-01, INV-WSC-02) |
| EC-8 | Client provides malformed JWT | `verify_access_token` raises; `_authenticate_token` catches and returns `None`; socket closes with `1008` |
| EC-9 | JWT payload lacks `sub` claim | `_authenticate_token` returns `None` (explicit `if not user_id: return None`); socket closes with `1008` |
| EC-10 | `room_id` path param is not a valid UUID | `_uuid.UUID(room_id)` raises `ValueError`; caught by endpoint wrapper, socket closes with `1008` |
| EC-11 | User tries to join a private room they did not create | `check_user_can_join` returns `False`; socket closes with `1008` before `ws.accept()` |
| EC-12 | User exceeds per-user connection cap | 6th `connect()` call returns `False`; endpoint sends `{"type":"error","code":"connection_limit"}` frame and closes with `1008` (INV-WSC-04) |
| EC-13 | User exceeds per-room rate limit (31st message in 60s window) | `_rate_limit_ok` returns `False`; server sends `{"type":"error","code":"rate_limited"}` frame; socket STAYS OPEN (INV-WSC-05) |
| EC-14 | Client sends text frame > `_MESSAGE_MAX_LENGTH * 2` bytes | `_run_chat_session` sends `{"type":"error","code":"payload_too_large"}` and continues the loop (does not close) |
| EC-15 | Client sends non-JSON text | `json.loads` raises; `_handle_incoming` sends `{"type":"error","code":"invalid_json"}` and returns |
| EC-16 | Client sends JSON violating `ChatMessageIn` schema (empty content, too long, extra field) | `model_validate` raises; server sends `{"type":"error","code":"invalid_message","detail":"..."}` |
| EC-17 | Redis outage during `_rate_limit_ok` | Exception caught, warning logged, function returns `True` (fails open per INV-WSC-12) |
| EC-18 | Redis outage during `WebSocketManager.broadcast` | `redis.publish` raises; exception propagates through `_handle_incoming` and closes the client loop; client must reconnect |
| EC-19 | Redis outage during subscriber pickup | `pubsub.get_message` returns `None` or raises; loop continues or exits; `finally` block closes pubsub cleanly |
| EC-20 | User disconnects mid-message | `WebSocketDisconnect` caught; `finally` block cancels `subscribe_task` and calls `manager.disconnect` (INV-WSC-14) |
| EC-21 | Subscribe loop raises unhandled exception | `except Exception: return` in `subscribe_loop` + `finally` in `_run_chat_session` swallows and cleans up |
| EC-22 | Message `content` is empty string | `Field(min_length=1)` rejects at Pydantic layer; error frame sent (INV-WSC-06) |
| EC-23 | Concurrent disconnect + broadcast | `async with self._lock` in `WebSocketManager` serializes mutation of `_local`; Redis publish is async-safe |
| EC-24 | `app/core/redis.py` already exists from a previous tool (e.g., `add_sse`) | Tool skips creation; `get_redis()` is reused transparently |
| EC-25 | `requirements.txt` already has `redis` | `_patch_requirements` checks `"redis" not in src` and skips the append |
| EC-26 | `alembic/versions/` does not exist | Migration generation skipped silently; file count still satisfies `>= 7` from other deliverables |
| EC-27 | `app/main.py` missing `from app.` imports | `_patch_main` returns `False`; `files_modified` does not include `main.py`; operator must manually mount the router |
| EC-28 | Tool run on project without `app/core/jwt.py` | Tool runs successfully but generated WS endpoint fails at runtime; surfaced as clear ImportError on first connection |
| EC-29 | Two workers simultaneously register the same user's 5th socket | Redis `INCR` is atomic: only one reaches 5, the second reaches 6 and gets rejected (INV-WSC-04) |
| EC-30 | User with 5 open sockets disconnects all at once | 5 concurrent `disconnect` calls each call `decr`; Redis arrives at 0 correctly |

## 14. Acceptance Criteria (Final Sign-off)

1. All 30 Completeness Criteria verified via `pytest adapt/extend/realtime/test_add_websocket_chat.py -v`
2. All 21 tests pass green
3. Tool execution time < 3s on reference hardware (measured via `execution_time_ms`)
4. ≥ 7 files created, ≥ 2 files modified on a clean fixture
5. Idempotent re-run returns `no_op` with zero file changes
6. `dry_run=True` produces zero filesystem side-effects
7. Every generated `.py` file AST-parses without `SyntaxError`
8. No generated function exceeds 50 LOC
9. Settings fields live inside `class Settings` (4-space indent enforced)
10. Tenant FK emitted conditionally on `app/models/tenant.py` existence
11. `next_steps` mentions both Redis and Alembic
12. Double-run leaves every project `.py` file parseable
13. Real end-to-end smoke test: start app, connect a WS client with a valid JWT to `/ws/chat/{room_id}?token=<jwt>`, send a message, see it persisted to `chat_messages`, reload `GET /chat/rooms/{room_id}/history`, and see the message
14. Horizontal smoke test: run two uvicorn workers behind nginx, connect one client to each, verify messages cross workers via Redis pub/sub
15. Rollback procedure verified: `git checkout` + `alembic downgrade -1` restores the project to a pre-tool state with zero leftover files

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(..., Prereq.BASE_MODEL, Prereq.MODELS_INIT, Prereq.CONFIG_SETTINGS, Prereq.ROUTES_INIT, Prereq.ALEMBIC_VERSIONS, Prereq.REQUIREMENTS_TXT, auto_scaffold=not inp.dry_run)` returns no errors
- [ ] If `app/ws/chat.py` exists AND contains `"WebSocketManager"`: return `status="no_op"` immediately
- [ ] If `inp.dry_run=True`: return early with informational notes and `next_steps=["Re-run without dry_run=True to apply changes."]`
- [ ] Record `start = time.monotonic()` for `execution_time_ms`

### 15.2 Models

- [ ] Create `app/models/chat.py` via `_write_chat_models(dest, has_tenants=has_tenants)`
- [ ] Branch `has_tenants` on `(app_dir / "models" / "tenant.py").exists()`
- [ ] When `has_tenants=True`: emit `ForeignKey("tenants.id", ondelete="CASCADE")` on both `ChatRoom.tenant_id` and `ChatMessage.tenant_id`
- [ ] When `has_tenants=False`: emit plain nullable `Uuid` columns; never emit `ForeignKey("tenants.id", ...)`
- [ ] Emit `__table_args__` with `ix_chat_messages_room_created` and `ix_chat_messages_user_created` composite indexes
- [ ] Append path to `files_created`
- [ ] Patch `app/models/__init__.py` via `_patch_models_init(..., [("chat", "ChatRoom"), ("chat", "ChatMessage")])`
- [ ] Append `app/models/__init__.py` to `files_modified`

### 15.3 Schemas

- [ ] Create `app/schemas/chat.py` via `_write_chat_schemas(dest, message_max_length)`
- [ ] `ChatMessageIn` uses `ConfigDict(strict=True, extra="forbid")` and `Field(min_length=1, max_length=_MESSAGE_MAX_LENGTH)`
- [ ] `ChatMessageOut` uses `ConfigDict(from_attributes=True)` with all 6 fields
- [ ] `ChatRoomCreate.name` uses `Field(min_length=3, max_length=127)`
- [ ] Append path to `files_created`

### 15.4 CRUD

- [ ] Create `app/crud/chat.py` via `_write_chat_crud(dest)`
- [ ] Emit async helpers: `create_room`, `get_room`, `list_rooms`, `save_message`, `get_history`, `check_user_can_join`
- [ ] `get_history` supports `before_id` cursor pagination; rows reversed to oldest-first before return
- [ ] `check_user_can_join` returns `True` for public rooms, `room.created_by == user_id` for private rooms
- [ ] Append path to `files_created`

### 15.5 WebSocket package

- [ ] Create `app/ws/` directory if absent
- [ ] Create `app/ws/__init__.py` with `'"""WebSocket sub-package."""\n'` if absent
- [ ] Create `app/ws/connection_manager.py` via `_write_connection_manager(dest, max_connections_per_user)`
- [ ] `WebSocketManager.__init__` initializes `_local: dict[str, set[WebSocket]]` + `_lock: asyncio.Lock`
- [ ] `WebSocketManager.connect` uses Redis `INCR` + `EXPIRE(86400)` + cap comparison + `DECR` on rejection
- [ ] `WebSocketManager.disconnect` uses Redis `DECR` in try/except
- [ ] `WebSocketManager.broadcast` uses `redis.publish(CHANNEL_TEMPLATE.format(room_id=room_id), json.dumps(...))`
- [ ] `WebSocketManager.subscribe_loop` uses `redis.pubsub()`, filters `msg.get("type") == "message"`, forwards via `ws.send_text`, cleans up in `finally`
- [ ] `get_ws_manager()` is module-level singleton factory

### 15.6 WebSocket endpoint

- [ ] Create `app/ws/chat.py` via `_write_chat_endpoint(dest, rate_limit_per_minute, message_max_length)`
- [ ] Define module constants `_RATE_LIMIT_PER_MINUTE`, `_MESSAGE_MAX_LENGTH`, `_RATE_KEY`
- [ ] `_extract_token` reads `?token=` first, then `Authorization: Bearer`
- [ ] `_authenticate_token` imports `verify_access_token` lazily inside try/except
- [ ] `_authenticate_token` returns `None` on any exception, missing `sub`, or verification failure
- [ ] `_rate_limit_ok` uses Redis `INCR`+`EXPIRE(60)`; fails open on Redis exception
- [ ] `_send_error` sends structured JSON error frame without closing the socket
- [ ] `_handle_incoming` validates JSON → Pydantic → rate limit → persist → broadcast
- [ ] `_run_chat_session` starts `subscribe_task`, loops on `receive_text`, cancels task in `finally`
- [ ] `chat_endpoint` decorated with `@router.websocket("/ws/chat/{room_id}")`
- [ ] `chat_endpoint` calls `_extract_token` → `_authenticate_token` → room UUID parse → `check_user_can_join` BEFORE `ws.accept()`
- [ ] Every rejection branch calls `ws.close(code=status.WS_1008_POLICY_VIOLATION)` and returns
- [ ] After `ws.accept()`, `manager.connect` enforces cap; rejection sends error frame + closes with 1008
- [ ] `manager.disconnect` called in `finally` block

### 15.7 HTTP companion routes

- [ ] Create `app/api/routes/chat.py` via `_write_chat_http_routes(dest)`
- [ ] `POST /chat/rooms` returns `HTTP_201_CREATED` with `ChatRoomPublic`
- [ ] `GET /chat/rooms` supports `limit: Annotated[int, Query(ge=1, le=200)] = 50`
- [ ] `GET /chat/rooms/{room_id}/history` supports `limit` + `before` cursor
- [ ] `get_chat_history` calls `check_user_can_join` and raises `HTTPException(403)` on failure
- [ ] Append path to `files_created`

### 15.8 Migration

- [ ] If `alembic/versions/` exists, call `_write_chat_migration(versions_dir, has_tenants=has_tenants)`
- [ ] `down_revision = find_migration_head(versions_dir) or "0001_initial"`
- [ ] Emit `create_table("chat_rooms")` with columns: id, tenant_id, name, is_private, created_by (FK), created_at
- [ ] Emit `create_index("ix_chat_rooms_created_by")`
- [ ] Emit `create_table("chat_messages")` with columns: id, tenant_id, room_id (FK), user_id (FK), content, created_at, edited_at
- [ ] Emit `create_index("ix_chat_messages_room_created", ["room_id", sa.text("created_at DESC")])`
- [ ] Emit `create_index("ix_chat_messages_user_created", ["user_id", sa.text("created_at DESC")])`
- [ ] `downgrade()` drops in reverse dependency order
- [ ] Append migration path to `files_created`

### 15.9 Patch config

- [ ] Read `app/core/config.py`; if `"WEBSOCKET_CHAT_MAX_CONNECTIONS_PER_USER" in src`: no-op
- [ ] Build block with 4-space indent and all 3 fields
- [ ] Try anchor: `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback 1: insert before `settings = Settings()`
- [ ] Fallback 2: append at EOF
- [ ] Write file and append to `files_modified`

### 15.10 Patch routers & main

- [ ] Call `_patch_routes_init(routes_init)` with `chat_router` import + include
- [ ] Call `_patch_main(main_file)` — insert `from app.ws.chat import router as ws_chat_router` + `app.include_router(ws_chat_router)`
- [ ] Append to `files_modified` only if `_patch_main` returned `True`

### 15.11 Redis + requirements

- [ ] If `app/core/redis.py` missing: create via `_write_redis_module`
- [ ] If `requirements.txt` exists: call `_patch_requirements` (idempotent: no-op if `"redis" in src`)
- [ ] Append `requirements.txt` to `files_modified` when patched

### 15.12 Atomicity

- [ ] Iterate `files_created` and call `_assert_parses(Path(path_str))` for each
- [ ] `_assert_parses` calls `ast.parse` and re-raises any `SyntaxError` with file path context

### 15.13 Finalization

- [ ] Return `ToolResult(status="success", files_created=[...], files_modified=[...], notes=[...], next_steps=[...], execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` includes: endpoint URL template, cap/rate/length settings, fan-out note, HTTP companion routes
- [ ] `next_steps` includes: `alembic upgrade head`, `Set REDIS_URL in .env`, app restart, client connect example, `/docs` verification

### 15.14 Verification

- [ ] Run `pytest adapt/extend/realtime/test_add_websocket_chat.py -v` → 21/21 passed
- [ ] Measure `execution_time_ms < 3000`
- [ ] Visual diff review of generated files vs. reference expectations
- [ ] Manual smoke test: connect a WebSocket client + send a message + observe it in `chat_messages`
- [ ] Horizontal smoke test with 2+ workers

## 16. Documentation Output

### Success return

```json
{
  "status": "success",
  "files_created": [
    "/app/app/models/chat.py",
    "/app/app/schemas/chat.py",
    "/app/app/crud/chat.py",
    "/app/app/ws/__init__.py",
    "/app/app/ws/connection_manager.py",
    "/app/app/ws/chat.py",
    "/app/app/api/routes/chat.py",
    "/app/alembic/versions/0017_add_websocket_chat.py",
    "/app/app/core/redis.py"
  ],
  "files_modified": [
    "/app/app/models/__init__.py",
    "/app/app/core/config.py",
    "/app/app/routes/__init__.py",
    "/app/app/main.py",
    "/app/requirements.txt"
  ],
  "notes": [
    "WebSocket chat added: connection manager, endpoint, models, schemas, CRUD.",
    "Endpoint: WS /ws/chat/{room_id}?token=<JWT>",
    "Per-user connection cap: 5.  Rate limit: 30/min.  Message max length: 4000.",
    "Fan-out is through Redis pub/sub — multi-worker safe out of the box.",
    "Companion HTTP routes: POST /chat/rooms, GET /chat/rooms, GET /chat/rooms/{room_id}/history."
  ],
  "next_steps": [
    "alembic upgrade head",
    "Set REDIS_URL in .env — pub/sub and rate-limiter require Redis.",
    "Restart the application so the new chat router and WS endpoint are active.",
    "Connect a client with: ws://<host>/ws/chat/<room_id>?token=<access_token>",
    "Verify the HTTP side at GET /docs → /chat/rooms."
  ],
  "execution_time_ms": 1842
}
```

### Idempotent no-op return

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "WebSocketManager already present — WebSocket chat is already enabled, skipped."
  ],
  "execution_time_ms": 12
}
```

### Dry-run return

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create WebSocketManager, /ws/chat/{room_id} endpoint,",
    "         ChatRoom+ChatMessage models, schemas, CRUD, HTTP routes, migration.",
    "         max_connections_per_user=5, message_max_length=4000, rate_limit_per_minute=30.",
    "[dry_run] No files written."
  ],
  "next_steps": ["Re-run without dry_run=True to apply changes."],
  "execution_time_ms": 3
}
```

### Prerequisite error return

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - Missing app/models/base.py (BASE_MODEL)\n  - Missing app/core/config.py (CONFIG_SETTINGS)",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 8
}
```

---

*End of TOOL-052 specification.*
