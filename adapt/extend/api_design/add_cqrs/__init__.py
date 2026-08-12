"""TOOL-080: add_cqrs — add Command/Query Responsibility Segregation with read replicas.

Writes a production-grade CQRS layer: a ``CommandBus`` (dispatches Commands) and a
``QueryBus`` (dispatches Queries), a ``ReadReplicaSession`` dependency that routes
read queries to ``settings.DATABASE_READ_URL`` (falls back to the primary connection
when not set), example Command and Query objects, HTTP routes for both buses, and
every required settings field.

The tool is idempotent: a second run detects ``CommandBus`` in
``app/cqrs/__init__.py`` and returns ``status="no_op"``.

Warnings:
    - CQRS does NOT enforce physical read/write model separation at the ORM level.
      CommandBus and QueryBus are logical separators. Physical model separation
      requires custom schema migration work outside this tool.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.api_design.add_cqrs import add_cqrs

    result = add_cqrs(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/cqrs/__init__.py", …]
    print(result.next_steps)    # ["Set DATABASE_READ_URL in .env", …]
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
    "name": "fastapi_api_add_cqrs",
    "description": (
        "Add a production-grade CQRS layer with CommandBus, QueryBus, "
        "read-replica session routing, and HTTP routes for both buses."
    ),
    "tags": ["extend", "api_design"],
    "entry": "add_cqrs",
    "imports_primitives": [],
    "imports_adapters": [],

}


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

    # Idempotency guard
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
    pkg_dir = app_dir / "cqrs"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    for name, tmpl in [
        ("__init__.py", "cqrs_init.py.tmpl"),
        ("bus.py", "bus.py.tmpl"),
        ("commands.py", "commands.py.tmpl"),
        ("queries.py", "queries.py.tmpl"),
        ("read_replica.py", "read_replica.py.tmpl"),
    ]:
        dest = pkg_dir / name
        render_to(_HERE, tmpl, dest=dest, substitutions={})
        files_created.append(str(dest))

    # Step 2 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes_file = routes_dir / "cqrs.py"
    render_to(_HERE, "cqrs_routes.py.tmpl", dest=routes_file, substitutions={})
    files_created.append(str(routes_file))

    # Step 3 — patch config.py
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        patch_settings_fields(
            config_file,
            fields=[
                ("DATABASE_READ_URL", 'DATABASE_READ_URL: str = ""'),
                ("CQRS_ENABLED", "CQRS_ENABLED: bool = True"),
            ],
        )
        files_modified.append(str(config_file))

    # Step 4 — register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 5 — emit test
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
            "CQRS layer added: CommandBus (dispatch), QueryBus (query).",
            "ReadReplicaSession routes read queries to DATABASE_READ_URL "
            "(falls back to primary DATABASE_URL when not set).",
            "POST /cqrs/commands — dispatch a registered command by name.",
            "POST /cqrs/queries  — dispatch a registered query by name.",
            "CQRS_ENABLED=false disables the HTTP surface; buses remain usable in code.",
            "WARNING: CQRS does NOT separate read/write ORM models — logical separation only.",
        ],
        next_steps=[
            "Set DATABASE_READ_URL in .env to point to your Postgres read replica.",
            "Register command handlers: bus.register('MyCommand', my_handler)",
            "Register query handlers: query_bus.register('MyQuery', my_handler)",
            "Restart the FastAPI app so /cqrs/* routes are loaded.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_routes_init(routes_init: Path) -> None:
    """Register the cqrs router in ``app/routes/__init__.py``."""
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


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_cqrs_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_cqrs_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_cqrs_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


