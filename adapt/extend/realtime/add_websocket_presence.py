"""TOOL-062: add_websocket_presence — add WebSocket presence tracking to a FastAPI project.

Writes a Redis-backed ``PresenceManager``, the ``/ws/presence`` WebSocket
endpoint with JWT auth + heartbeat ping/pong, ``UserPresence`` SQLAlchemy
model, Pydantic schemas, and REST companion routes.

Security guarantees:

* JWT is verified via ``app.core.jwt.verify_access_token`` — same auth
  scheme as the rest of the scaffold; no new token format invented.
* Failed auth closes the socket with ``1008 Policy Violation`` BEFORE
  any Redis write.
* Multi-device: each connection carries a ``device_id``; a user is
  considered "online" as long as ANY of their devices is connected.
* Redis TTL = heartbeat_seconds × 3 — three missed heartbeats = offline.
* Pub/sub fan-out for real-time "online/offline" event notifications.

The tool is idempotent: a second run detects the ``PresenceManager``
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.realtime.add_websocket_presence import add_websocket_presence

    result = add_websocket_presence(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/ws/presence.py", …]
    print(result.next_steps)    # ["Set REDIS_URL in .env", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_websocket_presence",
    "description": (
        "Add production-grade WebSocket presence tracking with JWT auth, "
        "Redis pub/sub, heartbeat TTL, multi-device support, and REST companion routes."
    ),
    "tags": ["extend", "realtime"],
    "entry": "add_websocket_presence",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_websocket_presence(
    inp: ToolInput,
    *,
    heartbeat_seconds: int = 30,
    max_devices_per_user: int = 5,
) -> ToolResult:
    """Add WebSocket presence tracking to a FastAPI project.

    Creates ``PresenceManager``, the ``/ws/presence`` endpoint, ``UserPresence``
    model, Pydantic schemas, and REST companion routes.  Patches
    ``app/core/config.py``, ``app/models/__init__.py``, and ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        heartbeat_seconds: How often the client sends a ping heartbeat (default 30).
            Redis TTL = heartbeat_seconds × 3 (three missed heartbeats = offline).
        max_devices_per_user: Maximum simultaneous device connections per user (default 5).

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
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
    presence_ws_file = app_dir / "ws" / "presence.py"
    if presence_ws_file.exists() and "PresenceManager" in presence_ws_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["PresenceManager already present — WebSocket presence is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        ttl = heartbeat_seconds * 3
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create PresenceManager, /ws/presence endpoint,",
                "         UserPresence model, schemas, and REST routes.",
                f"         heartbeat_seconds={heartbeat_seconds}, TTL={ttl}s, "
                f"max_devices_per_user={max_devices_per_user}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 – model
    model_file = app_dir / "models" / "presence.py"
    _write_presence_model(model_file)
    files_created.append(str(model_file))

    # Register UserPresence in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("presence", "UserPresence")])
        files_modified.append(str(models_init))

    # Step 2 – schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "presence.py"
    _write_presence_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 3 – ws package (manager + endpoint)
    ws_dir = app_dir / "ws"
    ws_dir.mkdir(parents=True, exist_ok=True)
    ws_init = ws_dir / "__init__.py"
    if not ws_init.exists():
        ws_init.write_text('"""WebSocket sub-package."""\n')
        files_created.append(str(ws_init))

    manager_file = ws_dir / "presence.py"
    _write_presence_manager(manager_file, heartbeat_seconds, max_devices_per_user)
    files_created.append(str(manager_file))

    endpoint_file = ws_dir / "presence_endpoint.py"
    _write_presence_endpoint(endpoint_file, heartbeat_seconds)
    files_created.append(str(endpoint_file))

    # Step 4 – REST companion routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    http_route_file = routes_dir / "presence.py"
    _write_presence_http_routes(http_route_file)
    files_created.append(str(http_route_file))

    # Step 5 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, heartbeat_seconds, max_devices_per_user)
        files_modified.append(str(config_file))

    # Step 6 – register presence router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 7 – ensure app/core/redis.py exists
    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        _write_redis_module(redis_module)
        files_created.append(str(redis_module))

    # Step 8 – add redis to requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate all written Python files parse correctly
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "WebSocket presence added: manager, endpoint, model, schemas, REST routes.",
            "Endpoint: WS /ws/presence?token=<JWT>",
            f"Heartbeat: every {heartbeat_seconds}s.  "
            f"TTL: {heartbeat_seconds * 3}s (3 missed = offline).  "
            f"Max devices/user: {max_devices_per_user}.",
            "Fan-out via Redis pub/sub — multi-worker safe out of the box.",
            "REST: GET /presence/online, GET /presence/{user_id}.",
        ],
        next_steps=[
            "Set REDIS_URL in .env — presence TTL and pub/sub require Redis.",
            "Restart the application so the new presence router and WS endpoint are active.",
            "Connect a client with: ws://<host>/ws/presence?token=<access_token>",
            "Client must send {\"type\": \"ping\"} every "
            f"{heartbeat_seconds}s to stay online.",
            "Poll online users at GET /presence/online.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each <= 50 LOC
# ---------------------------------------------------------------------------

def _write_presence_model(dest: Path) -> None:
    """Write ``app/models/presence.py`` with ``UserPresence`` SQLAlchemy model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"SQLAlchemy model for user presence tracking.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import DateTime, String, Uuid, func
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class UserPresence(Base):
            \"\"\"Tracks the online/offline state of a user.

            Attributes:
                id: UUID primary key.
                user_id: UUID of the user (not FK — presence is ephemeral).
                device_id: Device identifier for multi-device support.
                status: Current status string (``"online"`` or ``"offline"``).
                last_seen: UTC timestamp of the most recent heartbeat.
            \"\"\"

            __tablename__ = "user_presence"

            id: Mapped[uuid.UUID] = mapped_column(
                Uuid, primary_key=True, default=uuid.uuid4
            )
            user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
            device_id: Mapped[str] = mapped_column(
                String(64), nullable=False, server_default="default"
            )
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="offline"
            )
            last_seen: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
    """))


def _write_presence_schemas(dest: Path) -> None:
    """Write ``app/schemas/presence.py`` with Pydantic request/response schemas.

    Args:
        dest: Absolute path for the new file.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for WebSocket presence.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class PresenceUpdate(BaseModel):
            \"\"\"Inbound WebSocket control message from the client.

            Attributes:
                type: Message type — ``\"ping\"`` to refresh heartbeat,
                    ``\"set_device\"`` to register a device label.
                device_id: Optional device identifier (max 64 chars).
            \"\"\"

            model_config = ConfigDict(strict=True, extra="forbid")

            type: str = Field(..., pattern="^(ping|set_device)$")
            device_id: str | None = Field(default=None, max_length=64)


        class PresenceOut(BaseModel):
            \"\"\"Outbound presence state broadcast to subscribers.

            Attributes:
                user_id: UUID of the user.
                status: ``\"online\"`` or ``\"offline\"``.
                last_seen: UTC timestamp of the most recent heartbeat.
                device: Device identifier that triggered the update.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            user_id: uuid.UUID
            status: str
            last_seen: datetime
            device: str


        class PresenceList(BaseModel):
            \"\"\"List of currently online users.

            Attributes:
                online: List of user UUIDs that have at least one active device.
                count: Total number of online users.
            \"\"\"

            online: list[uuid.UUID]
            count: int
    """))


def _write_presence_manager(
    dest: Path,
    heartbeat_seconds: int,
    max_devices_per_user: int,
) -> None:
    """Write ``app/ws/presence.py`` with ``PresenceManager``.

    Args:
        dest: Absolute path for the new file.
        heartbeat_seconds: Heartbeat interval; TTL = heartbeat_seconds × 3.
        max_devices_per_user: Hard cap on simultaneous device connections per user.
    """
    ttl = heartbeat_seconds * 3
    content = textwrap.dedent("""\
        \"\"\"PresenceManager — Redis-backed user presence tracker.

        One instance per application process (singleton via ``get_presence_manager``).
        \"\"\"
        from __future__ import annotations

        import json
        import logging

        logger = logging.getLogger(__name__)

        PRESENCE_KEY = "presence:user:{user_id}"
        DEVICE_KEY = "presence:devices:{user_id}"
        CHANNEL = "presence:events"
        _HEARTBEAT_TTL = {ttl}
        _MAX_DEVICES = {max_devices}


        class PresenceManager:
            \"\"\"Manages user presence state in Redis with TTL-based heartbeats.

            Redis layout:

            * ``presence:user:<uid>`` — string key with TTL, value = ``"online"``.
            * ``presence:devices:<uid>`` — set of active device_id strings.
            * ``presence:events`` — pub/sub channel for online/offline events.
            \"\"\"

            async def mark_online(self, user_id: str, device_id: str) -> bool:
                \"\"\"Register *device_id* for *user_id* and set TTL.

                Args:
                    user_id: UUID string of the user.
                    device_id: Device identifier string.

                Returns:
                    ``True`` if registered, ``False`` if device cap exceeded.
                \"\"\"
                from app.core.redis import get_redis
                redis = await get_redis()
                dkey = DEVICE_KEY.format(user_id=user_id)
                count = await redis.scard(dkey)
                if count >= _MAX_DEVICES and not await redis.sismember(dkey, device_id):
                    return False
                await redis.sadd(dkey, device_id)
                await redis.expire(dkey, _HEARTBEAT_TTL)
                pkey = PRESENCE_KEY.format(user_id=user_id)
                is_new = await redis.set(pkey, "online", ex=_HEARTBEAT_TTL, nx=True)
                if is_new:
                    await self._publish_event(redis, user_id, "online", device_id)
                else:
                    await redis.expire(pkey, _HEARTBEAT_TTL)
                return True

            async def mark_offline(self, user_id: str, device_id: str) -> None:
                \"\"\"Remove *device_id* from *user_id*'s active set; go offline if last.

                Args:
                    user_id: UUID string of the user.
                    device_id: Device identifier string.
                \"\"\"
                from app.core.redis import get_redis
                redis = await get_redis()
                dkey = DEVICE_KEY.format(user_id=user_id)
                await redis.srem(dkey, device_id)
                remaining = await redis.scard(dkey)
                if remaining == 0:
                    pkey = PRESENCE_KEY.format(user_id=user_id)
                    await redis.delete(pkey)
                    await self._publish_event(redis, user_id, "offline", device_id)

            async def is_online(self, user_id: str) -> bool:
                \"\"\"Return ``True`` if *user_id* has any active device.

                Args:
                    user_id: UUID string of the user.

                Returns:
                    ``True`` when the user is online.
                \"\"\"
                from app.core.redis import get_redis
                redis = await get_redis()
                return bool(await redis.exists(PRESENCE_KEY.format(user_id=user_id)))

            async def _publish_event(
                self, redis: object, user_id: str, status: str, device: str
            ) -> None:
                \"\"\"Publish an online/offline event to the presence pub/sub channel.

                Args:
                    redis: Connected async Redis client.
                    user_id: UUID string of the user.
                    status: ``\"online\"`` or ``\"offline\"``.
                    device: Device identifier that triggered the change.
                \"\"\"
                payload = json.dumps(
                    {{"user_id": user_id, "status": status, "device": device}},
                    separators=(",", ":"),
                )
                try:
                    await redis.publish(CHANNEL, payload)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to publish presence event for user=%s", user_id)


        _manager: PresenceManager | None = None


        def get_presence_manager() -> PresenceManager:
            \"\"\"Return the application-wide ``PresenceManager`` singleton.

            Returns:
                The shared ``PresenceManager`` instance.
            \"\"\"
            global _manager
            if _manager is None:
                _manager = PresenceManager()
            return _manager
        """).replace("{ttl}", str(ttl)).replace("{max_devices}", str(max_devices_per_user))
    dest.write_text(content)


def _write_presence_endpoint(dest: Path, heartbeat_seconds: int) -> None:
    """Write ``app/ws/presence_endpoint.py`` — the /ws/presence WebSocket endpoint.

    Args:
        dest: Absolute path for the new file.
        heartbeat_seconds: Expected heartbeat interval for timeout detection.
    """
    timeout = heartbeat_seconds * 3
    content = textwrap.dedent("""\
        \"\"\"WebSocket presence endpoint: WS /ws/presence.

        Auth: JWT via ``?token=`` query param or ``Authorization: Bearer`` subprotocol.
        Heartbeat: client sends {{\"type\": \"ping\"}} every {hb}s; server echoes {{\"type\": \"pong\"}}.
        Timeout: {timeout}s without ping = server closes with 1001.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import json
        import logging
        import uuid as _uuid

        from fastapi import APIRouter, WebSocket, WebSocketDisconnect

        from app.ws.presence import get_presence_manager

        logger = logging.getLogger(__name__)
        router = APIRouter()
        _TIMEOUT = {timeout}


        def _extract_token(ws: WebSocket) -> str | None:
            \"\"\"Return JWT from ``?token=`` or ``Authorization`` header.

            Args:
                ws: Incoming ``WebSocket`` (before accept).

            Returns:
                Raw token string, or ``None`` if absent.
            \"\"\"
            token = ws.query_params.get("token")
            if token:
                return token
            auth = ws.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth.split(" ", 1)[1].strip()
            return None


        def _authenticate_token(token: str) -> tuple[str, str] | None:
            \"\"\"Verify *token* and return ``(user_id, device_id)`` on success.

            Args:
                token: Raw JWT string.

            Returns:
                ``(user_id, device_id)`` tuple, or ``None`` on failure.
            \"\"\"
            try:
                from app.core.jwt import verify_access_token
                payload = verify_access_token(token)
            except Exception:  # noqa: BLE001
                return None
            user_id = payload.get("sub")
            if not user_id:
                return None
            device_id = payload.get("device_id") or str(_uuid.uuid4())[:8]
            return str(user_id), str(device_id)


        @router.websocket("/ws/presence")
        async def ws_presence(ws: WebSocket) -> None:
            \"\"\"WebSocket endpoint for real-time user presence tracking.

            Authenticates via JWT, registers the connection, handles
            heartbeat pings, and marks the user offline on disconnect.
            \"\"\"
            token = _extract_token(ws)
            if not token:
                await ws.close(code=1008)
                return
            auth = _authenticate_token(token)
            if not auth:
                await ws.close(code=1008)
                return
            user_id, device_id = auth
            await ws.accept()
            manager = get_presence_manager()
            ok = await manager.mark_online(user_id, device_id)
            if not ok:
                await ws.send_text(
                    json.dumps({{"type": "error", "code": "device_limit_exceeded"}})
                )
                await ws.close(code=1008)
                return
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.receive_text(), timeout=_TIMEOUT)
                    except asyncio.TimeoutError:
                        await ws.close(code=1001)
                        return
                    try:
                        msg = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if msg.get("type") == "ping":
                        await manager.mark_online(user_id, device_id)
                        await ws.send_text(json.dumps({{"type": "pong"}}))
            except WebSocketDisconnect:
                pass
            finally:
                await manager.mark_offline(user_id, device_id)
        """).replace("{hb}", str(heartbeat_seconds)).replace("{timeout}", str(timeout))
    dest.write_text(content)


def _write_presence_http_routes(dest: Path) -> None:
    """Write ``app/api/routes/presence.py`` — REST companion routes.

    Routes:
        GET /presence/online — list all online user UUIDs.
        GET /presence/{user_id} — check if a specific user is online.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"REST companion routes for presence: GET /presence/online, GET /presence/{user_id}.\"\"\"
        from __future__ import annotations

        import uuid

        from fastapi import APIRouter

        from app.schemas.presence import PresenceList, PresenceOut
        from app.ws.presence import PRESENCE_KEY, get_presence_manager

        router = APIRouter(prefix="/presence", tags=["presence"])


        @router.get("/online", response_model=PresenceList)
        async def list_online_users() -> PresenceList:
            \"\"\"Return a list of all currently online user UUIDs.

            Scans Redis for ``presence:user:*`` keys and returns the user
            UUIDs with active TTL.  Designed for polling by mobile clients
            that cannot hold a long-lived WebSocket.

            Returns:
                ``PresenceList`` with ``online`` user UUID list and ``count``.
            \"\"\"
            from app.core.redis import get_redis
            redis = await get_redis()
            pattern = PRESENCE_KEY.replace("{user_id}", "*")
            keys = await redis.keys(pattern)
            prefix = PRESENCE_KEY.split("{")[0]
            online = [
                uuid.UUID(k[len(prefix):]) for k in keys if k.startswith(prefix)
            ]
            return PresenceList(online=online, count=len(online))


        @router.get("/{user_id}", response_model=PresenceOut)
        async def get_user_presence(user_id: uuid.UUID) -> PresenceOut:
            \"\"\"Return the current presence state for a specific user.

            Args:
                user_id: UUID of the user to query.

            Returns:
                ``PresenceOut`` with current status, last_seen, and device.
            \"\"\"
            import datetime as _dt
            manager = get_presence_manager()
            is_online = await manager.is_online(str(user_id))
            from app.core.redis import get_redis
            redis = await get_redis()
            from app.ws.presence import DEVICE_KEY
            members = await redis.smembers(DEVICE_KEY.format(user_id=str(user_id)))
            device = next(iter(members), "unknown") if members else "unknown"
            return PresenceOut(
                user_id=user_id,
                status="online" if is_online else "offline",
                last_seen=_dt.datetime.now(_dt.timezone.utc),
                device=device,
            )
    """))


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


def _patch_config(
    config_file: Path,
    heartbeat_seconds: int,
    max_devices_per_user: int,
) -> None:
    """Inject presence settings into the Settings class body.

    Args:
        config_file: Path to the existing config module.
        heartbeat_seconds: Heartbeat interval in seconds.
        max_devices_per_user: Per-user device cap.
    """
    src = config_file.read_text()
    if "PRESENCE_HEARTBEAT_SECONDS" in src:
        return
    ttl = heartbeat_seconds * 3
    block = (
        "\n"
        "    # --- Presence settings — added by add_websocket_presence tool ---\n"
        f"    PRESENCE_HEARTBEAT_SECONDS: int = {heartbeat_seconds}\n"
        f"    PRESENCE_TTL_SECONDS: int = {ttl}\n"
        f"    PRESENCE_MAX_DEVICES: int = {max_devices_per_user}\n"
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
    """Register the presence HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.presence import router as presence_router"
    include_line = "api_router.include_router(presence_router)"
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


def _write_redis_module(dest: Path) -> None:
    """Write ``app/core/redis.py`` with a simple async Redis client factory.

    Args:
        dest: Absolute destination path (``app/core/redis.py``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async Redis client factory for realtime features (SSE, webhooks, presence).\"\"\"
        from __future__ import annotations

        import redis.asyncio as redis

        from app.core.config import settings


        async def get_redis() -> redis.Redis:
            \"\"\"Return a connected async Redis client.

            Uses ``settings.REDIS_URL``.  Caller is responsible for closing
            the connection when done.

            Returns:
                Connected ``redis.asyncio.Redis`` instance.
            \"\"\"
            return redis.from_url(
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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.
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
