"""TOOL-004: add_search — full-text search via externalized templates.

Discovers domain models with text fields, emits CRUD search() + autocomplete()
helpers using websearch_to_tsquery + bound parameters (F-08: NO SQL string
concatenation of user input), patches schemas + routes, and writes an Alembic
GIN-index migration per table. All emitted code lives in templates/*.py.tmpl.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_search",
    "description": "Add full-text search endpoints backed by PostgreSQL tsvector or Elasticsearch.",
    "tags": ["extend", "crud_data"],
    "entry": "add_search",
    "imports_primitives": [],
    "imports_adapters": [],

}

_SKIP_MODELS = {"base", "user", "mixins", "__init__", "tenant"}


def add_search(inp: ToolInput) -> ToolResult:
    """Add PostgreSQL full-text search capability to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
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

    app_dir = project / "app"
    if _search_already_installed(app_dir):
        return ToolResult(
            status="no_op",
            notes=[
                "search() function already present — full-text search already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )
    model_map = _discover_models_with_fields(app_dir)
    if not model_map:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models with text fields found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    pascal_names = [pascal for (_stem, pascal) in model_map]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add full-text search for models: {', '.join(pascal_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    for (stem, model_name), text_fields in model_map.items():
        crud_file = app_dir / "crud" / f"{stem}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name, text_fields)
            files_modified.append(str(crud_file))

        schema_file = app_dir / "schemas" / f"{stem}.py"
        if schema_file.exists():
            _patch_schema(schema_file, model_name)
            files_modified.append(str(schema_file))

        route_file = app_dir / "api" / "routes" / f"{stem}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

        versions_dir = project / "alembic" / "versions"
        if versions_dir.exists():
            files_created.append(str(_write_migration(versions_dir, model_name, text_fields)))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Full-text search enabled for: {', '.join(pascal_names)}",
            "GIN index created via CONCURRENTLY (migration must run outside a transaction).",
            "User input always parameterized via websearch_to_tsquery on PostgreSQL.",
            "Dialect-aware: falls back to ILIKE on non-PostgreSQL databases (SQLite, MySQL).",
            "Autocomplete uses prefix tsquery (term:*) on PostgreSQL, ILIKE prefix on others.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Restart the application so route changes take effect.",
            "NOTE: The migration uses CREATE INDEX CONCURRENTLY — run outside a transaction block.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _search_already_installed(app_dir: Path) -> bool:
    crud_dir = app_dir / "crud"
    if not crud_dir.exists():
        return False
    for f in sorted(crud_dir.glob("*.py")):
        if f.exists() and "Full-text search helpers" in f.read_text():
            return True
    return False


def _discover_models_with_fields(app_dir: Path) -> dict[tuple[str, str], list[str]]:
    """Return (snake_stem, PascalName) → text-field list for searchable models."""
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    result: dict[tuple[str, str], list[str]] = {}
    available_routes = (
        {r.stem for r in routes_dir.glob("*.py") if r.stem != "__init__"}
        if routes_dir.exists()
        else set()
    )
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in _SKIP_MODELS or stem not in available_routes:
            continue
        src = f.read_text()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        base_subclasses = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        base_subclasses = [c for c in base_subclasses if c.lower() == stem]
        if not base_subclasses:
            continue
        fields = _extract_text_fields(src)
        result[(stem, base_subclasses[0])] = fields if fields else ["title", "description"]
    return result


def _extract_text_fields(src: str) -> list[str]:
    fields: list[str] = []
    for line in src.splitlines():
        s = line.strip()
        if "Mapped[str" in s and "mapped_column" in s:
            name = s.split(":")[0].strip()
            if name and name.isidentifier() and name not in ("id", "owner_id"):
                fields.append(name)
    return fields


def _patch_crud(crud_file: Path, model_name: str, text_fields: list[str]) -> None:
    src = crud_file.read_text()
    if "async def search" in src:
        return

    weight_labels = ["A", "B", "C", "D"]
    field_vec_lines = []
    for i, field in enumerate(text_fields[:4]):
        label = weight_labels[i]
        field_vec_lines.append(
            "    _func.setweight(_func.to_tsvector(_func.cast(lang, _REGCONFIG),"
            + f" _func.coalesce({model_name}.{field}, '')), _text(\"'{label}'\")),"
        )
    field_vecs_block = "[\n" + "\n".join(field_vec_lines) + "\n    ]"
    first_field = text_fields[0] if text_fields else "id"

    additions = render(
        _HERE,
        "crud_additions.py.tmpl",
        {
            "model_name": model_name,
            "search_field_names": repr(text_fields[:4]),
            "field_vecs": field_vecs_block,
            "first_field": first_field,
        },
    )
    crud_file.write_text(src + additions)


def _patch_schema(schema_file: Path, model_name: str) -> None:
    src = schema_file.read_text()
    if "SearchParams" in src:
        return
    for missing in ("ConfigDict", "Field"):
        if missing not in src:
            src = src.replace(
                "from pydantic import BaseModel",
                f"from pydantic import BaseModel, {missing}",
            )
    schema_file.write_text(
        src + render(_HERE, "schema_additions.py.tmpl", {"model_name": model_name})
    )


def _patch_routes(route_file: Path, model_name: str) -> None:
    src = route_file.read_text()
    if "async def search_" in src or "/search" in src:
        return
    stem = route_file.stem
    header_lines = [
        f"from app.crud.{stem} import search as _crud_search",
        f"from app.crud.{stem} import autocomplete as _crud_autocomplete",
        f"from app.schemas.{stem} import {model_name}_SearchResponse",
        f"from app.schemas.{stem} import {model_name}_SearchResultItem",
        f"from app.schemas.{stem} import {model_name}_AutocompleteResult",
        "from fastapi import HTTPException",
        "from fastapi import Query as _SearchQuery",
    ]
    new_imports = "\n".join(line for line in header_lines if line.strip() not in src)
    additions = render(
        _HERE,
        "routes_additions.py.tmpl",
        {"lower": model_name.lower(), "model_name": model_name, "import_header": new_imports},
    )
    id_route_match = re.search(r'^@router\.get\("/?\{', src, re.MULTILINE)
    if id_route_match is not None:
        pos = id_route_match.start()
        while pos > 0 and src[pos - 1] == "\n":
            pos -= 1
        route_file.write_text(src[:pos] + additions + "\n" + src[pos:])
    else:
        route_file.write_text(src + additions)


def _write_migration(versions_dir: Path, model_name: str, text_fields: list[str]) -> Path:
    table = model_name.lower() + "s"
    rev_id = "search_idx_" + table
    weight_labels = ["A", "B", "C", "D"]
    parts = [
        f"        setweight(to_tsvector('english', coalesce({field}, '')), '{weight_labels[i]}')"
        for i, field in enumerate(text_fields[:4])
    ]
    return render_to(
        _HERE,
        "migration.py.tmpl",
        dest=versions_dir / f"{rev_id}.py",
        substitutions={
            "table": table,
            "rev_id": rev_id,
            "down_rev": find_migration_head(versions_dir) or "0001_initial",
            "generated_expr": "\n        ||\n".join(parts),
        },
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_search_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_search_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


