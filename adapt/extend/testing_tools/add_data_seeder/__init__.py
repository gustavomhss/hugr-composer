"""TOOL-105: add_data_seeder — smart test data seeder respecting FK relationships.

Generates a DataSeeder that reads SQLAlchemy models, uses smart generators,
performs topological sort of models by FK with DependencyGraph, and exposes
a POST /dev/seed endpoint (dev only) and a scripts/seed.py CLI.

The tool is idempotent: a second run detects the ``DataSeeder``
fingerprint and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_testing_add_data_seeder",
    "description": "Add a smart test data seeder that respects FK relationships via topological sort.",
    "tags": ["extend", "testing_tools"],
    "entry": "add_data_seeder",
}


def add_data_seeder(inp: ToolInput) -> ToolResult:
    """Add a smart data seeder with FK-aware topological sort and dev-only endpoint.

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
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.BASE_MODEL,
        Prereq.ROUTES_INIT,
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
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    seeder_init = app_dir / "seeder" / "__init__.py"
    if seeder_init.exists() and "DataSeeder" in seeder_init.read_text():
        return ToolResult(
            status="no_op",
            notes=["DataSeeder already present — data seeder is already installed, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/seeder/ (DataSeeder, generators, DependencyGraph),",
                "         POST /dev/seed?count=N route (dev/staging only),",
                "         scripts/seed.py CLI.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    seeder_dir = app_dir / "seeder"
    seeder_dir.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "seeder_init.py.tmpl", dest=seeder_init, substitutions={})
    files_created.append(str(seeder_init))

    render_to(
        _HERE, "seeder_generators.py.tmpl", dest=seeder_dir / "generators.py", substitutions={}
    )
    files_created.append(str(seeder_dir / "generators.py"))

    render_to(_HERE, "seeder_graph.py.tmpl", dest=seeder_dir / "graph.py", substitutions={})
    files_created.append(str(seeder_dir / "graph.py"))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    seeder_route = routes_dir / "seeder.py"
    render_to(_HERE, "seeder_route.py.tmpl", dest=seeder_route, substitutions={})
    files_created.append(str(seeder_route))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    seed_script = scripts_dir / "seed.py"
    render_to(_HERE, "seed_cli.py.tmpl", dest=seed_script, substitutions={})
    files_created.append(str(seed_script))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_ms(start),
                )

    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_data_seeder_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_data_seeder_emitted.py.tmpl", dest=emitted, substitutions={})
        files_created.append(str(emitted))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Data seeder added: DataSeeder, smart generators, DependencyGraph.",
            "Topological sort ensures FKs are seeded before referencing models.",
            "POST /dev/seed?count=100 route enabled only when SEEDER_ENABLED=true.",
            "scripts/seed.py CLI: python scripts/seed.py --count 100",
        ],
        next_steps=[
            "Set SEEDER_ENABLED=true in your dev .env (default is false in production)",
            "Seed data: python scripts/seed.py --count 50",
            "Or via HTTP: POST /dev/seed?count=50 (dev only)",
            "SEEDER_DEFAULT_COUNT controls the default count (default: 10)",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_routes_init(routes_init: Path) -> None:
    content = routes_init.read_text()
    import_line = "from app.api.routes.seeder import router as seeder_router"
    include_line = "api_router.include_router(seeder_router)"
    if import_line in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n{import_line}\n{include_line}\n"
    routes_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("SEEDER_ENABLED", "SEEDER_ENABLED: bool = False"),
            ("SEEDER_DEFAULT_COUNT", "SEEDER_DEFAULT_COUNT: int = 10"),
        ],
    )


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
