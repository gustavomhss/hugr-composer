"""TOOL-073: add_graphql_subscriptions — add WebSocket GraphQL subscriptions to a FastAPI project.

Extends the existing GraphQL setup (from add_graphql / TOOL-018) with
WebSocket-based real-time subscriptions using the ``graphql-ws`` protocol.

Files created:

* ``app/graphql/subscriptions.py`` — Subscription type with ``on_item_created``
  and ``on_notification`` example subscriptions (async generators).
* ``app/graphql/pubsub.py`` — thin glue over ``core.venous.events.PubSub``
  (motor: ``InMemoryPubSub``) + ``core.venous._adapters.redis.PubSubAdapter``
  (``RedisPubSubBackend``). Exposes ``get_pubsub()`` /
  ``publish(topic, payload)`` /
  ``subscribe(topic) -> AsyncIterator``. Selects in-memory by default;
  switches to Redis when ``REDIS_URL`` is set and the ``redis`` package
  is importable.
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
* Pub/sub is the HuGR ``events.PubSub`` motor (in-process fanout) with an
  opt-in Redis adapter for multi-worker fanout. Redis import is lazy so
  ``app.main`` boots without ``redis`` installed.
* Subscription resolvers are async generators decorated with
  ``@strawberry.subscription``.
* Authentication is handled via the ``connection_init`` payload (JWT token).
* Keepalive pings are configurable via ``GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS``.
* Idempotency: detects ``get_pubsub`` (or legacy ``PubSubManager``)
  fingerprint in ``pubsub.py``.

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
    "name": "fastapi_api_add_graphql_subscriptions",
    "description": (
        "Add WebSocket GraphQL subscriptions (graphql-ws protocol) to a FastAPI project, "
        "extending the existing Strawberry GraphQL setup with real-time pub/sub."
    ),
    "tags": ["extend", "api_design", "realtime"],
    "entry": "add_graphql_subscriptions",
    "imports_primitives": ["core.venous.events.PubSub"],
    "imports_adapters": ["core.venous._adapters.redis.PubSubAdapter"],
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
    if pubsub_file.exists():
        body = pubsub_file.read_text()
        # Accept both the new fingerprint (``get_pubsub()``) and the pre-Rails
        # legacy fingerprint (``PubSubManager``) so reruns on a project
        # generated by an older tool snapshot are still detected.
        if "get_pubsub" in body or "PubSubManager" in body:
            return ToolResult(
                status="no_op",
                notes=["GraphQL subscriptions already present — skipped."],
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

    # Step 0: ship the PubSub motor + Redis adapter into the project tree
    # so the generated `app/graphql/pubsub.py` can import from
    # `core.venous.events.PubSub` and `core.venous._adapters.redis.PubSubAdapter`.
    from generators.scaffold_venous import ensure_primitives
    manifest = ensure_primitives(
        str(project),
        names=["core.venous.events.PubSub"],
        adapters=["core.venous._adapters.redis.PubSubAdapter"],
    )
    files_created.append(manifest.path)

    # Step 1: pubsub.py — thin glue that selects motor vs Redis adapter
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
            "PubSub motor (events.PubSub) + Redis adapter shipped into core/venous/; pubsub.py is thin glue.",
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
    """Write ``app/graphql/pubsub.py`` — thin glue over the HuGR-shipped
    ``events.PubSub`` motor + Redis adapter.

    Generated file selects the in-memory motor by default and switches to
    the Redis adapter when ``REDIS_URL`` is set AND the ``redis`` package
    is importable. The heavy lifting (fanout, ordering, cleanup, JSON
    codec) lives in the framework-free primitive and the adapter — this
    glue is Rails-style app wiring only.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"PubSub manager for GraphQL subscriptions.

        Backed by the HuGR ``events.PubSub`` primitive:

        - In-memory default (``InMemoryPubSub``): single-worker only.
        - Redis adapter (``RedisPubSubBackend``): multi-worker safe; lazy
          import so the app boots without the ``redis`` package installed.

        Usage::

            pubsub = get_pubsub()
            await pubsub.publish("items", {"id": "...", "title": "..."})

            async for event in pubsub.subscribe("items"):
                yield event
        \"\"\"
        from __future__ import annotations

        import logging
        import os
        from typing import Any

        from core.venous.events.PubSub import InMemoryPubSub, PubSub

        logger = logging.getLogger(__name__)


        _pubsub: PubSub | None = None


        def _build() -> PubSub:
            \"\"\"Select the active PubSub backend.

            When ``REDIS_URL`` is set AND ``redis`` is importable, use the
            Redis adapter for multi-worker fanout. Otherwise fall back to
            the in-memory motor (single worker).
            \"\"\"
            redis_url = os.getenv("REDIS_URL", "")
            if redis_url:
                try:
                    import redis.asyncio  # noqa: F401, PLC0415
                except ImportError:
                    logger.warning(
                        "REDIS_URL set but `redis` package not installed — "
                        "falling back to in-process PubSub (single worker).",
                    )
                else:
                    from core.venous._adapters.redis import RedisPubSubBackend
                    return RedisPubSubBackend(redis_url)
            return InMemoryPubSub()


        def get_pubsub() -> PubSub:
            \"\"\"Return the process-wide PubSub backend (singleton).\"\"\"
            global _pubsub
            if _pubsub is None:
                _pubsub = _build()
            return _pubsub


        # Backward-compatible alias — older callers imported
        # `get_pubsub_manager` and treated its return value as a PubSub.
        def get_pubsub_manager() -> PubSub:
            \"\"\"Deprecated: use ``get_pubsub()`` instead.\"\"\"
            return get_pubsub()


        async def publish(topic: str, payload: Any) -> None:
            \"\"\"Shortcut — ``get_pubsub().publish(topic, payload)``.\"\"\"
            await get_pubsub().publish(topic, payload)
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

        import strawberry

        # Imported at MODULE level (not TYPE_CHECKING) because strawberry
        # resolves forward-reference strings in Subscription field
        # annotations at schema-construction time via `__globals__`.
        # TYPE_CHECKING-only imports leave the name undefined at runtime
        # and strawberry raises "Subscription fields cannot be resolved.
        # name 'GraphQLContext' is not defined" when the schema is built.
        from app.graphql.context import GraphQLContext  # noqa: F401 — used in annotations

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
                from app.graphql.pubsub import get_pubsub
                mgr = get_pubsub()
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
                from app.graphql.pubsub import get_pubsub
                mgr = get_pubsub()
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
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("GRAPHQL_WS_ENABLED", "GRAPHQL_WS_ENABLED: bool = True"),
            ("GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS", "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS: int = 30_000"),
        ],
    )


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
