"""
SKILL-001 WebSocket Tool: Generate production WebSocket infrastructure for FastAPI.

Creates a complete WebSocket module with JWT auth on connect, connection manager
with rooms, Redis pub/sub for multi-worker broadcast, heartbeat/ping-pong,
Pydantic message validation, connection limiting, and graceful shutdown.
All generated code follows KNOWLEDGE.md patterns.

Generated files:
    ws/__init__.py          -- package marker with re-exports
    ws/manager.py           -- ConnectionManager with rooms, broadcast, limits
    ws/auth.py              -- JWT validation for WS connections (query param)
    ws/schemas.py           -- Pydantic models for WS messages
    ws/endpoint.py          -- WebSocket endpoint with full lifecycle
    ws/redis_pubsub.py      -- Redis pub/sub bridge for multi-worker (optional)
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.models import Finding, Severity


# ---------------------------------------------------------------------------
# File templates
# ---------------------------------------------------------------------------


def _init_py() -> str:
    return textwrap.dedent("""\
        \"\"\"WebSocket module — production real-time communication for FastAPI.\"\"\"

        from .manager import ConnectionManager
        from .endpoint import websocket_endpoint

        __all__ = ["ConnectionManager", "websocket_endpoint"]
    """)


def _schemas_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Pydantic models for WebSocket message validation.

        All incoming messages are validated against WSIncoming before processing.
        All outgoing messages are serialized from WSOutgoing for consistency.
        \"\"\"

        from __future__ import annotations

        import time
        from enum import Enum

        from pydantic import BaseModel, Field


        class WSAction(str, Enum):
            \"\"\"Actions the client can send.\"\"\"
            SUBSCRIBE = "subscribe"
            UNSUBSCRIBE = "unsubscribe"
            MESSAGE = "message"
            TYPING = "typing"
            PONG = "pong"


        class WSIncoming(BaseModel):
            \"\"\"Schema for all incoming WebSocket messages.

            Validates action, room name format, and optional payload.
            Rejects messages that don't match this schema.
            \"\"\"
            action: WSAction
            room: str = Field(
                max_length=64,
                pattern=r"^[a-zA-Z0-9_-]+$",
                description="Room name (alphanumeric, dashes, underscores)",
            )
            payload: dict | None = None


        class WSOutgoing(BaseModel):
            \"\"\"Schema for all outgoing WebSocket messages.\"\"\"
            event: str
            room: str | None = None
            data: dict = Field(default_factory=dict)
            timestamp: float = Field(default_factory=time.time)
            sender: str | None = None
    """)


def _auth_py(with_auth: bool) -> str:
    if not with_auth:
        return textwrap.dedent("""\
            \"\"\"WebSocket auth — disabled (no authentication).\"\"\"

            from __future__ import annotations
            from fastapi import WebSocket


            async def authenticate_ws(websocket: WebSocket, token: str | None) -> dict | None:
                \"\"\"No authentication. Returns a default payload.\"\"\"
                return {"sub": "anonymous", "type": "access"}
        """)

    return textwrap.dedent("""\
        \"\"\"WebSocket authentication — JWT validation on connect.

        The browser WebSocket API does not support custom Authorization headers.
        Token is passed as a query parameter: ws://host/ws?token=<jwt>

        For production, use short-lived (60s) single-use WS tickets:
        1. Client calls POST /ws/ticket (authenticated HTTP endpoint)
        2. Server returns a one-time WS token valid for 60 seconds
        3. Client connects with ws://host/ws?token=<ws_ticket>
        \"\"\"

        from __future__ import annotations

        import logging

        import jwt
        from fastapi import WebSocket

        logger = logging.getLogger("ws.auth")

        # IMPORTANT: Load from environment in production — NEVER hardcode.
        SECRET_KEY: str = ""
        ALGORITHM = "HS256"


        def configure_ws_auth(secret: str) -> None:
            \"\"\"Set the JWT secret at startup. Called from app lifespan.\"\"\"
            global SECRET_KEY
            SECRET_KEY = secret


        async def authenticate_ws(websocket: WebSocket, token: str | None) -> dict | None:
            \"\"\"Validate JWT token for WebSocket connection.

            Args:
                websocket: The WebSocket connection (for logging/headers).
                token: JWT token from query parameter.

            Returns:
                Token payload dict if valid, None if invalid/missing.
            \"\"\"
            if not token:
                logger.warning("WebSocket connection attempt without token")
                return None

            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                if payload.get("type") != "access":
                    logger.warning(f"WebSocket token is not an access token: {payload.get('type')}")
                    return None
                return payload
            except jwt.ExpiredSignatureError:
                logger.warning("WebSocket token has expired")
                return None
            except jwt.InvalidTokenError as exc:
                logger.warning(f"Invalid WebSocket token: {exc}")
                return None
    """)


def _manager_py(with_rooms: bool) -> str:
    room_methods = ""
    if with_rooms:
        room_methods = textwrap.dedent("""\

            def connect(self, user_id: str, room: str, websocket: WebSocket) -> None:
                \"\"\"Add a user to a room.\"\"\"
                if room not in self._rooms:
                    self._rooms[room] = {}
                self._rooms[room][user_id] = websocket
                self._user_rooms.setdefault(user_id, set()).add(room)
                self._user_connections.setdefault(user_id, []).append(websocket)
                ip = self._get_ip(websocket)
                self._ip_counts[ip] = self._ip_counts.get(ip, 0) + 1
                logger.info(f"User {user_id} joined room {room}")

            def disconnect(self, user_id: str, room: str | None = None) -> None:
                \"\"\"Remove a user from a room (or all rooms if room is None).\"\"\"
                if room:
                    rooms_to_leave = [room]
                else:
                    rooms_to_leave = list(self._user_rooms.get(user_id, set()))

                for r in rooms_to_leave:
                    ws = self._rooms.get(r, {}).pop(user_id, None)
                    if not self._rooms.get(r):
                        self._rooms.pop(r, None)
                    self._user_rooms.get(user_id, set()).discard(r)
                    # Decrement IP count
                    if ws:
                        ip = self._get_ip(ws)
                        self._ip_counts[ip] = max(0, self._ip_counts.get(ip, 1) - 1)

                if not room:
                    self._user_connections.pop(user_id, None)
                    self._user_rooms.pop(user_id, None)
                logger.info(f"User {user_id} left {'room ' + room if room else 'all rooms'}")

            async def broadcast_to_room(
                self, room: str, message: dict, exclude: str | None = None,
            ) -> None:
                \"\"\"Send message to all users in a room (local connections only).\"\"\"
                await self._send_local(room, message, exclude)

            async def _send_local(
                self, room: str, message: dict, exclude: str | None = None,
            ) -> None:
                \"\"\"Send to local connections in a room. Remove dead connections.\"\"\"
                dead: list[str] = []
                for uid, ws in self._rooms.get(room, {}).items():
                    if uid == exclude:
                        continue
                    try:
                        await ws.send_json(message)
                    except Exception:
                        dead.append(uid)
                for uid in dead:
                    self.disconnect(uid, room)

            def get_room_members(self, room: str) -> list[str]:
                \"\"\"Return list of user IDs in a room.\"\"\"
                return list(self._rooms.get(room, {}).keys())

            def get_user_rooms(self, user_id: str) -> set[str]:
                \"\"\"Return set of rooms the user is in.\"\"\"
                return self._user_rooms.get(user_id, set()).copy()
        """)
    else:
        room_methods = textwrap.dedent("""\

            def connect(self, user_id: str, websocket: WebSocket) -> None:
                \"\"\"Register a user connection.\"\"\"
                self._user_connections.setdefault(user_id, []).append(websocket)
                ip = self._get_ip(websocket)
                self._ip_counts[ip] = self._ip_counts.get(ip, 0) + 1
                logger.info(f"User {user_id} connected")

            def disconnect(self, user_id: str) -> None:
                \"\"\"Remove a user connection.\"\"\"
                connections = self._user_connections.pop(user_id, [])
                for ws in connections:
                    ip = self._get_ip(ws)
                    self._ip_counts[ip] = max(0, self._ip_counts.get(ip, 1) - 1)
                logger.info(f"User {user_id} disconnected")

            async def broadcast(self, message: dict, exclude: str | None = None) -> None:
                \"\"\"Send message to all connected users.\"\"\"
                dead: list[str] = []
                for uid, connections in self._user_connections.items():
                    if uid == exclude:
                        continue
                    for ws in connections:
                        try:
                            await ws.send_json(message)
                        except Exception:
                            dead.append(uid)
                            break
                for uid in dead:
                    self.disconnect(uid)
        """)

    template = textwrap.dedent("""\
        \"\"\"WebSocket Connection Manager — rooms, limits, broadcast, lifecycle.

        Manages active WebSocket connections with per-user and per-IP limits,
        room-based grouping, and safe broadcast with dead connection cleanup.
        \"\"\"

        from __future__ import annotations

        import asyncio
        import logging

        from fastapi import WebSocket

        logger = logging.getLogger("ws.manager")


        class ConnectionManager:
            \"\"\"Manages WebSocket connections with rooms and limits.\"\"\"

            MAX_PER_USER = 5
            MAX_PER_IP = 20

            def __init__(self):
                self._rooms: dict[str, dict[str, WebSocket]] = {}
                self._user_connections: dict[str, list[WebSocket]] = {}
                self._user_rooms: dict[str, set[str]] = {}
                self._ip_counts: dict[str, int] = {}

            def _get_ip(self, websocket: WebSocket) -> str:
                \"\"\"Get client IP, respecting X-Forwarded-For from proxies.\"\"\"
                forwarded = websocket.headers.get("x-forwarded-for", "")
                if forwarded:
                    return forwarded.split(",")[0].strip()
                return websocket.client.host if websocket.client else "unknown"

            async def can_connect(self, user_id: str, websocket: WebSocket) -> tuple[bool, str]:
                \"\"\"Check if a new connection is allowed (per-user and per-IP limits).\"\"\"
                user_count = len(self._user_connections.get(user_id, []))
                ip = self._get_ip(websocket)
                ip_count = self._ip_counts.get(ip, 0)

                if user_count >= self.MAX_PER_USER:
                    return False, f"Max {self.MAX_PER_USER} connections per user"
                if ip_count >= self.MAX_PER_IP:
                    return False, f"Max {self.MAX_PER_IP} connections per IP"
                return True, "ok"
        __ROOM_METHODS__
            @property
            def connection_count(self) -> int:
                \"\"\"Total number of active connections.\"\"\"
                return sum(len(conns) for conns in self._user_connections.values())

            async def close_all(self, code: int = 1001, reason: str = "Server shutting down"):
                \"\"\"Gracefully close all connections (for shutdown).\"\"\"
                tasks = []
                for uid, connections in self._user_connections.items():
                    for ws in connections:
                        tasks.append(self._safe_close(ws, code, reason))
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                self._rooms.clear()
                self._user_connections.clear()
                self._user_rooms.clear()
                self._ip_counts.clear()
                logger.info(f"Closed {len(tasks)} WebSocket connections")

            async def _safe_close(self, ws: WebSocket, code: int, reason: str):
                try:
                    await asyncio.wait_for(ws.close(code=code, reason=reason), timeout=5.0)
                except Exception:
                    pass


        # Module-level singleton
        manager = ConnectionManager()
    """)
    return template.replace("__ROOM_METHODS__", room_methods)


def _endpoint_py(with_rooms: bool, with_auth: bool) -> str:
    auth_import = "from .auth import authenticate_ws" if with_auth else ""
    auth_check = textwrap.dedent("""\
        # Authenticate BEFORE accepting the connection
        payload = await authenticate_ws(websocket, token)
        if payload is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        user_id = payload["sub"]""") if with_auth else textwrap.dedent("""\
        user_id = token or "anonymous"
        payload = {"sub": user_id}""")

    if with_rooms:
        connect_call = 'manager.connect(user_id, "general", websocket)'
        disconnect_call = "manager.disconnect(user_id)"
        message_handling = textwrap.dedent("""\
                    match msg.action:
                        case WSAction.SUBSCRIBE:
                            manager.connect(user_id, msg.room, websocket)
                            await websocket.send_json({
                                "event": "subscribed", "room": msg.room,
                                "data": {"members": manager.get_room_members(msg.room)},
                            })
                        case WSAction.UNSUBSCRIBE:
                            manager.disconnect(user_id, msg.room)
                            await websocket.send_json({"event": "unsubscribed", "room": msg.room, "data": {}})
                        case WSAction.MESSAGE:
                            await manager.broadcast_to_room(
                                msg.room,
                                {"event": "message", "room": msg.room, "data": msg.payload or {}, "sender": user_id},
                                exclude=user_id,
                            )
                        case WSAction.TYPING:
                            await manager.broadcast_to_room(
                                msg.room,
                                {"event": "typing", "room": msg.room, "data": {"user_id": user_id}},
                                exclude=user_id,
                            )
                        case WSAction.PONG:
                            pass  # Heartbeat response — no processing needed""")
    else:
        connect_call = "manager.connect(user_id, websocket)"
        disconnect_call = "manager.disconnect(user_id)"
        message_handling = textwrap.dedent("""\
                    match msg.action:
                        case WSAction.MESSAGE:
                            await manager.broadcast(
                                {"event": "message", "data": msg.payload or {}, "sender": user_id},
                                exclude=user_id,
                            )
                        case WSAction.PONG:
                            pass  # Heartbeat response""")

    template = textwrap.dedent("""\
        \"\"\"WebSocket endpoint with full connection lifecycle.

        Handles: authentication, connection limits, message validation,
        heartbeat/ping-pong, room management, and graceful disconnect.
        \"\"\"

        from __future__ import annotations

        import asyncio
        import json
        import logging
        import time

        from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
        from pydantic import ValidationError

        __AUTH_IMPORT__
        from .manager import manager
        from .schemas import WSAction, WSIncoming

        logger = logging.getLogger("ws.endpoint")

        router = APIRouter()

        # --- Heartbeat configuration ---
        HEARTBEAT_INTERVAL = 30  # seconds between pings
        HEARTBEAT_TIMEOUT = 10   # seconds to wait for pong


        async def _heartbeat_loop(websocket: WebSocket, user_id: str):
            \"\"\"Send periodic pings to detect dead connections.\"\"\"
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                    try:
                        await asyncio.wait_for(
                            websocket.send_json({"type": "ping", "ts": time.time()}),
                            timeout=HEARTBEAT_TIMEOUT,
                        )
                    except (asyncio.TimeoutError, Exception):
                        logger.info(f"Heartbeat failed for user {user_id} — closing")
                        try:
                            await websocket.close(code=1001)
                        except Exception:
                            pass
                        break
            except asyncio.CancelledError:
                pass


        @router.websocket("/ws")
        async def websocket_endpoint(
            websocket: WebSocket,
            token: str | None = Query(default=None),
        ):
            \"\"\"Main WebSocket endpoint with full lifecycle management.\"\"\"
        __AUTH_CHECK__

            # Check connection limits
            allowed, reason = await manager.can_connect(user_id, websocket)
            if not allowed:
                logger.warning(f"Connection rejected for {user_id}: {reason}")
                await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
                return

            await websocket.accept()
        __CONNECT_CALL__
            logger.info(f"User {user_id} connected (total: {manager.connection_count})")

            # Start heartbeat background task
            heartbeat_task = asyncio.create_task(_heartbeat_loop(websocket, user_id))

            try:
                while True:
                    raw = await websocket.receive_text()

                    # Validate message against schema
                    try:
                        msg = WSIncoming.model_validate_json(raw)
                    except ValidationError as exc:
                        await websocket.send_json({
                            "event": "error",
                            "data": {"code": "INVALID_MESSAGE", "detail": str(exc)},
                        })
                        continue

        __MESSAGE_HANDLING__

            except WebSocketDisconnect:
                logger.info(f"User {user_id} disconnected normally")
            except Exception:
                logger.exception(f"WebSocket error for user {user_id}")
            finally:
                # ALWAYS clean up
                heartbeat_task.cancel()
        __DISCONNECT_CALL__
                logger.info(f"User {user_id} cleaned up (total: {manager.connection_count})")
    """)
    # Indent interpolated blocks to match their context in generated code
    auth_import_line = auth_import if auth_import else ""
    # auth_check needs to be at 8-space indent (inside function body)
    auth_check_indented = textwrap.indent(auth_check.strip(), "    ")
    # connect_call at 4 spaces indent (function body)
    connect_indented = "    " + connect_call
    # disconnect_call at 8 spaces indent (inside finally)
    disconnect_indented = "        " + disconnect_call
    # message_handling at 8 spaces indent (inside while/try)
    msg_indented = textwrap.indent(message_handling.strip(), "        ")

    result = template.replace("__AUTH_IMPORT__", auth_import_line)
    result = result.replace("__AUTH_CHECK__", auth_check_indented)
    result = result.replace("__CONNECT_CALL__", connect_indented)
    result = result.replace("__MESSAGE_HANDLING__", msg_indented)
    result = result.replace("__DISCONNECT_CALL__", disconnect_indented)
    return result


def _redis_pubsub_py() -> str:
    return textwrap.dedent("""\
        \"\"\"Redis Pub/Sub bridge for multi-worker WebSocket broadcast.

        When running multiple uvicorn workers, each worker has its own
        ConnectionManager instance. Redis Pub/Sub bridges messages between
        workers so broadcasts reach all connected clients.

        Usage:
            1. Call init_redis_bridge() in lifespan startup
            2. Call broadcast_via_redis() instead of manager.broadcast_to_room()
            3. Call close_redis_bridge() in lifespan shutdown
        \"\"\"

        from __future__ import annotations

        import asyncio
        import json
        import logging

        import redis.asyncio as aioredis

        from .manager import manager

        logger = logging.getLogger("ws.redis_pubsub")

        _redis: aioredis.Redis | None = None
        _listener_task: asyncio.Task | None = None


        async def init_redis_bridge(redis_url: str = "redis://localhost:6379") -> None:
            \"\"\"Initialize Redis connection and start the pub/sub listener.\"\"\"
            global _redis, _listener_task
            _redis = aioredis.from_url(redis_url)
            _listener_task = asyncio.create_task(_listen_loop())
            logger.info("Redis pub/sub bridge initialized")


        async def close_redis_bridge() -> None:
            \"\"\"Shut down the Redis pub/sub listener and close connection.\"\"\"
            global _redis, _listener_task
            if _listener_task:
                _listener_task.cancel()
                try:
                    await _listener_task
                except asyncio.CancelledError:
                    pass
                _listener_task = None
            if _redis:
                await _redis.close()
                _redis = None
            logger.info("Redis pub/sub bridge closed")


        async def broadcast_via_redis(room: str, message: dict) -> None:
            \"\"\"Publish a message to Redis for cross-worker delivery.

            Also delivers to local connections immediately.
            \"\"\"
            # Local delivery first (same worker)
            await manager.broadcast_to_room(room, message)
            # Cross-worker delivery via Redis
            if _redis:
                channel = f"ws:room:{room}"
                await _redis.publish(channel, json.dumps(message, default=str))


        async def _listen_loop() -> None:
            \"\"\"Subscribe to Redis channels and relay to local connections.\"\"\"
            if not _redis:
                return
            pubsub = _redis.pubsub()
            await pubsub.psubscribe("ws:room:*")
            logger.info("Redis pub/sub listener started")
            try:
                async for message in pubsub.listen():
                    if message["type"] != "pmessage":
                        continue
                    try:
                        channel = message["channel"]
                        if isinstance(channel, bytes):
                            channel = channel.decode()
                        room = channel.split(":", 2)[-1]
                        data = json.loads(message["data"])
                        # Deliver to local connections only (avoid echo)
                        await manager._send_local(room, data)
                    except Exception:
                        logger.exception("Error processing Redis pub/sub message")
            except asyncio.CancelledError:
                await pubsub.unsubscribe()
    """)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def generate_websocket_module(
    output_dir: str,
    with_rooms: bool = True,
    with_auth: bool = True,
) -> dict:
    """
    Generate a production-ready WebSocket module for a FastAPI project.

    Creates a complete WebSocket implementation with auth on connect,
    connection manager with rooms, heartbeat/ping-pong, message validation,
    connection limiting, and Redis pub/sub for multi-worker broadcast.

    Args:
        output_dir: Parent directory where the ``ws/`` package will be created.
        with_rooms: Include room-based grouping and broadcast.
        with_auth: Include JWT authentication on WebSocket connect.

    Returns:
        Dict with ``created_files`` (list of paths) and ``ws_path`` (str).

    Example::

        result = generate_websocket_module("/tmp/myproject", with_rooms=True)
        print(result["created_files"])
        # ['ws/__init__.py', 'ws/schemas.py', 'ws/auth.py', 'ws/manager.py',
        #  'ws/endpoint.py', 'ws/redis_pubsub.py']
    """
    ws_dir = Path(output_dir) / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "__init__.py": _init_py(),
        "schemas.py": _schemas_py(),
        "auth.py": _auth_py(with_auth),
        "manager.py": _manager_py(with_rooms),
        "endpoint.py": _endpoint_py(with_rooms, with_auth),
        "redis_pubsub.py": _redis_pubsub_py(),
    }

    created: list[str] = []
    for filename, content in files.items():
        filepath = ws_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(f"ws/{filename}")

    return {
        "created_files": created,
        "ws_path": str(ws_dir),
        "with_rooms": with_rooms,
        "with_auth": with_auth,
    }
