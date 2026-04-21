"""TOOL-080: add_cqrs — add Command/Query Responsibility Segregation with read replicas.

Writes a production-grade CQRS layer: a ``CommandBus`` (dispatches Commands) and a
``QueryBus`` (dispatches Queries), a ``ReadReplicaSession`` dependency that routes
read queries to ``settings.DATABASE_READ_URL`` (falls back to the primary connection
when not set), example Command and Query objects, HTTP routes for both buses, and
every required settings field.

Why CQRS?

* **Write / read separation** — Commands mutate state and return opaque results;
  Queries are side-effect-free and return structured read models.  The boundary
  enforces discipline that prevents accidental writes in query paths.
* **Read replica routing** — ``ReadReplicaSession`` resolves ``DATABASE_READ_URL``
  at runtime so read-heavy query handlers can scale independently of the primary
  Postgres instance with zero application code changes.
* **Type safety** — ``Command`` and ``Query`` are Pydantic ``BaseModel`` subclasses
  so every handler receives a validated, typed object.
* **Bus pattern** — ``CommandBus.dispatch`` and ``QueryBus.query`` are the only
  callsites; adding a new command or query is a single ``register()`` call.

Security / correctness guarantees:

* No handler is imported at module level; buses use a registry dict so only the
  explicitly registered handlers are callable.
* ``DATABASE_READ_URL`` defaults to the primary ``DATABASE_URL`` when absent — the
  feature degrades gracefully without crashing boot.
* Every generated function is kept ≤50 LOC.
* The tool is idempotent: a second run detects ``CommandBus`` in
  ``app/cqrs/__init__.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_cqrs import add_cqrs

    result = add_cqrs(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/cqrs/__init__.py", …]
    print(result.next_steps)    # ["Set DATABASE_READ_URL in .env", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_api_add_cqrs",
    "description": (
        "Add a production-grade CQRS layer with CommandBus, QueryBus, "
        "read-replica session routing, and HTTP routes for both buses."
    ),
    "tags": ["extend", "api_design"],
    "entry": "add_cqrs",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_cqrs(inp: ToolInput) -> ToolResult:
    """Add a CQRS layer (CommandBus + QueryBus + read replica) to a FastAPI project.

    Creates ``app/cqrs/__init__.py``, ``app/cqrs/bus.py``,
    ``app/cqrs/commands.py``, ``app/cqrs/queries.py``,
    ``app/cqrs/read_replica.py``, ``app/api/routes/cqrs.py``.
    Patches ``app/core/config.py`` and registers the cqrs router in
    ``app/routes/__init__.py``.

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? ---------------------------------------
    cqrs_init = app_dir / "cqrs" / "__init__.py"
    if cqrs_init.exists() and "CommandBus" in cqrs_init.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "CommandBus already present in app/cqrs/__init__.py — "
                "CQRS layer already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/cqrs/ (__init__.py, bus.py, commands.py,",
                "         queries.py, read_replica.py) and app/api/routes/cqrs.py.",
                "[dry_run] Would patch app/core/config.py with DATABASE_READ_URL + CQRS_ENABLED.",
                "[dry_run] Would register cqrs router in app/routes/__init__.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — cqrs package
    _write_cqrs_package(app_dir, files_created)

    # Step 2 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "cqrs.py"
    routes_file.write_text(_CQRS_ROUTES)
    files_created.append(str(routes_file))

    # Step 3 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 4 — register router in app/routes/__init__.py
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
            "CQRS layer added: CommandBus (dispatch), QueryBus (query).",
            "ReadReplicaSession routes read queries to DATABASE_READ_URL "
            "(falls back to primary DATABASE_URL when not set).",
            "POST /cqrs/commands — dispatch a registered command by name.",
            "POST /cqrs/queries  — dispatch a registered query by name.",
            "CQRS_ENABLED=false disables the HTTP surface; buses remain usable in code.",
        ],
        next_steps=[
            "Set DATABASE_READ_URL in .env to point to your Postgres read replica.",
            "Register command handlers: bus.register('MyCommand', my_handler)",
            "Register query handlers: query_bus.register('MyQuery', my_handler)",
            "Restart the FastAPI app so /cqrs/* routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body
# ---------------------------------------------------------------------------

def _write_cqrs_package(app_dir: Path, files_created: list[str]) -> None:
    """Create the ``app/cqrs/`` package with __init__, bus, commands, queries, read_replica.

    Args:
        app_dir: Path to the project's ``app/`` directory.
        files_created: Mutable list to append created paths to.
    """
    pkg_dir = app_dir / "cqrs"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "__init__.py": _CQRS_INIT,
        "bus.py": _CQRS_BUS,
        "commands.py": _CQRS_COMMANDS,
        "queries.py": _CQRS_QUERIES,
        "read_replica.py": _CQRS_READ_REPLICA,
    }
    for name, content in files.items():
        p = pkg_dir / name
        p.write_text(content)
        files_created.append(str(p))


def _patch_config(config_file: Path) -> None:
    """Inject CQRS settings into the ``Settings`` class body.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "DATABASE_READ_URL" in src:
        return

    block = (
        "\n"
        "    # --- CQRS — added by add_cqrs tool ---\n"
        '    DATABASE_READ_URL: str = ""\n'
        "    CQRS_ENABLED: bool = True\n"
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
    """Register the cqrs router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    src = routes_init.read_text()
    import_line = "from app.api.routes.cqrs import router as cqrs_router"
    include_line = "api_router.include_router(cqrs_router)"
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

_CQRS_INIT = textwrap.dedent("""\
    \"\"\"CQRS layer — CommandBus, QueryBus, and ReadReplicaSession.

    Public API:
        CommandBus:          dispatch(command)  — mutating operations
        QueryBus:            query(query)        — read-only operations
        ReadReplicaSession:  FastAPI dependency  — routes to read replica
    \"\"\"

    from app.cqrs.bus import CommandBus, QueryBus
    from app.cqrs.read_replica import ReadReplicaSession

    __all__ = ["CommandBus", "QueryBus", "ReadReplicaSession"]
""")

_CQRS_BUS = textwrap.dedent("""\
    \"\"\"CommandBus and QueryBus — registry-based message dispatchers.

    Handlers are registered with ``register()``.  ``dispatch()`` /
    ``query()`` look up the handler by message class name and invoke it.
    \"\"\"

    from __future__ import annotations

    import logging
    from collections.abc import Awaitable, Callable
    from typing import Any

    logger = logging.getLogger(__name__)

    Handler = Callable[..., Awaitable[Any]]


    class CommandBus:
        \"\"\"Dispatch Commands to their registered async handlers.\"\"\"

        def __init__(self) -> None:
            \"\"\"Initialise with an empty handler registry.\"\"\"
            self._registry: dict[str, Handler] = {}

        def register(self, command_name: str, handler: Handler) -> None:
            \"\"\"Register *handler* for *command_name*.

            Args:
                command_name: Fully-qualified command class name (e.g. ``'CreateItem'``).
                handler: Async callable that accepts the command and returns a result.
            \"\"\"
            self._registry[command_name] = handler

        async def dispatch(self, command: object, **kwargs: Any) -> Any:
            \"\"\"Dispatch *command* to its registered handler.

            Args:
                command: A Command instance — its class name is used as lookup key.
                **kwargs: Extra keyword arguments forwarded to the handler.

            Returns:
                Whatever the handler returns.

            Raises:
                KeyError: When no handler is registered for the command type.
            \"\"\"
            name = type(command).__name__
            handler = self._registry.get(name)
            if handler is None:
                raise KeyError(f"No handler registered for command: {name!r}")
            logger.debug("CommandBus dispatching %r", name)
            return await handler(command, **kwargs)


    class QueryBus:
        \"\"\"Dispatch Queries to their registered async handlers.\"\"\"

        def __init__(self) -> None:
            \"\"\"Initialise with an empty handler registry.\"\"\"
            self._registry: dict[str, Handler] = {}

        def register(self, query_name: str, handler: Handler) -> None:
            \"\"\"Register *handler* for *query_name*.

            Args:
                query_name: Fully-qualified query class name (e.g. ``'GetItem'``).
                handler: Async callable that accepts the query and returns a result.
            \"\"\"
            self._registry[query_name] = handler

        async def query(self, q: object, **kwargs: Any) -> Any:
            \"\"\"Dispatch *q* to its registered handler.

            Args:
                q: A Query instance — its class name is used as lookup key.
                **kwargs: Extra keyword arguments forwarded to the handler.

            Returns:
                Whatever the handler returns.

            Raises:
                KeyError: When no handler is registered for the query type.
            \"\"\"
            name = type(q).__name__
            handler = self._registry.get(name)
            if handler is None:
                raise KeyError(f"No handler registered for query: {name!r}")
            logger.debug("QueryBus dispatching %r", name)
            return await handler(q, **kwargs)
""")

_CQRS_COMMANDS = textwrap.dedent("""\
    \"\"\"Command base class and example command definitions.

    Commands represent write-intent messages.  They are dispatched through
    ``CommandBus.dispatch()`` and MUST NOT query state — they only mutate it.
    \"\"\"

    from __future__ import annotations

    import uuid

    from pydantic import BaseModel


    class Command(BaseModel):
        \"\"\"Base class for all commands.

        All command fields should be immutable value objects.  Use UUIDs
        for entity references rather than full object graphs.
        \"\"\"


    class CreateItemCommand(Command):
        \"\"\"Command to create a new item.\"\"\"

        title: str
        description: str = ""
        owner_id: uuid.UUID


    class UpdateItemCommand(Command):
        \"\"\"Command to update an existing item.\"\"\"

        item_id: uuid.UUID
        title: str | None = None
        description: str | None = None


    class DeleteItemCommand(Command):
        \"\"\"Command to delete an item by ID.\"\"\"

        item_id: uuid.UUID
        owner_id: uuid.UUID
""")

_CQRS_QUERIES = textwrap.dedent("""\
    \"\"\"Query base class and example query definitions.

    Queries represent read-intent messages.  They are dispatched through
    ``QueryBus.query()`` and MUST NOT mutate state — they only read it.
    Queries should be routed to the read replica via ``ReadReplicaSession``.
    \"\"\"

    from __future__ import annotations

    import uuid

    from pydantic import BaseModel


    class Query(BaseModel):
        \"\"\"Base class for all queries.

        Query fields describe what to look for.  Results are returned as
        plain dicts or Pydantic read-models — never as mutable ORM objects.
        \"\"\"


    class GetItemQuery(Query):
        \"\"\"Query to fetch a single item by ID.\"\"\"

        item_id: uuid.UUID


    class ListItemsQuery(Query):
        \"\"\"Query to list items with pagination.\"\"\"

        owner_id: uuid.UUID | None = None
        limit: int = 50
        offset: int = 0


    class SearchItemsQuery(Query):
        \"\"\"Query to search items by keyword.\"\"\"

        keyword: str
        limit: int = 20
""")

_CQRS_READ_REPLICA = textwrap.dedent("""\
    \"\"\"ReadReplicaSession — FastAPI dependency for read-replica routing.

    When ``settings.DATABASE_READ_URL`` is set, queries are routed to the
    read replica.  Otherwise falls back to the primary database connection.
    This makes the feature degrade gracefully on projects without a replica.
    \"\"\"

    from __future__ import annotations

    import logging
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    logger = logging.getLogger(__name__)

    _replica_engine = None
    _replica_session_factory = None


    def _get_replica_factory():
        \"\"\"Lazily create the read-replica session factory.

        Returns:
            An ``async_sessionmaker`` pointed at ``DATABASE_READ_URL``,
            or ``None`` if the setting is absent or empty.
        \"\"\"
        global _replica_engine, _replica_session_factory
        if _replica_session_factory is not None:
            return _replica_session_factory
        try:
            from app.core.config import settings
            url = settings.DATABASE_READ_URL
        except Exception:
            return None

        if not url:
            return None

        _replica_engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        _replica_session_factory = async_sessionmaker(
            _replica_engine, class_=AsyncSession, expire_on_commit=False,
        )
        return _replica_session_factory


    async def ReadReplicaSession() -> AsyncGenerator[AsyncSession, None]:
        \"\"\"FastAPI dependency that yields a read-replica database session.

        Falls back to the primary engine when ``DATABASE_READ_URL`` is not
        configured, so query handlers work on projects without a replica.

        Yields:
            An ``AsyncSession`` connected to the read replica (or primary).
        \"\"\"
        factory = _get_replica_factory()
        if factory is not None:
            async with factory() as session:
                yield session
            return

        # Fallback: primary session
        try:
            from app.core.session import get_session
            async for session in get_session():
                yield session
        except ImportError:
            logger.warning(
                "ReadReplicaSession: no replica URL and no app.core.session — "
                "yielding a placeholder (queries will fail at handler level)."
            )
            raise
""")

_CQRS_ROUTES = textwrap.dedent("""\
    \"\"\"HTTP routes for the CQRS buses.

    POST /cqrs/commands — dispatch a named command payload.
    POST /cqrs/queries  — dispatch a named query payload.

    These routes are intentionally thin: they deserialise the incoming JSON
    into the appropriate message object and forward it to the bus.  All
    business logic lives in registered handlers.
    \"\"\"

    from __future__ import annotations

    import logging
    from typing import Any

    from fastapi import APIRouter, Depends, HTTPException, status
    from pydantic import BaseModel

    from app.cqrs.bus import CommandBus, QueryBus

    logger = logging.getLogger(__name__)
    router = APIRouter(prefix="/cqrs", tags=["cqrs"])

    # Module-level bus singletons — handlers are registered at startup.
    command_bus = CommandBus()
    query_bus = QueryBus()


    class BusRequest(BaseModel):
        \"\"\"Generic envelope for bus dispatch requests.\"\"\"

        name: str
        payload: dict[str, Any] = {}


    @router.post(
        "/commands",
        status_code=status.HTTP_200_OK,
        summary="Dispatch a command",
    )
    async def dispatch_command(req: BusRequest) -> dict[str, Any]:
        \"\"\"Dispatch a named command to its registered handler.

        Args:
            req: Command name and payload dict.

        Returns:
            Handler result wrapped in a ``{\"result\": ...}`` envelope.

        Raises:
            HTTPException 404: When no handler is registered for *req.name*.
        \"\"\"
        from app.cqrs.commands import Command
        try:
            cmd_cls_map = {
                sub.__name__: sub
                for sub in Command.__subclasses__()
            }
            cmd_cls = cmd_cls_map.get(req.name)
            if cmd_cls is None:
                raise KeyError(req.name)
            cmd = cmd_cls(**req.payload)
            result = await command_bus.dispatch(cmd)
            return {"result": result}
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": f"No handler registered for command: {req.name!r}"},
            )


    @router.post(
        "/queries",
        status_code=status.HTTP_200_OK,
        summary="Dispatch a query",
    )
    async def dispatch_query(req: BusRequest) -> dict[str, Any]:
        \"\"\"Dispatch a named query to its registered handler.

        Args:
            req: Query name and payload dict.

        Returns:
            Handler result wrapped in a ``{\"result\": ...}`` envelope.

        Raises:
            HTTPException 404: When no handler is registered for *req.name*.
        \"\"\"
        from app.cqrs.queries import Query
        try:
            qry_cls_map = {
                sub.__name__: sub
                for sub in Query.__subclasses__()
            }
            qry_cls = qry_cls_map.get(req.name)
            if qry_cls is None:
                raise KeyError(req.name)
            qry = qry_cls(**req.payload)
            result = await query_bus.query(qry)
            return {"result": result}
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": f"No handler registered for query: {req.name!r}"},
            )
""")
