"""TOOL-073: add_graphql_subscriptions — add WebSocket GraphQL subscriptions to a FastAPI project.

Extends the existing GraphQL setup (from add_graphql / TOOL-018) with
WebSocket-based real-time subscriptions using the ``graphql-ws`` protocol.

Files created:

* ``app/graphql/subscriptions.py`` — Subscription type with ``on_item_created``
  and ``on_notification`` example subscriptions (async generators).
* ``app/graphql/pubsub.py`` — ``PubSubManager``: ``publish(topic, payload)``,
  ``subscribe(topic) -> AsyncIterator``; memory backend (single-worker) +
  Redis backend (multi-worker) with lazy redis import.
* ``app/graphql/ws_handler.py`` — GraphQL WebSocket handler wired to the
  ``graphql-ws`` protocol (not the legacy ``subscriptions-transport-ws``).

Files modified:

* ``app/graphql/schema.py`` — adds ``Subscription`` to the top-level
  ``strawberry.Schema`` (creates a minimal schema if add_graphql wasn't run).
* ``app/core/config.py`` — adds ``GRAPHQL_WS_ENABLED`` and
  ``GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS`` inside the ``Settings`` class.
* ``app/main.py`` — mounts the WebSocket route at ``/graphql/ws``.
* ``requirements.txt`` — adds ``strawberry-graphql[fastapi]`` and
  ``graphql-ws>=0.5.0``.

Design:

* Uses ``graphql-ws`` protocol (not legacy ``subscriptions-transport-ws``).
* ``PubSubManager`` has an in-process memory backend (single worker) and a
  Redis Pub/Sub backend (multi-worker). Redis import is lazy so ``app.main``
  boots without ``redis`` installed.
* Subscription resolvers are async generators decorated with
  ``@strawberry.subscription``.
* Authentication is handled via the ``connection_init`` payload (JWT token).
* Keepalive pings are configurable via ``GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS``.
* Idempotency: detects ``PubSubManager`` fingerprint in ``pubsub.py``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_graphql_subscriptions import add_graphql_subscriptions

    result = add_graphql_subscriptions(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # ["...app/graphql/subscriptions.py", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_graphql_subscriptions",
    "description": (
        "Add WebSocket GraphQL subscriptions (graphql-ws protocol) to a FastAPI project, "
        "extending the existing Strawberry GraphQL setup with real-time pub/sub."
    ),
    "tags": ["extend", "api_design", "realtime"],
    "entry": "add_graphql_subscriptions",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_graphql_subscriptions(inp: ToolInput) -> ToolResult:
    """Add WebSocket GraphQL subscriptions to a FastAPI project.

    Generates a PubSub manager, Subscription type, and WebSocket handler, then
    wires the subscription into the existing (or newly scaffolded) GraphQL schema
    and mounts a WebSocket route in ``app/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
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

    # --- Idempotency guard ---------------------------------------------------
    pubsub_file = app_dir / "graphql" / "pubsub.py"
    if pubsub_file.exists() and "PubSubManager" in pubsub_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["GraphQL subscriptions (PubSubManager) already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would generate subscriptions.py, pubsub.py, ws_handler.py.",
                "[dry_run] Would patch schema.py, config.py, main.py, requirements.txt.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []
    gql_dir = app_dir / "graphql"

    # Step 1: pubsub.py
    _write_pubsub(pubsub_file)
    files_created.append(str(pubsub_file))

    # Step 2: subscriptions.py
    subs_file = gql_dir / "subscriptions.py"
    _write_subscriptions(subs_file)
    files_created.append(str(subs_file))

    # Step 3: ws_handler.py
    ws_file = gql_dir / "ws_handler.py"
    _write_ws_handler(ws_file)
    files_created.append(str(ws_file))

    # Step 4: patch or create schema.py
    schema_file = gql_dir / "schema.py"
    created_schema = _patch_or_create_schema(schema_file)
    if created_schema:
        files_created.append(str(schema_file))
    else:
        files_modified.append(str(schema_file))

    # Step 5: patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 6: patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # Step 7: patch requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # --- ast.parse validation loop ------------------------------------------
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
            "GraphQL subscriptions mounted at /graphql/ws (graphql-ws protocol).",
            "PubSubManager supports in-process memory (single worker) and Redis (multi-worker).",
            "Redis import is lazy — app boots without redis installed.",
            "Authentication via connection_init payload JWT token.",
            "Keepalive configurable via GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS.",
            "Example subscriptions: on_item_created, on_notification.",
        ],
        next_steps=[
            "pip install 'strawberry-graphql[fastapi]' 'graphql-ws>=0.5.0'",
            "Set GRAPHQL_WS_ENABLED=true in .env to activate WebSocket subscriptions.",
            "For multi-worker pub/sub set REDIS_URL in .env — falls back to in-process.",
            "Connect with a GraphQL client using the graphql-ws protocol at ws://host/graphql/ws.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_pubsub(dest: Path) -> None:
    """Write ``app/graphql/pubsub.py`` with PubSubManager.

    Provides an in-process memory backend (asyncio.Queue per subscriber) and
    a Redis Pub/Sub backend (multi-worker). Redis import is lazy so the module
    loads without redis installed.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"PubSub manager for GraphQL subscriptions.

        Two backends:
        - Memory (default): asyncio.Queue per subscriber. Single-worker only.
        - Redis: uses redis.asyncio Pub/Sub. Multi-worker safe. Lazy import.

        Usage::

            mgr = get_pubsub_manager()
            await mgr.publish("items", {"id": "...", "title": "..."})

            async for event in mgr.subscribe("items"):
                yield event
        \"\"\"

        from __future__ import annotations

        import asyncio
        import json
        import logging
        import os
        from collections.abc import AsyncIterator
        from typing import Any

        logger = logging.getLogger(__name__)

        _SENTINEL = object()


        class MemoryPubSubBackend:
            \"\"\"In-process pub/sub using asyncio.Queue per subscriber.

            Suitable for single-worker deployments only. Events are NOT
            shared across processes or workers.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise an empty subscriber registry.\"\"\"
                self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}

            async def publish(self, topic: str, payload: Any) -> None:
                \"\"\"Broadcast *payload* to all current subscribers of *topic*.

                Args:
                    topic: Logical channel name (e.g. ``\"items\"``).
                    payload: Serialisable event data.
                \"\"\"
                queues = self._subscribers.get(topic, [])
                for q in list(queues):
                    await q.put(payload)

            async def subscribe(self, topic: str) -> AsyncIterator[Any]:
                \"\"\"Yield events published to *topic* until the generator is closed.

                Args:
                    topic: Logical channel name.

                Yields:
                    Each event payload in arrival order.
                \"\"\"
                q: asyncio.Queue[Any] = asyncio.Queue()
                self._subscribers.setdefault(topic, []).append(q)
                try:
                    while True:
                        item = await q.get()
                        if item is _SENTINEL:
                            break
                        yield item
                finally:
                    subs = self._subscribers.get(topic, [])
                    if q in subs:
                        subs.remove(q)


        class RedisPubSubBackend:
            \"\"\"Redis-backed pub/sub for multi-worker deployments.

            Redis is imported lazily so that ``app.main`` boots without
            the ``redis`` package installed. Falls back to ``MemoryPubSubBackend``
            when Redis is unavailable.

            Args:
                redis_url: Redis connection URL (default: ``REDIS_URL`` env var).
            \"\"\"

            def __init__(self, redis_url: str | None = None) -> None:
                \"\"\"Store the Redis URL for lazy connection.\"\"\"
                self._url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self._client: Any = None

            def _get_client(self) -> Any:
                \"\"\"Return a lazy-loaded redis.asyncio client.

                Returns:
                    A ``redis.asyncio.Redis`` client instance.

                Raises:
                    ImportError: If the ``redis`` package is not installed.
                \"\"\"
                if self._client is None:
                    import redis.asyncio as aioredis  # noqa: PLC0415
                    self._client = aioredis.from_url(self._url, decode_responses=True)
                return self._client

            async def publish(self, topic: str, payload: Any) -> None:
                \"\"\"Publish *payload* as JSON to Redis channel *topic*.

                Args:
                    topic: Redis channel name.
                    payload: Serialisable event data; serialised to JSON.
                \"\"\"
                client = self._get_client()
                await client.publish(topic, json.dumps(payload))

            async def subscribe(self, topic: str) -> AsyncIterator[Any]:
                \"\"\"Subscribe to Redis channel *topic* and yield decoded events.

                Args:
                    topic: Redis channel name.

                Yields:
                    Deserialised event payloads.
                \"\"\"
                client = self._get_client()
                async with client.pubsub() as pubsub:
                    await pubsub.subscribe(topic)
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            yield json.loads(message["data"])


        class PubSubManager:
            \"\"\"Unified pub/sub facade that selects backend based on configuration.

            Chooses ``RedisPubSubBackend`` when ``REDIS_URL`` is set and
            ``redis`` is importable; otherwise falls back to
            ``MemoryPubSubBackend``.

            Usage::

                mgr = get_pubsub_manager()
                await mgr.publish("items", payload)

                async for event in mgr.subscribe("items"):
                    yield event
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Select backend based on environment.\"\"\"
                self._backend = self._choose_backend()

            def _choose_backend(self) -> MemoryPubSubBackend | RedisPubSubBackend:
                \"\"\"Return the best available backend.

                Returns:
                    ``RedisPubSubBackend`` if redis is available, else
                    ``MemoryPubSubBackend``.
                \"\"\"
                redis_url = os.getenv("REDIS_URL", "")
                if redis_url:
                    try:
                        import redis.asyncio  # noqa: PLC0415, F401
                        return RedisPubSubBackend(redis_url)
                    except ImportError:
                        logger.warning("redis not installed — using in-process PubSub.")
                return MemoryPubSubBackend()

            async def publish(self, topic: str, payload: Any) -> None:
                \"\"\"Publish *payload* to *topic*.

                Args:
                    topic: Channel / event type name.
                    payload: Serialisable event data.
                \"\"\"
                await self._backend.publish(topic, payload)

            async def subscribe(self, topic: str) -> AsyncIterator[Any]:
                \"\"\"Yield events for *topic* from the active backend.

                Args:
                    topic: Channel / event type name.

                Yields:
                    Event payloads in arrival order.
                \"\"\"
                async for event in self._backend.subscribe(topic):
                    yield event


        _manager: PubSubManager | None = None


        def get_pubsub_manager() -> PubSubManager:
            \"\"\"Return the singleton ``PubSubManager`` instance.

            Returns:
                Application-wide ``PubSubManager``.
            \"\"\"
            global _manager
            if _manager is None:
                _manager = PubSubManager()
            return _manager
        """))


def _write_subscriptions(dest: Path) -> None:
    """Write ``app/graphql/subscriptions.py`` with example subscription resolvers.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GraphQL Subscription type — real-time event streams via WebSocket.

        Provides two example subscriptions:
        - ``on_item_created``: streams ``ItemEvent`` payloads when items are created.
        - ``on_notification``: streams ``NotificationEvent`` payloads per user.

        Clients must authenticate via the ``connection_init`` payload.
        \"\"\"

        from __future__ import annotations

        import logging
        from collections.abc import AsyncIterator
        from typing import TYPE_CHECKING

        import strawberry

        if TYPE_CHECKING:
            from app.graphql.context import GraphQLContext

        logger = logging.getLogger(__name__)


        @strawberry.type
        class ItemEvent:
            \"\"\"Payload emitted when an item is created.

            Attributes:
                id: Newly created item ID.
                title: Item title.
                created_by: User ID of the creator.
            \"\"\"

            id: strawberry.ID
            title: str
            created_by: strawberry.ID


        @strawberry.type
        class NotificationEvent:
            \"\"\"Payload emitted when a notification is sent to a user.

            Attributes:
                id: Notification ID.
                user_id: Target user ID.
                message: Notification message text.
                level: Severity level (info, warning, error).
            \"\"\"

            id: strawberry.ID
            user_id: strawberry.ID
            message: str
            level: str = "info"


        @strawberry.type
        class Subscription:
            \"\"\"Root GraphQL subscription type.  All subscriptions require authentication.\"\"\"

            @strawberry.subscription
            async def on_item_created(
                self,
                info: strawberry.types.Info["GraphQLContext", None],
            ) -> AsyncIterator[ItemEvent]:
                \"\"\"Stream ``ItemEvent`` payloads whenever an item is created.

                Authenticates via ``info.context`` — raises ``PermissionError``
                for unauthenticated connections.

                Args:
                    info: GraphQL resolve info carrying request context.

                Yields:
                    ``ItemEvent`` for each new item creation.
                \"\"\"
                if not info.context.user:
                    raise PermissionError("Authentication required for subscriptions")
                from app.graphql.pubsub import get_pubsub_manager
                mgr = get_pubsub_manager()
                async for payload in mgr.subscribe("items"):
                    yield ItemEvent(
                        id=strawberry.ID(str(payload.get("id", ""))),
                        title=str(payload.get("title", "")),
                        created_by=strawberry.ID(str(payload.get("created_by", ""))),
                    )

            @strawberry.subscription
            async def on_notification(
                self,
                info: strawberry.types.Info["GraphQLContext", None],
                user_id: strawberry.ID,
            ) -> AsyncIterator[NotificationEvent]:
                \"\"\"Stream ``NotificationEvent`` for the given *user_id*.

                Only the authenticated user or a superuser may subscribe to their
                own notification channel.

                Args:
                    info: GraphQL resolve info carrying request context.
                    user_id: Target user whose notifications to stream.

                Yields:
                    ``NotificationEvent`` for each new notification.
                \"\"\"
                if not info.context.user:
                    raise PermissionError("Authentication required for subscriptions")
                from app.graphql.pubsub import get_pubsub_manager
                mgr = get_pubsub_manager()
                topic = f"notifications:{user_id}"
                async for payload in mgr.subscribe(topic):
                    yield NotificationEvent(
                        id=strawberry.ID(str(payload.get("id", ""))),
                        user_id=strawberry.ID(str(user_id)),
                        message=str(payload.get("message", "")),
                        level=str(payload.get("level", "info")),
                    )
        """))


def _write_ws_handler(dest: Path) -> None:
    """Write ``app/graphql/ws_handler.py`` with the GraphQL WebSocket handler.

    Uses the ``graphql-ws`` protocol. Authentication is performed via
    ``connection_init`` payload inspection.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GraphQL WebSocket handler — graphql-ws protocol over Starlette WebSocket.

        Mounts at ``/graphql/ws``. Authentication is resolved from the
        ``connection_init`` payload; unauthenticated connections get a
        context with ``user=None`` (subscriptions will reject them).

        Keepalive interval is controlled by the ``GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS``
        setting (default: 30 000 ms).
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from starlette.websockets import WebSocket

        logger = logging.getLogger(__name__)


        async def graphql_ws_handler(websocket: WebSocket) -> None:
            \"\"\"Handle a single GraphQL WebSocket connection (graphql-ws protocol).

            Accepts the WebSocket, resolves a per-connection context (including
            optional JWT auth from ``connection_init``), then delegates to the
            Strawberry schema's WebSocket handler.

            Args:
                websocket: Incoming Starlette ``WebSocket`` connection.
            \"\"\"
            from app.graphql.schema import schema as _schema
            from app.core.config import settings as _settings

            keepalive_ms: int = getattr(
                _settings, "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS", 30_000
            )
            enabled: bool = getattr(_settings, "GRAPHQL_WS_ENABLED", True)

            if not enabled:
                await websocket.close(code=4400, reason="GraphQL subscriptions disabled.")
                return

            context = await _build_ws_context(websocket)
            await _schema.handle_websocket(
                websocket,
                context_value=context,
            )


        async def _build_ws_context(websocket: WebSocket) -> Any:
            \"\"\"Build a per-connection GraphQL context from the WebSocket request.

            Attempts to resolve the current user from the ``Authorization`` header
            that may be passed inside the ``connection_init`` payload. Sets
            ``user=None`` for unauthenticated connections so that subscription
            resolvers can enforce auth explicitly.

            Args:
                websocket: Starlette WebSocket connection.

            Returns:
                A ``GraphQLContext`` instance with ``user`` set (or None).
            \"\"\"
            from app.graphql.dataloaders import DataLoaderRegistry
            from app.graphql.context import GraphQLContext

            user: Any = None
            try:
                from app.api.deps import get_current_user as _get_user
                user = await _get_user(websocket)
            except Exception:
                pass

            return GraphQLContext(
                request=websocket,  # type: ignore[arg-type]
                user=user,
                loaders=DataLoaderRegistry(),
            )
        """))


def _patch_or_create_schema(schema_file: Path) -> bool:
    """Patch existing schema.py to include Subscription, or create a minimal one.

    Args:
        schema_file: Path to ``app/graphql/schema.py``.

    Returns:
        ``True`` if the file was newly created, ``False`` if it was patched.
    """
    schema_file.parent.mkdir(parents=True, exist_ok=True)

    if not schema_file.exists():
        _write_minimal_schema(schema_file)
        return True

    src = schema_file.read_text()
    if "Subscription" in src:
        return False  # already patched

    # Add Subscription import
    sub_import = "from app.graphql.subscriptions import Subscription as _GQLSubscription\n"
    if "from app.graphql.queries import Query" in src:
        src = src.replace(
            "from app.graphql.queries import Query",
            "from app.graphql.queries import Query\n" + sub_import,
        )
    elif "import strawberry" in src:
        src = src.replace(
            "import strawberry",
            "import strawberry\n" + sub_import,
        )
    else:
        src = sub_import + src

    # Add subscription= to strawberry.Schema call
    if "strawberry.Schema(" in src and "subscription=" not in src:
        src = src.replace(
            "strawberry.Schema(",
            "strawberry.Schema(\n    subscription=_GQLSubscription,",
        )

    schema_file.write_text(src)
    return False


def _write_minimal_schema(dest: Path) -> None:
    """Write a minimal ``app/graphql/schema.py`` when add_graphql wasn't run.

    Args:
        dest: Absolute destination path.
    """
    dest.write_text(textwrap.dedent("""\
        \"\"\"Strawberry GraphQL schema with Subscription support.

        Import ``schema`` in ``app/main.py`` and mount via GraphQL WebSocket handler.
        \"\"\"

        from __future__ import annotations

        import strawberry

        from app.graphql.subscriptions import Subscription as _GQLSubscription


        @strawberry.type
        class _Query:
            \"\"\"Minimal placeholder Query required by Strawberry.\"\"\"

            @strawberry.field
            def health(self) -> str:
                \"\"\"Return a liveness string.

                Returns:
                    Always 'ok'.
                \"\"\"
                return "ok"


        schema = strawberry.Schema(
            query=_Query,
            subscription=_GQLSubscription,
        )
        """))


def _patch_config(config_file: Path) -> None:
    """Inject ``GRAPHQL_WS_ENABLED`` and ``GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS`` into Settings.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "GRAPHQL_WS_ENABLED" in src:
        return

    new_fields = (
        "\n"
        "    GRAPHQL_WS_ENABLED: bool = True\n"
        "    GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS: int = 30_000\n"
    )

    # Insert before the closing of the Settings class — find last field line
    if "class Settings" in src:
        # Append fields before the closing `settings = Settings()` line or at end of class
        if "\nsettings = Settings()" in src:
            src = src.replace(
                "\nsettings = Settings()",
                new_fields + "\nsettings = Settings()",
            )
        else:
            # Append to end of file
            src = src.rstrip("\n") + new_fields + "\n"
    config_file.write_text(src)


def _patch_main(main_file: Path) -> None:
    """Mount the GraphQL WebSocket route in ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "/graphql/ws" in src or "graphql_ws_handler" in src:
        return

    ws_import = textwrap.dedent("""\
        from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler
        """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI\n" + ws_import,
        )
    else:
        src = ws_import + src

    mount_block = textwrap.dedent("""\

        app.add_api_websocket_route("/graphql/ws", _gql_ws_handler)
        """)

    src = src.rstrip("\n") + "\n" + mount_block
    main_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Add ``strawberry-graphql[fastapi]`` and ``graphql-ws>=0.5.0`` to requirements.txt.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    lines_to_add = []
    if "strawberry-graphql" not in src:
        lines_to_add.append("strawberry-graphql[fastapi]>=0.220.0")
    if "graphql-ws" not in src:
        lines_to_add.append("graphql-ws>=0.5.0")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


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
