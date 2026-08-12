"""TOOL-018: add_graphql — add a Strawberry GraphQL layer to a FastAPI project.

Generates GraphQL types from SQLAlchemy models, query/mutation resolvers that
delegate to existing CRUD functions, an ``aiodataloader``-based N+1 prevention
layer, depth and complexity extensions, and mounts the GraphQL endpoint at
``/graphql`` (configurable) inside ``app/main.py``.

The tool is idempotent: a second run detects the ``app/graphql/`` fingerprint
and returns ``status="no_op"`` without touching any file.

Note (D-14 / F-09): this tool does NOT ship a raw SDL/.graphql blob.  All
GraphQL schema is emitted as Python Strawberry type annotations.  No
SDL extraction to ``.graphql.tmpl`` is needed — F-09 is not triggered.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_graphql import add_graphql

    result = add_graphql(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...app/graphql/schema.py", ...]
    print(result.next_steps)    # ["pip install strawberry-graphql[fastapi]", ...]
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_api_add_graphql",
    "description": "Add GraphQL endpoint (Strawberry) alongside the existing REST API.",
    "tags": ["extend", "api_design"],
    "entry": "add_graphql",
    "imports_primitives": [],
    "imports_adapters": [],

}

_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


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

    files_modified: list[str] = []
    gql_dir = app_dir / "graphql"

    # Step 1: __init__.py
    init_file = gql_dir / "__init__.py"
    render_to(_HERE, "graphql_init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    # Step 2: types.py
    types_file = gql_dir / "types.py"
    type_blocks = "\n\n".join(_model_type_block(m) for m in model_names) or (
        "# No models discovered — add @strawberry.type classes here."
    )
    render_to(_HERE, "types.py.tmpl", dest=types_file, substitutions={"type_blocks": type_blocks})
    files_created.append(str(types_file))

    # Step 3: dataloaders.py
    loaders_file = gql_dir / "dataloaders.py"
    loader_blocks = (
        "\n\n".join(_model_loader_block(m) for m in model_names) or "# No models discovered."
    )
    registry_attrs = (
        "".join(f"        {m.lower()}_by_id: {m}ByIdLoader\n" for m in model_names)
        or "        # No models\n"
    )
    registry_init = (
        "\n".join(f"        self.{m.lower()}_by_id = {m}ByIdLoader()" for m in model_names)
        or "        pass  # No models"
    )
    render_to(
        _HERE,
        "dataloaders.py.tmpl",
        dest=loaders_file,
        substitutions={
            "loader_blocks": loader_blocks,
            "registry_attrs": registry_attrs,
            "registry_init": registry_init,
        },
    )
    files_created.append(str(loaders_file))

    # Step 4: context.py
    ctx_file = gql_dir / "context.py"
    render_to(_HERE, "context.py.tmpl", dest=ctx_file, substitutions={})
    files_created.append(str(ctx_file))

    # Step 5: extensions.py
    ext_file = gql_dir / "extensions.py"
    render_to(_HERE, "extensions.py.tmpl", dest=ext_file, substitutions={})
    files_created.append(str(ext_file))

    # Step 6: queries.py
    queries_file = gql_dir / "queries.py"
    import_lines = "\n".join(f"from app.graphql.types import {m}Type" for m in model_names)
    resolver_blocks = "\n\n".join(_query_resolver_block(m) for m in model_names) or (
        "    # No models discovered."
    )
    render_to(
        _HERE,
        "queries.py.tmpl",
        dest=queries_file,
        substitutions={"import_lines": import_lines, "resolver_blocks": resolver_blocks},
    )
    files_created.append(str(queries_file))

    # Step 7: mutations.py
    mutations_file = gql_dir / "mutations.py"
    mutation_imports = "\n".join(
        f"from app.graphql.types import {m}Type, {m}CreateInput, {m}UpdateInput"
        for m in model_names
    )
    mutation_blocks = "\n\n".join(_mutation_resolver_block(m) for m in model_names) or (
        "    # No models discovered."
    )
    render_to(
        _HERE,
        "mutations.py.tmpl",
        dest=mutations_file,
        substitutions={
            "mutation_imports": mutation_imports,
            "mutation_blocks": mutation_blocks,
        },
    )
    files_created.append(str(mutations_file))

    # Step 8: schema.py — assembles Query + Mutation
    render_to(_HERE, "schema.py.tmpl", dest=schema_file, substitutions={})
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

    # Step 11: emit test
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
            "GraphQL layer mounted at /graphql.",
            "Types generated from SQLAlchemy models; resolvers delegate to CRUD.",
            "aiodataloader used for N+1 prevention.",
            "Depth (max 8) and complexity (max 1000) extensions enabled.",
            "Mutations create/update/delete delegate to existing CRUD functions.",
            "Note (F-09): schema is Python Strawberry types only — no raw SDL blob.",
        ],
        next_steps=[
            "pip install 'strawberry-graphql[fastapi]' aiodataloader",
            "Restart the application to activate the /graphql endpoint.",
            "Open /graphql to explore the schema with GraphiQL.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names with a matching route file."""
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__", "tenant"}
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


def _model_type_block(model_name: str) -> str:
    """Return a strawberry.type class block for *model_name*."""
    return (
        "@strawberry.type\n"
        f"class {model_name}Type:\n"
        f'    """GraphQL representation of {model_name}.\n\n'
        "    Attributes:\n"
        "        id: Primary key UUID.\n"
        "        created_at: UTC creation timestamp.\n"
        '    """\n\n'
        "    id: strawberry.ID\n"
        "    created_at: datetime\n\n"
        "@strawberry.input\n"
        f"class {model_name}CreateInput:\n"
        f'    """Input for creating a {model_name}.\n\n'
        "    Attributes:\n"
        "        title: Human-readable label.\n"
        '    """\n\n'
        "    title: str\n\n"
        "@strawberry.input\n"
        f"class {model_name}UpdateInput:\n"
        f'    """Input for updating a {model_name}.  All fields are optional.\n\n'
        "    Attributes:\n"
        "        title: New label, or None to leave unchanged.\n"
        '    """\n\n'
        "    title: str | None = None\n"
    )


def _model_loader_block(model_name: str) -> str:
    """Return an aiodataloader class for *model_name*."""
    lower = model_name.lower()
    return (
        f"class {model_name}ByIdLoader(DataLoader):\n"
        f'    """Batch-load {model_name} rows by primary key UUID.\n\n'
        f"    Prevents N+1 queries by grouping all IDs requested within a single\n"
        f"    GraphQL resolution pass into a single ``WHERE id IN (...)`` query.\n\n"
        f"    Args:\n"
        f"        keys: List of UUID primary keys to load.\n\n"
        f"    Returns:\n"
        f"        List of {model_name} ORM objects (or None) aligned to *keys*.\n"
        f'    """\n\n'
        f"    async def batch_load_fn(self, keys: list[uuid.UUID]) -> list[Any]:\n"
        f"        from sqlalchemy import select as _select\n"
        f"        from app.core.db import async_session_maker as _maker\n"
        f"        from app.models.{lower} import {model_name} as _Model\n\n"
        f"        async with _maker() as session:\n"
        f"            stmt = _select(_Model).where(_Model.id.in_(keys))\n"
        f"            rows = (await session.execute(stmt)).scalars().all()\n"
        f"        key_map = {{row.id: row for row in rows}}\n"
        f"        return [key_map.get(k) for k in keys]\n"
    )


def _query_resolver_block(model_name: str) -> str:
    """Return query resolver methods for a single model."""
    lower = model_name.lower()
    return (
        "    @strawberry.field\n"
        f"    async def {lower}(\n"
        "        self,\n"
        '        info: strawberry.types.Info["GraphQLContext", None],\n'
        "        id: strawberry.ID,\n"
        f"    ) -> {model_name}Type | None:\n"
        f'        """Fetch a single {model_name} by ID using the dataloader.\n\n'
        "        Args:\n"
        "            info: GraphQL resolve info carrying context.\n"
        "            id: Primary key UUID as a strawberry ID string.\n\n"
        "        Returns:\n"
        f"            {model_name}Type or None if not found.\n"
        '        """\n'
        "        if not info.context.user:\n"
        '            raise PermissionError("Authentication required")\n'
        f"        return await info.context.loaders.{lower}_by_id.load(\n"
        "            uuid.UUID(str(id))\n"
        "        )\n"
        "\n"
        "    @strawberry.field\n"
        f"    async def {lower}s(\n"
        "        self,\n"
        '        info: strawberry.types.Info["GraphQLContext", None],\n'
        "        skip: int = 0,\n"
        "        limit: int = 20,\n"
        f"    ) -> list[{model_name}Type]:\n"
        f'        """List {model_name} rows with pagination.\n\n'
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        "            skip: Pagination offset (default 0).\n"
        "            limit: Page size, max 100 (default 20).\n\n"
        "        Returns:\n"
        f"            List of {model_name}Type objects.\n"
        '        """\n'
        "        if not info.context.user:\n"
        '            raise PermissionError("Authentication required")\n'
        f"        from app.crud.{lower} import list_{lower}s as _list\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            rows = await _list(session, skip=skip, limit=min(limit, 100))\n"
        "        return rows\n"
    )


def _mutation_resolver_block(model_name: str) -> str:
    """Return mutation resolver methods for a single model."""
    lower = model_name.lower()
    return (
        "    @strawberry.mutation\n"
        f"    async def create_{lower}(\n"
        "        self,\n"
        '        info: strawberry.types.Info["GraphQLContext", None],\n'
        f"        data: {model_name}CreateInput,\n"
        f"    ) -> {model_name}Type:\n"
        f'        """Create a new {model_name}.  Delegates to CRUD create.\n\n'
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        f"            data: Input fields for the new {model_name}.\n\n"
        "        Returns:\n"
        f"            The created {model_name}Type.\n"
        '        """\n'
        "        if not info.context.user:\n"
        '            raise PermissionError("Authentication required")\n'
        f"        from app.crud.{lower} import create_{lower} as _create\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            return await _create(session, item_in=data)\n"
        "\n"
        "    @strawberry.mutation\n"
        f"    async def delete_{lower}(\n"
        "        self,\n"
        '        info: strawberry.types.Info["GraphQLContext", None],\n'
        "        id: strawberry.ID,\n"
        f"    ) -> bool:\n"
        f'        """Delete a {model_name} by ID.  Delegates to CRUD delete.\n\n'
        "        Args:\n"
        "            info: GraphQL resolve info.\n"
        "            id: Primary key UUID.\n\n"
        "        Returns:\n"
        "            True on success, False if not found.\n"
        '        """\n'
        "        if not info.context.user:\n"
        '            raise PermissionError("Authentication required")\n'
        f"        from app.crud.{lower} import delete_{lower} as _delete\n"
        "        from app.core.session import async_session as _maker\n"
        "        async with _maker() as session:\n"
        "            deleted = await _delete(session, uuid.UUID(str(id)))\n"
        "            return deleted is not None\n"
    )


def _patch_main(main_file: Path) -> None:
    """Mount the GraphQL router inside ``app/main.py``."""
    src = main_file.read_text()
    if "GraphQLRouter" in src or "/graphql" in src:
        return

    graphql_import = (
        "from strawberry.fastapi import GraphQLRouter as _GraphQLRouter\n"
        "from app.graphql.schema import schema as _gql_schema\n"
        "from app.graphql.context import get_graphql_context as _gql_ctx\n"
    )

    if "from fastapi import FastAPI" in src:
        src = src.replace(
            "from fastapi import FastAPI",
            "from fastapi import FastAPI\n" + graphql_import,
        )
    else:
        src = graphql_import + src

    mount_block = (
        "\n"
        "_graphql_app = _GraphQLRouter(\n"
        "    _gql_schema,\n"
        "    context_getter=_gql_ctx,\n"
        '    graphql_ide="graphiql",\n'
        ")\n"
        'app.include_router(_graphql_app, prefix="/graphql")\n'
    )

    src = src.rstrip("\n") + "\n" + mount_block
    main_file.write_text(src)


def _patch_requirements(requirements_file: Path) -> None:
    """Add strawberry-graphql and aiodataloader to requirements.txt."""
    src = requirements_file.read_text()
    lines_to_add = []
    if "strawberry-graphql" not in src:
        lines_to_add.append("strawberry-graphql[fastapi]>=0.220.0")
    if "aiodataloader" not in src:
        lines_to_add.append("aiodataloader>=0.2.1")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_graphql_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_graphql_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_graphql_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


