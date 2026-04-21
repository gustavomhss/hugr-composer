"""TOOL-014: add_sse — add Server-Sent Events to a FastAPI/SQLAlchemy project.

Writes an SSEManager (Redis pub/sub fan-out), publisher helper, channel-access
guard, SSE routes, a formatter, a rate-limiter, a connection registry, and all
required ``settings`` keys.  The manager supports heartbeats, per-user
connection caps, Last-Event-ID replay from a bounded sorted-set buffer, and
multi-line ``data`` fields per the HTML5 spec.

The tool is idempotent: a second run detects the ``SSEManager`` fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.realtime.add_sse import add_sse

    result = add_sse(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/sse/manager.py", …]
    print(result.next_steps)    # ["Restart the application …"]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_realtime_add_sse",
    "description": "Add Server-Sent Events (SSE) endpoints for real-time push to browser clients.",
    "tags": ["extend", "realtime"],
    "entry": "add_sse",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_sse(
    inp: ToolInput,
    *,
    heartbeat_seconds: int = 15,
    max_connections_per_user: int = 10,
    replay_buffer_size: int = 100,
    replay_ttl_seconds: int = 600,
) -> ToolResult:
    """Add Server-Sent Events support to a FastAPI project.

    Creates the SSE manager, publisher, channel-access guard, routes, formatter,
    rate-limiter, and connection registry.  Patches ``app/core/config.py`` and
    ``app/api/main.py`` for the new settings and route registration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        heartbeat_seconds: Interval between ``:keepalive`` comments (default 15).
        max_connections_per_user: Simultaneous SSE streams per user (default 10).
        replay_buffer_size: Events kept per channel for Last-Event-ID replay (default 100).
        replay_ttl_seconds: TTL of per-channel replay buffer in Redis (default 600).

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
    manager_file = app_dir / "core" / "sse" / "manager.py"
    if manager_file.exists() and "SSEManager" in manager_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SSEManager already present — SSE is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create SSE manager, publisher, access guard, routes,",
                "         formatter, rate-limiter, connection registry.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    sse_dir = app_dir / "core" / "sse"
    sse_dir.mkdir(parents=True, exist_ok=True)

    # Write __init__.py
    init_file = sse_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""SSE sub-package."""\n')
        files_created.append(str(init_file))

    # Step 1 – formatter
    formatter_file = sse_dir / "formatter.py"
    _write_formatter(formatter_file, replay_buffer_size)
    files_created.append(str(formatter_file))

    # Step 2 – rate limiter
    rate_limiter_file = sse_dir / "rate_limiter.py"
    _write_rate_limiter(rate_limiter_file)
    files_created.append(str(rate_limiter_file))

    # Step 3 – connection registry
    registry_file = sse_dir / "connection_registry.py"
    _write_connection_registry(registry_file)
    files_created.append(str(registry_file))

    # Step 4 – channel-access guard
    access_file = sse_dir / "access.py"
    _write_access(access_file)
    files_created.append(str(access_file))

    # Step 5 – publisher
    publisher_file = sse_dir / "publisher.py"
    _write_publisher(publisher_file, replay_buffer_size, replay_ttl_seconds)
    files_created.append(str(publisher_file))

    # Step 6 – manager
    _write_manager(manager_file, heartbeat_seconds, max_connections_per_user)
    files_created.append(str(manager_file))

    # Step 7 – routes
    events_route_file = app_dir / "api" / "routes" / "events.py"
    _write_events_route(events_route_file)
    files_created.append(str(events_route_file))

    # Step 8 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            heartbeat_seconds,
            max_connections_per_user,
            replay_buffer_size,
            replay_ttl_seconds,
        )
        files_modified.append(str(config_file))

    # Step 9 – register events router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

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

    # Validate all written .py files parse correctly.
    # Scaffolded prerequisites may include non-Python artefacts
    # (requirements.txt, alembic/versions/.gitkeep) and relative paths —
    # skip those, and resolve relative paths against the project root.
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix != ".py":
            continue
        if not p.is_absolute():
            p = project / p
        if p.is_file():
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "SSE support added: manager, publisher, access guard, routes.",
            f"Heartbeat: every {heartbeat_seconds}s.  "
            f"Connection cap: {max_connections_per_user}/user.",
            f"Replay buffer: {replay_buffer_size} events, TTL {replay_ttl_seconds}s.",
            "Clients subscribe via GET /api/v1/events/stream?channel=<name>.",
            "Publish events with: await publish_event(channel, event_name, payload).",
        ],
        next_steps=[
            "Set REDIS_URL in .env (Redis is required for pub/sub and replay buffer).",
            "Restart the application so the new events router is active.",
            "Verify the endpoint at GET /docs → /events/stream.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_formatter(dest: Path, replay_buffer_size: int) -> None:
    """Write ``app/core/sse/formatter.py`` with ``SSEEvent`` + ``format_event``.

    Args:
        dest: Absolute path for the new file.
        replay_buffer_size: Documented in the module docstring.
    """
    content = textwrap.dedent("""\
        \"\"\"Format SSE events to the text/event-stream wire format (HTML5 spec).

        An SSE event is a series of lines followed by a blank line::

            id: 1234567890-abc
            event: item.created
            retry: 5000
            data: {"id": "..."}

        Multi-line ``data`` values are split into multiple ``data:`` lines per spec.
        Replay buffer holds up to {buf} events per channel.
        \"\"\"
        from __future__ import annotations

        import json
        from dataclasses import dataclass
        from typing import Any


        @dataclass(frozen=True)
        class SSEEvent:
            \"\"\"Immutable SSE event value object.

            Attributes:
                event_id: Unique identifier placed in the ``id:`` field.
                event_name: Value of the ``event:`` field.
                payload: JSON-serializable data placed in the ``data:`` field(s).
                retry_ms: Optional ``retry:`` hint for client auto-reconnect.
            \"\"\"

            event_id: str
            event_name: str
            payload: dict[str, Any]
            retry_ms: int | None = None


        def format_event(event: SSEEvent) -> bytes:
            \"\"\"Serialize an SSEEvent to the text/event-stream wire format.

            Args:
                event: The SSEEvent to serialize.

            Returns:
                UTF-8 encoded bytes ready to stream to the client.

            Raises:
                ValueError: If ``event_id`` or ``event_name`` is empty.
            \"\"\"
            if not event.event_id:
                raise ValueError("event_id must be non-empty")
            if not event.event_name:
                raise ValueError("event_name must be non-empty")
            lines: list[str] = [f"id: {event.event_id}", f"event: {event.event_name}"]
            if event.retry_ms is not None:
                lines.append(f"retry: {event.retry_ms}")
            data_json = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False)
            for data_line in data_json.splitlines() or [""]:
                lines.append(f"data: {data_line}")
            lines.append("")
            return ("\\n".join(lines) + "\\n").encode("utf-8")


        def format_keepalive() -> bytes:
            \"\"\"Return a comment-only keepalive frame to defeat proxy idle timeouts.

            Returns:
                Bytes representing ``:keepalive\\n\\n``.
            \"\"\"
            return b":keepalive\\n\\n"
        """).replace("{buf}", str(replay_buffer_size))
    dest.write_text(content)


def _write_rate_limiter(dest: Path) -> None:
    """Write ``app/core/sse/rate_limiter.py`` with ``TokenBucket`` + ``ConnectionRateLimiter``.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Per-connection token bucket for SSE event emission.

        A slow consumer cannot stall the publisher because overflow events are
        dropped and counted so operators can see slow consumers in dashboards.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import time
        from dataclasses import dataclass, field


        @dataclass
        class TokenBucket:
            \"\"\"Asyncio-safe token bucket.

            Attributes:
                capacity: Maximum tokens the bucket holds.
                refill_rate_per_second: Tokens added per second.
            \"\"\"

            capacity: float
            refill_rate_per_second: float
            _tokens: float = field(default=0.0, init=False)
            _last_refill: float = field(default=0.0, init=False)
            _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

            def __post_init__(self) -> None:
                self._tokens = self.capacity
                self._last_refill = time.monotonic()

            async def try_acquire(self, tokens: float = 1.0) -> bool:
                \"\"\"Attempt to consume *tokens* from the bucket.

                Args:
                    tokens: Number of tokens to consume (default 1.0).

                Returns:
                    ``True`` if the tokens were available and consumed.
                \"\"\"
                async with self._lock:
                    now = time.monotonic()
                    elapsed = now - self._last_refill
                    self._tokens = min(
                        self.capacity,
                        self._tokens + elapsed * self.refill_rate_per_second,
                    )
                    self._last_refill = now
                    if self._tokens >= tokens:
                        self._tokens -= tokens
                        return True
                    return False


        class ConnectionRateLimiter:
            \"\"\"Maps connection_id to a TokenBucket; buckets are released on disconnect.

            Args:
                capacity: Initial token capacity per bucket (default 20.0).
                refill_per_second: Token refill rate (default 10.0).
            \"\"\"

            def __init__(self, capacity: float = 20.0, refill_per_second: float = 10.0) -> None:
                self._capacity = capacity
                self._refill = refill_per_second
                self._buckets: dict[str, TokenBucket] = {}

            def register(self, connection_id: str) -> None:
                \"\"\"Create a fresh token bucket for *connection_id*.

                Args:
                    connection_id: Unique identifier for the connection.
                \"\"\"
                self._buckets[connection_id] = TokenBucket(self._capacity, self._refill)

            def release(self, connection_id: str) -> None:
                \"\"\"Remove the token bucket when a connection closes.

                Args:
                    connection_id: Identifier of the closing connection.
                \"\"\"
                self._buckets.pop(connection_id, None)

            async def allow(self, connection_id: str) -> bool:
                \"\"\"Check whether *connection_id* may emit one more event.

                Args:
                    connection_id: Identifier of the connection to check.

                Returns:
                    ``True`` if the connection is within its rate limit.
                \"\"\"
                bucket = self._buckets.get(connection_id)
                if bucket is None:
                    return False
                return await bucket.try_acquire(1.0)
        """)
    dest.write_text(content)


def _write_connection_registry(dest: Path) -> None:
    """Write ``app/core/sse/connection_registry.py`` with Redis-backed connection cap.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Redis-backed SSE connection registry that enforces per-user caps.

        Each connection is stored in a Redis set under ``sse:connections:{user_id}``.
        The TTL is refreshed by the heartbeat loop so a worker restart does not
        permanently leak a connection slot.
        \"\"\"
        from __future__ import annotations

        from dataclasses import dataclass
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            import redis.asyncio as aioredis


        CONNECTION_KEY = "sse:connections:{user_id}"
        CONNECTION_TTL_SECONDS = 30  # refreshed by heartbeat every SSE_HEARTBEAT_SECONDS


        @dataclass(frozen=True)
        class ConnectionSlot:
            \"\"\"Identifies a single SSE connection.

            Attributes:
                user_id: UUID string of the connected user.
                connection_id: Unique identifier for this specific connection.
                worker_id: Worker-process identifier (e.g. hostname + PID).
            \"\"\"

            user_id: str
            connection_id: str
            worker_id: str


        class ConnectionRegistry:
            \"\"\"Register and release SSE connections against per-user caps.

            Args:
                client: Async Redis client.
                max_per_user: Maximum simultaneous connections allowed (default 5).
            \"\"\"

            def __init__(self, client: "aioredis.Redis", max_per_user: int = 5) -> None:
                self._redis = client
                self._max = max_per_user

            async def try_register(self, slot: ConnectionSlot) -> bool:
                \"\"\"Attempt to register a new connection slot.

                Args:
                    slot: The connection to register.

                Returns:
                    ``True`` if there was room under the cap and the slot was stored.
                \"\"\"
                key = CONNECTION_KEY.format(user_id=slot.user_id)
                current = await self._redis.scard(key)
                if current >= self._max:
                    return False
                member = f"{slot.worker_id}:{slot.connection_id}"
                await self._redis.sadd(key, member)
                await self._redis.expire(key, CONNECTION_TTL_SECONDS)
                return True

            async def refresh(self, slot: ConnectionSlot) -> None:
                \"\"\"Refresh the TTL of the connection set (called by heartbeat loop).

                Args:
                    slot: The connection whose TTL should be refreshed.
                \"\"\"
                key = CONNECTION_KEY.format(user_id=slot.user_id)
                await self._redis.expire(key, CONNECTION_TTL_SECONDS)

            async def release(self, slot: ConnectionSlot) -> None:
                \"\"\"Remove a connection slot from Redis when the connection closes.

                Args:
                    slot: The connection to remove.
                \"\"\"
                key = CONNECTION_KEY.format(user_id=slot.user_id)
                member = f"{slot.worker_id}:{slot.connection_id}"
                await self._redis.srem(key, member)
        """)
    dest.write_text(content)


def _write_access(dest: Path) -> None:
    """Write ``app/core/sse/access.py`` with ``authorize_channel``.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Channel-level authorization for SSE subscriptions.

        Three channel namespaces are supported:

        * ``user:<uuid>``            — only the matching user may subscribe.
        * ``tenant:<uuid>:<topic>``  — only users belonging to the tenant may subscribe.
        * ``public:<topic>``         — any authenticated user may subscribe.

        Any other prefix results in a 400 Bad Request.
        \"\"\"
        from __future__ import annotations

        from fastapi import HTTPException, status

        from app.models.user import User


        def authorize_channel(user: User, channel: str) -> None:
            \"\"\"Validate that *user* is allowed to subscribe to *channel*.

            Args:
                user: The authenticated requesting user.
                channel: The logical SSE channel string.

            Raises:
                HTTPException: 403 if the user is not allowed.
                HTTPException: 400 if the channel format is invalid.
            \"\"\"
            if channel.startswith("user:"):
                target = channel[len("user:"):]
                if str(user.id) != target:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "Cannot subscribe to another user's channel",
                    )
                return
            if channel.startswith("tenant:"):
                parts = channel.split(":", 2)
                if len(parts) < 3:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid channel format")
                tenant_id = parts[1]
                user_tenant = getattr(user, "tenant_id", None)
                if user_tenant is None or str(user_tenant) != tenant_id:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "Cannot subscribe to another tenant's channel",
                    )
                return
            if channel.startswith("public:"):
                return
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown channel namespace: {channel!r}",
            )
        """)
    dest.write_text(content)


def _write_publisher(dest: Path, replay_buffer_size: int, replay_ttl_seconds: int) -> None:
    """Write ``app/core/sse/publisher.py`` with ``publish_event``.

    Args:
        dest: Absolute path for the new file.
        replay_buffer_size: Max events kept per channel in the sorted-set.
        replay_ttl_seconds: Redis EXPIRE TTL for replay keys.
    """
    content = textwrap.dedent("""\
        \"\"\"SSE publisher: fan-out events to all subscribers via Redis pub/sub.

        ``publish_event`` is the public surface that application code calls.
        It atomically publishes to the pub/sub bus AND writes to the per-channel
        sorted-set replay buffer so reconnecting clients can catch up via
        ``Last-Event-ID``.
        \"\"\"
        from __future__ import annotations

        import json
        import time
        from typing import Any
        from uuid import uuid4

        from app.core.redis import get_redis

        PUBSUB_CHANNEL = "sse:bus:{channel}"
        REPLAY_KEY = "sse:replay:{channel}"
        _REPLAY_BUFFER_SIZE = {buf}
        _REPLAY_TTL = {ttl}
        MAX_PAYLOAD_BYTES = 65_536  # 64 KB hard cap


        async def publish_event(
            channel: str,
            event_name: str,
            payload: dict[str, Any],
            event_id: str | None = None,
        ) -> None:
            \"\"\"Publish an SSE event to *channel*.

            Fan-out is handled by Redis pub/sub so clients connected to any
            worker receive the event.  The event is also written to the
            per-channel sorted-set replay buffer.

            Args:
                channel: Logical channel name (e.g. ``user:<uuid>``).
                event_name: SSE ``event:`` field value.
                payload: JSON-serializable event data.
                event_id: Optional explicit event id.  Auto-generated if omitted.

            Raises:
                ValueError: If the serialized payload exceeds ``MAX_PAYLOAD_BYTES``.
            \"\"\"
            if event_id is None:
                event_id = f"{int(time.time() * 1000)}-{uuid4().hex[:8]}"

            body = json.dumps(
                {"id": event_id, "event": event_name, "data": payload},
                separators=(",", ":"),
                sort_keys=True,
            )
            if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                raise ValueError(f"SSE payload exceeds {MAX_PAYLOAD_BYTES} bytes")

            redis = await get_redis()
            # Score is the numeric ms-timestamp prefix for ZRANGEBYSCORE replay.
            try:
                score = float(event_id.split("-")[0])
            except (ValueError, IndexError):
                score = float(int(time.time() * 1000))

            pipe = redis.pipeline()
            pipe.publish(PUBSUB_CHANNEL.format(channel=channel), body)
            pipe.zadd(REPLAY_KEY.format(channel=channel), {body: score})
            pipe.zremrangebyrank(
                REPLAY_KEY.format(channel=channel), 0, -(_REPLAY_BUFFER_SIZE + 1)
            )
            pipe.expire(REPLAY_KEY.format(channel=channel), _REPLAY_TTL)
            await pipe.execute()
        """).replace("{buf}", str(replay_buffer_size)).replace("{ttl}", str(replay_ttl_seconds))
    dest.write_text(content)


def _write_manager(dest: Path, heartbeat_seconds: int, max_connections_per_user: int) -> None:
    """Write ``app/core/sse/manager.py`` with ``SSEManager`` and ``get_sse_manager``.

    Args:
        dest: Absolute path for the new file.
        heartbeat_seconds: Seconds between keepalive comments.
        max_connections_per_user: Hard limit on simultaneous streams per user.
    """
    content = textwrap.dedent("""\
        \"\"\"SSE Manager: per-channel Redis pub/sub fan-out with replay and heartbeats.

        ``SSEManager.stream`` is consumed by the FastAPI ``StreamingResponse``.
        It handles:

        * Last-Event-ID replay before subscribing to the live channel.
        * Heartbeat comment frames every ``SSE_HEARTBEAT_SECONDS`` to defeat proxies.
        * Per-user connection cap via a Redis counter.
        * Cleanup of the connection slot in a ``try/finally`` so disconnects are safe.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import json
        import logging
        from typing import AsyncIterator
        from uuid import UUID

        from app.core.redis import get_redis
        from app.core.sse.publisher import PUBSUB_CHANNEL, REPLAY_KEY

        logger = logging.getLogger(__name__)

        _HEARTBEAT_SECONDS = {hb}
        _MAX_CONNECTIONS_PER_USER = {cap}
        CONNECTION_COUNT_KEY = "sse:conn:{user_id}"


        class SSEManager:
            \"\"\"Redis-backed SSE fan-out manager.

            One instance per application (singleton via ``get_sse_manager``).
            \"\"\"

            async def _pubsub_loop(
                self,
                ps,
                channel: str,
            ) -> AsyncIterator[bytes]:
                \"\"\"Subscribe to a Redis pubsub channel and yield SSE messages.

                Sends ``:keepalive\\\\n\\\\n`` pings every ``_HEARTBEAT_SECONDS``.
                Unsubscribes and closes the pubsub handle on exit.

                Args:
                    ps: Redis pubsub object (already subscribed on entry).
                    channel: Logical channel name (used only for unsubscribe).

                Yields:
                    SSE-formatted byte chunks (messages or keepalives).
                \"\"\"
                heartbeat_task: asyncio.Task[None] = asyncio.create_task(self._heartbeat_sleep())
                try:
                    while True:
                        msg_task: asyncio.Task[object] = asyncio.create_task(
                            ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        )
                        done, _ = await asyncio.wait({msg_task, heartbeat_task},
                            return_when=asyncio.FIRST_COMPLETED)
                        if heartbeat_task in done:
                            yield b":keepalive\\n\\n"
                            heartbeat_task = asyncio.create_task(self._heartbeat_sleep())
                        if msg_task in done:
                            msg = msg_task.result()
                            if msg and isinstance(msg, dict) and msg.get("type") == "message":
                                yield self._format_message(msg["data"])
                finally:
                    heartbeat_task.cancel()
                    await ps.unsubscribe(PUBSUB_CHANNEL.format(channel=channel))
                    await ps.aclose()


            async def stream(
                self,
                user_id: UUID,
                channel: str,
                last_event_id: str | None,
            ) -> AsyncIterator[bytes]:
                \"\"\"Yield SSE-formatted bytes for the given *channel*.

                Args:
                    user_id: The authenticated user's UUID (used for cap enforcement).
                    channel: Logical channel name.
                    last_event_id: Value from the ``Last-Event-ID`` header, or ``None``.

                Yields:
                    SSE-formatted byte chunks.
                \"\"\"
                redis = await get_redis()
                uid = str(user_id)
                conn_key = CONNECTION_COUNT_KEY.format(user_id=uid)
                count = await redis.incr(conn_key)
                await redis.expire(conn_key, 86400)
                if count > _MAX_CONNECTIONS_PER_USER:
                    await redis.decr(conn_key)
                    yield self._format_error("connection_limit_exceeded")
                    return
                try:
                    if last_event_id:
                        async for chunk in self._replay(redis, channel, last_event_id):
                            yield chunk
                    ps = redis.pubsub()
                    await ps.subscribe(PUBSUB_CHANNEL.format(channel=channel))
                    async for chunk in self._pubsub_loop(ps, channel):
                        yield chunk
                finally:
                    await redis.decr(conn_key)

            async def _heartbeat_sleep(self) -> None:
                \"\"\"Sleep for the configured heartbeat interval.\"\"\"
                await asyncio.sleep(_HEARTBEAT_SECONDS)

            async def _replay(
                self,
                redis: object,
                channel: str,
                last_event_id: str,
            ) -> AsyncIterator[bytes]:
                \"\"\"Yield buffered events with id > *last_event_id*.

                Args:
                    redis: Async Redis client.
                    channel: Logical channel name.
                    last_event_id: Resume point (numeric ms timestamp prefix).

                Yields:
                    SSE-formatted byte chunks for each replayed event.
                \"\"\"
                try:
                    since = float(last_event_id.split("-")[0])
                except (ValueError, IndexError, AttributeError):
                    return
                items = await redis.zrangebyscore(
                    REPLAY_KEY.format(channel=channel),
                    min=f"({since}",
                    max="+inf",
                )
                for raw in items:
                    yield self._format_message(raw)

            def _format_message(self, raw: bytes | str) -> bytes:
                \"\"\"Convert a raw Redis pub/sub message to SSE wire format.

                Args:
                    raw: Raw JSON bytes or string from Redis.

                Returns:
                    UTF-8 encoded SSE frame bytes.
                \"\"\"
                data = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                try:
                    payload = json.loads(data)
                    event_id = payload.get("id", "")
                    event_name = payload.get("event", "message")
                    data_field = json.dumps(
                        payload.get("data", {}), separators=(",", ":"), ensure_ascii=False
                    )
                except (json.JSONDecodeError, TypeError):
                    event_id = ""
                    event_name = "message"
                    data_field = data
                lines: list[str] = []
                if event_id:
                    lines.append(f"id: {event_id}")
                lines.append(f"event: {event_name}")
                for chunk in data_field.split("\\n"):
                    lines.append(f"data: {chunk}")
                lines.append("")
                lines.append("")
                return ("\\n".join(lines)).encode("utf-8")

            def _format_error(self, code: str) -> bytes:
                \"\"\"Return an SSE error event frame.

                Args:
                    code: Short error code string.

                Returns:
                    UTF-8 encoded SSE error frame.
                \"\"\"
                return f"event: error\\ndata: {{\\\"code\\\":\\\"{code}\\\"}}\\n\\n".encode("utf-8")


        _sse_manager: SSEManager | None = None


        def get_sse_manager() -> SSEManager:
            \"\"\"Return the application-wide SSEManager singleton.

            Returns:
                The shared ``SSEManager`` instance.
            \"\"\"
            global _sse_manager
            if _sse_manager is None:
                _sse_manager = SSEManager()
            return _sse_manager
        """).replace("{hb}", str(heartbeat_seconds)).replace("{cap}", str(max_connections_per_user))
    dest.write_text(content)


def _write_events_route(dest: Path) -> None:
    """Write ``app/api/routes/events.py`` with the ``/events/stream`` endpoint.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SSE streaming endpoint.

        GET /events/stream?channel=<name> opens a text/event-stream connection.
        The ``Last-Event-ID`` header is forwarded to the manager for gap-free replay.
        \"\"\"
        from __future__ import annotations

        from typing import Annotated

        from fastapi import APIRouter, Header, Query
        from fastapi.responses import StreamingResponse

        from app.api.deps import CurrentUser
        from app.core.sse.access import authorize_channel
        from app.core.sse.manager import get_sse_manager

        router = APIRouter(prefix="/events", tags=["events"])


        @router.get("/stream", response_model=None)
        async def stream_events(
            current_user: CurrentUser,
            channel: Annotated[str, Query(min_length=3, max_length=255)],
            last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
        ) -> StreamingResponse:
            \"\"\"Open an SSE stream on *channel*.

            Args:
                current_user: Authenticated requesting user.
                channel: Logical channel name (``user:<uuid>``, ``public:<topic>``, etc.).
                last_event_id: Optional ``Last-Event-ID`` header for gap-free reconnect.

            Returns:
                A ``StreamingResponse`` emitting ``text/event-stream`` bytes.
            \"\"\"
            authorize_channel(current_user, channel)
            manager = get_sse_manager()
            return StreamingResponse(
                manager.stream(
                    user_id=current_user.id,
                    channel=channel,
                    last_event_id=last_event_id,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )
        """)
    dest.write_text(content)


def _patch_config(
    config_file: Path,
    heartbeat_seconds: int,
    max_connections_per_user: int,
    replay_buffer_size: int,
    replay_ttl_seconds: int,
) -> None:
    """Inject SSE settings into ``app/core/config.py``.

    Args:
        config_file: Path to the existing config module.
        heartbeat_seconds: Heartbeat interval.
        max_connections_per_user: Connection cap.
        replay_buffer_size: Replay buffer size.
        replay_ttl_seconds: Replay buffer TTL.
    """
    src = config_file.read_text()
    if "SSE_HEARTBEAT_SECONDS" in src:
        return

    snippet = textwrap.dedent("""\

        # --- SSE (Server-Sent Events) settings — added by add_sse tool ---
        SSE_HEARTBEAT_SECONDS: int = {hb}
        SSE_MAX_CONNECTIONS_PER_USER: int = {cap}
        SSE_REPLAY_BUFFER_SIZE: int = {buf}
        SSE_REPLAY_TTL_SECONDS: int = {ttl}
        SSE_MAX_PAYLOAD_BYTES: int = 65_536
        """).replace("{hb}", str(heartbeat_seconds)) \
           .replace("{cap}", str(max_connections_per_user)) \
           .replace("{buf}", str(replay_buffer_size)) \
           .replace("{ttl}", str(replay_ttl_seconds))

    # Append before the last closing line or at end of Settings class
    if "class Settings(" in src:
        # Find the end of the Settings class body
        insert_marker = "\nclass Settings("
        idx = src.rfind(insert_marker)
        if idx != -1:
            # Append before end of file to land inside the class
            src = src.rstrip("\n") + snippet + "\n"
        else:
            src = src + snippet
    else:
        src = src + snippet

    config_file.write_text(src)


def _patch_api_main(routes_init: Path) -> None:
    """Register the events router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.events import router as events_router",
        include_line="api_router.include_router(events_router)",
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
    SSE and realtime tools depend on ``get_redis()`` from this module.

    Args:
        dest: Absolute destination path (``app/core/redis.py``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async Redis client factory for realtime features (SSE, webhooks).\"\"\"

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
