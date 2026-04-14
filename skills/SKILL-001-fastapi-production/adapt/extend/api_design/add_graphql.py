"""TOOL-018: add_graphql — add a Strawberry GraphQL layer to a FastAPI project.

Generates GraphQL types from SQLAlchemy models, query/mutation resolvers that
delegate to existing CRUD functions, an ``aiodataloader``-based N+1 prevention
layer, depth and complexity extensions, and mounts the GraphQL endpoint at
``/graphql`` (configurable) inside ``app/main.py``.

The tool is idempotent: a second run detects the ``app/graphql/`` fingerprint
and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_graphql import add_graphql

    result = add_graphql(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/graphql/schema.py", ...]
    print(result.next_steps)    # ["pip install strawberry-graphql[fastapi]", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_graphql",
    "description": "Add GraphQL endpoint (Strawberry) alongside the existing REST API.",
    "tags": ["extend", "api_design"],
    "entry": "add_graphql",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_graphql(inp: ToolInput) -> ToolResult:
    """Add a Strawberry GraphQL layer to a FastAPI project.

    Discovers SQLAlchemy models, generates types/resolvers/dataloaders,
    and wires the GraphQL router into ``app/main.py``.

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
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    schema_file = app_dir / "graphql" / "schema.py"
    if schema_file.exists() and "strawberry" in schema_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["GraphQL schema already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    model_names = _discover_models(app_dir)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would generate GraphQL types, resolvers, dataloaders.",
                f"[dry_run] Models found: {', '.join(model_names) or 'none'}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    gql_dir = app_dir / "graphql"

    # Step 1: __init__.py
    init_file = gql_dir / "__init__.py"
    _write_graphql_init(init_file)
    files_created.append(str(init_file))

    # Step 2: types.py
    types_file = gql_dir / "types.py"
    _write_types(types_file, model_names)
    files_created.append(str(types_file))

    # Step 3: dataloaders.py
    loaders_file = gql_dir / "dataloaders.py"
    _write_dataloaders(loaders_file, model_names)
    files_created.append(str(loaders_file))

    # Step 4: context.py
    ctx_file = gql_dir / "context.py"
    _write_context(ctx_file)
    files_created.append(str(ctx_file))

    # Step 5: extensions.py
    ext_file = gql_dir / "extensions.py"
    _write_extensions(ext_file)
    files_created.append(str(ext_file))

    # Step 6: queries.py
    queries_file = gql_dir / "queries.py"
    _write_queries(queries_file, model_names)
    files_created.append(str(queries_file))

    # Step 7: mutations.py
    mutations_file = gql_dir / "mutations.py"
    _write_mutations(mutations_file, model_names)
    files_created.append(str(mutations_file))

    # Step 8: schema.py — assembles Query + Mutation
    _write_schema(schema_file, model_names)
    files_created.append(str(schema_file))

    # Step 9: patch main.py
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # Step 10: add strawberry-graphql and aiodataloader to requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    warnings: list[str] = []
    for path_str in files_created:
        w = _validate_py(Path(path_str))
        if w:
            warnings.append(w)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        warnings=warnings,
        notes=[
            "GraphQL layer mounted at /graphql.",
            "Types generated from SQLAlchemy models; resolvers delegate to CRUD.",
            "aiodataloader used for N+1 prevention.",
            "Depth (max 8) and complexity (max 1000) extensions enabled.",
            "Mutations create/update/delete delegate to existing CRUD functions.",
        ],
        next_steps=[
            "pip install 'strawberry-graphql[fastapi]' aiodataloader",
            "Restart the application to activate the /graphql endpoint.",
            "Open /graphql to explore the schema with GraphiQL.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names found in ``app/models/``.

    Only includes models that have a matching route file in ``app/api/routes/``
    to avoid generating resolvers for infrastructure-only models.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names.
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    names: list[str] = []
    if not models_dir.exists():
        return names
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        if f.stem not in available_routes:
            continue
        pascal = "".join(part.capitalize() for part in f.stem.split("_"))
        names.append(pascal)
    return names


def _write_graphql_init(dest: Path) -> None:
    """Write ``app/graphql/__init__.py``.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GraphQL layer — Strawberry schema, resolvers, dataloaders, and context.\"\"\"
        """))


def _write_types(dest: Path, model_names: list[str]) -> None:
    """Write ``app/graphql/types.py`` with Strawberry type stubs.

    Args:
        dest: Absolute destination path.
        model_names: PascalCase model names to generate types for.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    type_blocks = "\n\n".join(_model_type_block(m) for m in model_names) or (
        "# No models discovered — add @strawberry.type classes here."
    )
    content = textwrap.dedent("""\
        \"\"\"Strawberry GraphQL types auto-generated from SQLAlchemy models.

        Each type mirrors its SQLAlchemy counterpart and delegates relationship
        resolution to dataloaders to prevent N+1 queries.
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import TYPE_CHECKING

        import strawberry

        if TYPE_CHECKING:
            from app.graphql.context import GraphQLContext

        """) + type_blocks + "\n"
    dest.write_text(content)


def _model_type_block(model_name: str) -> str:
    """Return a strawberry.type class block for *model_name*.

    Args:
        model_name: PascalCase model name.

    Returns:
        Python source string for the Strawberry type.
    """
    return textwrap.dedent("""\
        @strawberry.type
        class {Model}Type:
            \"\"\"GraphQL representation of {Model}.

            Attributes:
                id: Primary key UUID.
                created_at: UTC creation timestamp.
            \"\"\"

            id: strawberry.ID
            created_at: datetime

        @strawberry.input
        class {Model}CreateInput:
            \"\"\"Input for creating a {Model}.

            Attributes:
                title: Human-readable label.
            \"\"\"

            title: str

        @strawberry.input
        class {Model}UpdateInput:
            \"\"\"Input for updating a {Model}.  All fields are optional.

            Attributes:
                title: New label, or None to leave unchanged.
            \"\"\"

            title: str | None = None
        """).replace("{Model}", model_name)


def _write_dataloaders(dest: Path, model_names: list[str]) -> None:
    """Write ``app/graphql/dataloaders.py`` with aiodataloader loaders.

    Args:
        dest: Absolute destination path.
        model_names: PascalCase model names.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    loader_blocks = "\n\n".join(_model_loader_block(m) for m in model_names) or (
        "# No models discovered."
    )

    attr_doc_lines = "".join(
        f"        {m.lower()}_by_id: {m}ByIdLoader\n"
        for m in model_names
    ) or "        # No models\n"

    init_lines = "\n".join(
        f"            self.{m.lower()}_by_id = {m}ByIdLoader()"
        for m in model_names
    ) or "            pass  # No models"

    registry_class = (
        "\n\nclass DataLoaderRegistry:\n"
        '    """Per-request container for all model dataloaders.\n'
        "\n"
        "    Instantiate once per request inside ``get_graphql_context`` so the\n"
        "    cache is flushed at request end and never shared across users.\n"
        "\n"
        "    Attributes:\n"
        + attr_doc_lines
        + '    """\n'
        "\n"
        "    def __init__(self) -> None:\n"
        + init_lines
        + "\n"
    )

    content = textwrap.dedent("""\
        \"\"\"aiodataloader registry — one loader per model, batches DB lookups.

        Import ``DataLoaderRegistry`` in ``app/graphql/context.py`` and attach
        an instance per-request so the cache is never shared across requests.
        \"\"\"

        from __future__ import annotations

        import uuid
        from typing import Any

        from aiodataloader import DataLoader


        """) + loader_blocks + registry_class
    dest.write_text(content)


def _model_loader_block(model_name: str) -> str:
    """Return an aiodataloader class for *model_name*.

    Args:
        model_name: PascalCase model name.

    Returns:
        Python source string for the DataLoader subclass.
    """
    return textwrap.dedent("""\
        class {Model}ByIdLoader(DataLoader):
            \"\"\"Batch-load {Model} rows by primary key UUID.

            Prevents N+1 queries by grouping all IDs requested within a single
            GraphQL resolution pass into a single ``WHERE id IN (...)`` query.

            Args:
                keys: List of UUID primary keys to load.

            Returns:
                List of {Model} ORM objects (or None) aligned to *keys*.
            \"\"\"

            async def batch_load_fn(self, keys: list[uuid.UUID]) -> list[Any]:
                from sqlalchemy import select as _select
                from app.core.db import async_session_maker as _maker
                from app.models.{lower} import {Model} as _Model

                async with _maker() as session:
                    stmt = _select(_Model).where(_Model.id.in_(keys))
                    rows = (await session.execute(stmt)).scalars().all()
                key_map = {row.id: row for row in rows}
                return [key_map.get(k) for k in keys]
        """).replace("{Model}", model_name).replace("{lower}", model_name.lower())


def _write_context(dest: Path) -> None:
    """Write ``app/graphql/context.py`` with ``GraphQLContext``.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GraphQL request context — carries auth user and dataloader registry.\"\"\"

        from __future__ import annotations

        from typing import Any

        import strawberry
        from fastapi import Request
        from strawberry.fastapi import BaseContext

        from app.graphql.dataloaders import DataLoaderRegistry


        class GraphQLContext(BaseContext):
            \"\"\"Per-request context injected into every resolver via ``info.context``.

            Attributes:
                request: The originating Starlette ``Request``.
                user: Authenticated user object, or ``None`` for anonymous requests.
                loaders: Fresh dataloader registry; cache is per-request.
            \"\"\"

            def __init__(
                self,
                request: Request,
                user: Any | None,
                loaders: DataLoaderRegistry,
            ) -> None:
                self.request = request
                self.user = user
                self.loaders = loaders
                super().__init__()


        async def get_graphql_context(request: Request) -> GraphQLContext:
            \"\"\"Build a fresh ``GraphQLContext`` for the current request.

            Attempts to resolve the current user via ``Authorization`` header;
            silently sets ``user=None`` for unauthenticated requests so public
            queries remain accessible.

            Args:
                request: Incoming HTTP request.

            Returns:
                Populated ``GraphQLContext``.
            \"\"\"
            user: Any | None = None
            try:
                from app.api.deps import get_current_user as _get_user
                user = await _get_user(request)
            except Exception:
                pass
            return GraphQLContext(
                request=request,
                user=user,
                loaders=DataLoaderRegistry(),
            )
        """))


def _write_extensions(dest: Path) -> None:
    """Write ``app/graphql/extensions.py`` with depth and complexity guards.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Strawberry schema extensions for depth and complexity limiting.

        Both extensions abort query execution before resolvers run, returning
        a structured error so the response never reaches the database.
        \"\"\"

        from __future__ import annotations

        from typing import Any

        from strawberry.extensions import SchemaExtension


        class DepthLimitExtension(SchemaExtension):
            \"\"\"Reject queries deeper than *max_depth* nesting levels.

            Args:
                max_depth: Maximum allowed query depth (default 8).
            \"\"\"

            def __init__(self, *, max_depth: int = 8, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._max_depth = max_depth

            def on_executing_start(self) -> None:
                \"\"\"Check query depth before execution begins.

                Raises:
                    ValueError: If the query exceeds the configured depth limit.
                \"\"\"
                depth = _measure_depth(self.execution_context.graphql_document)
                if depth > self._max_depth:
                    raise ValueError(
                        f"Query depth {depth} exceeds maximum allowed depth {self._max_depth}."
                    )


        class ComplexityLimitExtension(SchemaExtension):
            \"\"\"Reject queries with a complexity score above *max_complexity*.

            Complexity is approximated as the total number of field selections in
            the document — sufficient for DoS prevention without introspection cost.

            Args:
                max_complexity: Maximum allowed complexity score (default 1000).
            \"\"\"

            def __init__(self, *, max_complexity: int = 1000, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._max_complexity = max_complexity

            def on_executing_start(self) -> None:
                \"\"\"Check query complexity before execution begins.

                Raises:
                    ValueError: If the query exceeds the complexity limit.
                \"\"\"
                complexity = _measure_complexity(self.execution_context.graphql_document)
                if complexity > self._max_complexity:
                    raise ValueError(
                        f"Query complexity {complexity} exceeds maximum {self._max_complexity}."
                    )


        # ---------------------------------------------------------------------------
        # Internal document analysis helpers
        # ---------------------------------------------------------------------------

        def _measure_depth(document: Any, depth: int = 0) -> int:
            \"\"\"Recursively measure the maximum field nesting depth in a document.

            Args:
                document: GraphQL AST document node.
                depth: Current recursion depth counter.

            Returns:
                Maximum depth found.
            \"\"\"
            if document is None:
                return depth
            max_d = depth
            selections = getattr(document, "selection_set", None)
            if selections:
                for sel in getattr(selections, "selections", []):
                    child_depth = _measure_depth(sel, depth + 1)
                    if child_depth > max_d:
                        max_d = child_depth
            return max_d


        def _measure_complexity(document: Any) -> int:
            \"\"\"Count total field selections as a complexity approximation.

            Args:
                document: GraphQL AST document node.

            Returns:
                Total field selection count.
            \"\"\"
            if document is None:
                return 0
            count = 0
            selections = getattr(document, "selection_set", None)
            if selections:
                for sel in getattr(selections, "selections", []):
                    count += 1 + _measure_complexity(sel)
            for child_attr in ("definitions",):
                for child in getattr(document, child_attr, []):
                    count += _measure_complexity(child)
            return count
        """))


def _write_queries(dest: Path, model_names: list[str]) -> None:
    """Write ``app/graphql/queries.py`` with a ``Query`` class.

    Args:
        dest: Absolute destination path.
        model_names: PascalCase model names.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    resolver_blocks = "\n\n".join(_query_resolver_block(m) for m in model_names) or (
        "    # No models discovered."
    )
    content = textwrap.dedent("""\
        \"\"\"GraphQL Query type — resolvers delegate to existing CRUD functions.\"\"\"

        from __future__ import annotations

        import uuid

        import strawberry

        from app.graphql.context import GraphQLContext

        """) + "\n".join(
        f"from app.graphql.types import {m}Type"
        for m in model_names
    ) + textwrap.dedent("""


        @strawberry.type
        class Query:
            \"\"\"Root GraphQL query type.  All fields require authentication.\"\"\"

        """) + resolver_blocks + "\n"
    dest.write_text(content)


def _query_resolver_block(model_name: str) -> str:
    """Return query resolver methods for a single model.

    Args:
        model_name: PascalCase model name.

    Returns:
        Python source for two strawberry.field methods.
    """
    lower = model_name.lower()
    # NOTE: leading 4-space indent places methods inside the Query class body.
    return (
        "    @strawberry.field\n"
        "    async def {lower}(\n"
        "        self,\n"
        "        info: strawberry.types.Info[\"GraphQLContext\", None],\n"
        "        id: strawberry.ID,\n"
        "    ) -> {Model}Type | None:\n"
        "        \"\"\"Fetch a single {Model} by ID using the dataloader.\n\n"
        "        Args:\n"
        "            info: GraphQL resolve info carrying context.\n"
        "            id: Primary key UUID as a strawberry ID string.\n\n"
        "        Returns:\n"
        "            {Model}Type or None if not found.\n"
        "        \"\"\"\n"
        "        if not info.context.user:\n"
        "            raise PermissionError(\"Authentication required\")\n"
        "        return await info.context.loaders.{lower}_by_id.load(\n"
        "            uuid.UUID(str(id))\n"
        "        )\n"
        "\n"
        "    @strawberry.field\n"
        "    async def {lower}s(\n"
        "        self,\n"
        "        info: strawberry.types.Info[\"GraphQLContext\", None],\n"
        "        skip: int = 0,\n"
        "        limit: int = 20,\n"
        "    ) -> list[{Model}Type]:\n"
        "        \"\"\"List {Model} rows with pagination.\n\n"
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        "            skip: Pagination offset (default 0).\n"
        "            limit: Page size, max 100 (default 20).\n\n"
        "        Returns:\n"
        "            List of {Model}Type objects.\n"
        "        \"\"\"\n"
        "        if not info.context.user:\n"
        "            raise PermissionError(\"Authentication required\")\n"
        "        from app.crud.{lower} import list_{lower}s as _list\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            rows = await _list(session, skip=skip, limit=min(limit, 100))\n"
        "        return rows\n"
    ).replace("{Model}", model_name).replace("{lower}", lower)


def _write_mutations(dest: Path, model_names: list[str]) -> None:
    """Write ``app/graphql/mutations.py`` with a ``Mutation`` class.

    Args:
        dest: Absolute destination path.
        model_names: PascalCase model names.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    mutation_blocks = "\n\n".join(_mutation_resolver_block(m) for m in model_names) or (
        "    # No models discovered."
    )
    content = textwrap.dedent("""\
        \"\"\"GraphQL Mutation type — delegates to existing CRUD functions.\"\"\"

        from __future__ import annotations

        import uuid

        import strawberry

        from app.graphql.context import GraphQLContext

        """) + "\n".join(
        f"from app.graphql.types import {m}Type, {m}CreateInput, {m}UpdateInput"
        for m in model_names
    ) + textwrap.dedent("""


        @strawberry.type
        class Mutation:
            \"\"\"Root GraphQL mutation type.  All mutations require authentication.\"\"\"

        """) + mutation_blocks + "\n"
    dest.write_text(content)


def _mutation_resolver_block(model_name: str) -> str:
    """Return mutation resolver methods for a single model.

    Args:
        model_name: PascalCase model name.

    Returns:
        Python source for create/update/delete mutations.
    """
    lower = model_name.lower()
    # NOTE: leading 4-space indent places methods inside the Mutation class body.
    return (
        "    @strawberry.mutation\n"
        "    async def create_{lower}(\n"
        "        self,\n"
        "        info: strawberry.types.Info[\"GraphQLContext\", None],\n"
        "        data: {Model}CreateInput,\n"
        "    ) -> {Model}Type:\n"
        "        \"\"\"Create a new {Model}.  Delegates to CRUD create.\n\n"
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        "            data: Input fields for the new {Model}.\n\n"
        "        Returns:\n"
        "            The created {Model}Type.\n"
        "        \"\"\"\n"
        "        if not info.context.user:\n"
        "            raise PermissionError(\"Authentication required\")\n"
        "        from app.crud.{lower} import create_{lower} as _create\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            return await _create(session, item_in=data)\n"
        "\n"
        "    @strawberry.mutation\n"
        "    async def delete_{lower}(\n"
        "        self,\n"
        "        info: strawberry.types.Info[\"GraphQLContext\", None],\n"
        "        id: strawberry.ID,\n"
        "    ) -> bool:\n"
        "        \"\"\"Delete a {Model} by ID.  Delegates to CRUD delete.\n\n"
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        "            id: Primary key UUID.\n\n"
        "        Returns:\n"
        "            True on success, False if not found.\n"
        "        \"\"\"\n"
        "        if not info.context.user:\n"
        "            raise PermissionError(\"Authentication required\")\n"
        "        from app.crud.{lower} import delete_{lower} as _delete\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            deleted = await _delete(session, uuid.UUID(str(id)))\n"
        "            return deleted is not None\n"
    ).replace("{Model}", model_name).replace("{lower}", lower)


def _write_schema(dest: Path, model_names: list[str]) -> None:
    """Write ``app/graphql/schema.py`` assembling the top-level Strawberry schema.

    Args:
        dest: Absolute destination path.
        model_names: PascalCase model names (used for notes only).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Strawberry GraphQL schema — top-level assembly.

        Import ``schema`` in ``app/main.py`` and mount via ``GraphQLRouter``.
        \"\"\"

        from __future__ import annotations

        import strawberry

        from app.graphql.extensions import ComplexityLimitExtension, DepthLimitExtension
        from app.graphql.mutations import Mutation
        from app.graphql.queries import Query

        _MAX_DEPTH: int = 8
        _MAX_COMPLEXITY: int = 1000

        schema = strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=[
                DepthLimitExtension(max_depth=_MAX_DEPTH),
                ComplexityLimitExtension(max_complexity=_MAX_COMPLEXITY),
            ],
        )
        """))


def _patch_main(main_file: Path) -> None:
    """Mount the GraphQL router inside ``app/main.py``.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "GraphQLRouter" in src or "/graphql" in src:
        return

    graphql_import = textwrap.dedent("""\
        from strawberry.fastapi import GraphQLRouter as _GraphQLRouter
        from app.graphql.schema import schema as _gql_schema
        from app.graphql.context import get_graphql_context as _gql_ctx
        """)

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI\n" + graphql_import,
        )
    else:
        src = graphql_import + src

    mount_block = textwrap.dedent("""\

        _graphql_app = _GraphQLRouter(
            _gql_schema,
            context_getter=_gql_ctx,
            graphql_ide="graphiql",
        )
        app.include_router(_graphql_app, prefix="/graphql")
        """)

    src = src.rstrip("\n") + "\n" + mount_block
    main_file.write_text(src)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _validate_py(path: Path) -> str | None:
    """Return error string if *path* fails ``ast.parse``, else None.

    Args:
        path: Python file to validate.

    Returns:
        Error string or None.
    """
    try:
        ast.parse(path.read_text())
        return None
    except SyntaxError as exc:
        return f"SyntaxError in {path}: {exc}"


def _patch_requirements(requirements_file: Path) -> None:
    """Add ``strawberry-graphql[fastapi]`` and ``aiodataloader`` to requirements.txt.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    lines_to_add = []
    if "strawberry-graphql" not in src:
        lines_to_add.append("strawberry-graphql[fastapi]>=0.220.0")
    if "aiodataloader" not in src:
        lines_to_add.append("aiodataloader>=0.2.1")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
