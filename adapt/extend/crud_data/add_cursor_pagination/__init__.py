"""TOOL-002: add_cursor_pagination — cursor pagination via shared _base phases.

Replaces offset ``skip/limit`` with stable cursor pagination on every discovered
model. Phase-1/3/4 primitives from :mod:`adapt._base`; emitted code in
``templates/*.py.tmpl``. Phase-5 emits ``tests/test_cursor_pagination.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import (
    INFRA_SKIP,
    DiscoveredModel,
    ProjectProbe,
    discover_models,
    patch_append_class_body_after_field,
    patch_append_module_block,
    patch_append_router_endpoint,
    probe_project,
    render,
    render_to,
)
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_cursor_pagination",
    "description": (
        "Replace offset pagination with cursor-based pagination across all list endpoints."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_cursor_pagination",
    "imports_primitives": [],
    "imports_adapters": [],

}

_NOTES_SUCCESS_TAIL = [
    "Response schema backward-compatible: data/count unchanged; next_cursor/has_more added with safe defaults.",
    "Invalid cursor returns HTTP 400. Emitted test: tests/test_cursor_pagination.py",
]
_NEXT_STEPS = [
    "alembic upgrade head",
    "Update API clients to use cursor/page_size instead of skip/limit.",
    "PYTHONPATH=. pytest tests/test_cursor_pagination.py -q",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created. Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_cursor_pagination(inp: ToolInput) -> ToolResult:
    """Add cursor-based pagination to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    probe = probe_project(project)
    models = discover_models(probe, skip=INFRA_SKIP, require_route=True)
    if not models:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    # BUG #1 fix: full-state idempotency — only no_op when core + every CRUD +
    # emitted test are ALL present. Partial state falls through.
    if _all_models_fully_patched(probe, models, project):
        return ToolResult(
            status="no_op",
            notes=[
                "get_multi_cursor + cursor core + emitted test all present — cursor pagination already enabled."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        names = [m.class_name for m in models]
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add cursor pagination for models: {', '.join(names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    _write_core(probe, files_created)
    for m in models:
        _patch_model(probe, m, files_modified)
    if probe.versions_dir and probe.versions_dir.exists():
        _write_migrations(probe, models, files_created)
    _emit_project_test(project, models, files_created)

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

    names = [m.class_name for m in models]
    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[f"Cursor pagination enabled for: {', '.join(names)}", *_NOTES_SUCCESS_TAIL],
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _write_core(probe: ProjectProbe, created: list[str]) -> None:
    cursor_py = probe.app_dir / "core" / "cursor.py"
    if not cursor_py.exists():
        render_to(_HERE, "cursor.py.tmpl", dest=cursor_py, substitutions={})
        created.append(str(cursor_py))
    paginator_py = probe.app_dir / "core" / "cursor_paginator.py"
    if not paginator_py.exists():
        render_to(_HERE, "cursor_paginator.py.tmpl", dest=paginator_py, substitutions={})
        created.append(str(paginator_py))


def _patch_model(probe: ProjectProbe, m: DiscoveredModel, modified: list[str]) -> None:
    plural_class = f"{m.class_name}sPublic"
    if m.has_crud:
        crud_file = probe.crud_dir / f"{m.stem}.py"
        if patch_append_module_block(
            crud_file,
            block=render(_HERE, "crud_addition.py.tmpl", {"model_name": m.class_name}),
            fingerprint="get_multi_cursor",
        ):
            modified.append(str(crud_file))
    if m.has_schema:
        schema_file = probe.schemas_dir / f"{m.stem}.py"
        if patch_append_class_body_after_field(
            schema_file,
            class_name=plural_class,
            after_field="count",
            new_fields=["next_cursor: str | None = None", "has_more: bool = False"],
        ):
            modified.append(str(schema_file))
    if m.has_route:
        route_file = probe.routes_dir / f"{m.stem}.py"
        # BUG #2 fix: schema lookup uses the actual file stem, not
        # class_name.lower() (which misses multiword files like vaccinelot.py).
        schema_lookup = probe.schemas_dir / f"{m.stem}.py"
        if not _route_has_plural_class(probe, route_file, schema_lookup, plural_class):
            return
        if patch_append_router_endpoint(
            route_file,
            endpoint_block=render(
                _HERE,
                "route_addition.py.tmpl",
                {"lower": m.stem, "model_name": m.class_name, "PublicList": plural_class},
            ),
            fingerprint=f"list_{m.stem}s_cursor",
        ):
            modified.append(str(route_file))


def _write_migrations(
    probe: ProjectProbe, models: list[DiscoveredModel], created: list[str]
) -> None:
    assert probe.versions_dir is not None
    down_rev = find_migration_head(probe.versions_dir) or "0001_initial"
    for m in models:
        table = m.class_name.lower() + "s"
        rev_id = f"cursor_idx_{table}"
        mig_file = probe.versions_dir / f"{rev_id}.py"
        if mig_file.exists():
            continue
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=mig_file,
            substitutions={"table": table, "rev_id": rev_id, "down_rev": down_rev},
        )
        created.append(str(mig_file))


def _emit_project_test(project: Path, models: list[DiscoveredModel], created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_cursor_pagination.py"
    if emitted.exists():
        return
    primary = models[0]
    render_to(
        _HERE,
        "test_cursor_pagination.py.tmpl",
        dest=emitted,
        substitutions={
            "model_name": primary.class_name,
            "stem": primary.stem,
            "table": primary.class_name.lower() + "s",
        },
    )
    created.append(str(emitted))




def _all_models_fully_patched(
    probe: ProjectProbe, models: list[DiscoveredModel], project: Path
) -> bool:
    """True when core + every CRUD + emitted test are all present (BUG #1 fix:
    legacy only checked CRUD; stubbed cursor.py with unpatched CRUD would no_op)."""
    if not (probe.app_dir / "core" / "cursor.py").exists():
        return False
    if not (project / "tests" / "test_cursor_pagination.py").exists():
        return False
    for m in models:
        crud_file = probe.crud_dir / f"{m.stem}.py"
        if not crud_file.exists() or "get_multi_cursor" not in probe.read(crud_file):
            return False
    return True


def _route_has_plural_class(
    probe: ProjectProbe, route_file: Path, schema_file: Path, plural_class: str
) -> bool:
    if not route_file.exists():
        return False
    if plural_class in probe.read(route_file):
        return True
    return schema_file.exists() and plural_class in probe.read(schema_file)
