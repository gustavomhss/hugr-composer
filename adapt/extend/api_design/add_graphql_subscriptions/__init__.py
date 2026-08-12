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

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.config_patcher import patch_settings_fields
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

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

_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    # Idempotency guard
    pubsub_file = app_dir / "graphql" / "pubsub.py"
    if pubsub_file.exists():
        body = pubsub_file.read_text()
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

    # Step 0: ship the PubSub motor + Redis adapter
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.events.PubSub"],
        adapters=["core.venous._adapters.redis.PubSubAdapter"],
    )
    files_created.append(manifest.path)

    # Step 1: pubsub.py
    render_to(_HERE, "pubsub.py.tmpl", dest=pubsub_file, substitutions={})
    files_created.append(str(pubsub_file))

    # Step 2: subscriptions.py
    subs_file = gql_dir / "subscriptions.py"
    render_to(_HERE, "subscriptions.py.tmpl", dest=subs_file, substitutions={})
    files_created.append(str(subs_file))

    # Step 3: ws_handler.py
    ws_file = gql_dir / "ws_handler.py"
    render_to(_HERE, "ws_handler.py.tmpl", dest=ws_file, substitutions={})
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
        patch_settings_fields(
            config_file,
            fields=[
                ("GRAPHQL_WS_ENABLED", "GRAPHQL_WS_ENABLED: bool = True"),
                (
                    "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS",
                    "GRAPHQL_SUBSCRIPTION_KEEPALIVE_MS: int = 30_000",
                ),
            ],
        )
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

    # Step 8: emit test
    _emit_project_test(project, files_created)

    import ast
    for fpath in files_created:
        if fpath.endswith(".py"):
            try:
                ast.parse(Path(fpath).read_text())
            except SyntaxError as e:
                return ToolResult(
                    status="error",
                    error=f"Syntax error in {fpath}: {e}",
                    files_created=[],
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


def _patch_or_create_schema(schema_file: Path) -> bool:
    """Patch existing schema.py to include Subscription, or create a minimal one."""
    schema_file.parent.mkdir(parents=True, exist_ok=True)

    if not schema_file.exists():
        render_to(_HERE, "minimal_schema.py.tmpl", dest=schema_file, substitutions={})
        return True

    src = schema_file.read_text()
    if "Subscription" in src:
        return False  # already patched

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

    if "strawberry.Schema(" in src and "subscription=" not in src:
        src = src.replace(
            "strawberry.Schema(",
            "strawberry.Schema(\n    subscription=_GQLSubscription,",
        )

    schema_file.write_text(src)
    return False


def _patch_main(main_file: Path) -> None:
    """Mount the GraphQL WebSocket route in ``app/main.py``."""
    src = main_file.read_text()
    if "/graphql/ws" in src or "graphql_ws_handler" in src:
        return

    ws_import = "from app.graphql.ws_handler import graphql_ws_handler as _gql_ws_handler\n"

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI\n" + ws_import,
        )
    else:
        src = ws_import + src

    mount_block = '\napp.add_api_websocket_route("/graphql/ws", _gql_ws_handler)\n'
    src = src.rstrip("\n") + "\n" + mount_block
    main_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Add strawberry-graphql and graphql-ws to requirements.txt."""
    src = requirements_file.read_text()
    lines_to_add = []
    if "strawberry-graphql" not in src:
        lines_to_add.append("strawberry-graphql[fastapi]>=0.220.0")
    if "graphql-ws" not in src:
        lines_to_add.append("graphql-ws>=0.5.0")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_graphql_subscriptions_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_graphql_subscriptions_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_graphql_subscriptions_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


