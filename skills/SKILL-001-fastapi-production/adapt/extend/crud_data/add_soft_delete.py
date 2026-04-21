"""TOOL-001: add_soft_delete — ship UnitOfWork primitive + FastAPI adapter.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors `add_graceful_shutdown`):

1. Copy the framework-agnostic primitive `core.venous.data.UnitOfWork`
   into the generated project.
2. Copy the FastAPI adapter `core.venous._adapters.fastapi.UnitOfWorkAdapter`
   alongside it.
3. Emit a thin ``app/soft_delete.py`` (≤20 lines of glue) that uses the
   UnitOfWork to register soft-delete mutations and commit transactionally.

Soft-delete in the framework-free world is a mutation pattern on a UoW:
callers call ``register_removed(entity)`` and the UoW's ``flush_fn`` sets
the ``is_deleted`` flag instead of issuing a physical DELETE. This tool
ships the primitive + adapter so project code can compose that pattern.

The tool is idempotent: a second run detects the import chain in
``app/soft_delete.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir

MCP_TOOL = {
    "name": "fastapi_data_add_soft_delete",
    "description": (
        "Copy UnitOfWork primitive + FastAPI adapter into the project and "
        "wire a ≤20-line app/soft_delete.py caller."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_soft_delete",
    "imports_primitives": [
        "core.venous.data.UnitOfWork",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.UnitOfWorkAdapter",
    ],
}


_GLUE = '''\
"""Wire soft-delete into the FastAPI app via the UnitOfWork primitive.

Delegates to `UnitOfWorkAdapter` copied under `core/venous/` by
`add_soft_delete`. Hand-editing is safe but the file is re-emitted
idempotently on subsequent tool runs.
"""

from __future__ import annotations

from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency


def _soft_delete_flush(new, dirty, removed):
    """Flip `is_deleted=True` on every 'removed' entity instead of DELETEing."""
    for entity in removed:
        if hasattr(entity, "is_deleted"):
            entity.is_deleted = True


get_uow = make_dependency(_soft_delete_flush)
"""FastAPI dependency yielding a UoW whose 'removed' bucket soft-deletes."""
'''


def add_soft_delete(inp: ToolInput) -> ToolResult:
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first via fastapi_generate_project."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    glue_file = app_dir / "soft_delete.py"

    if glue_file.exists() and "UnitOfWorkAdapter" in glue_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Soft-delete already wired via the UnitOfWork adapter."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would copy UnitOfWork primitive + FastAPI adapter "
                "and write app/soft_delete.py."
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.data.UnitOfWork"],
        adapters=["core.venous._adapters.fastapi.UnitOfWorkAdapter"],
    )
    files_created.append(manifest.path)

    app_dir.mkdir(parents=True, exist_ok=True)
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

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
        files_modified=[],
        notes=[
            "Shipped primitive: core.venous.data.UnitOfWork (change-bucket transaction).",
            "Shipped adapter: UnitOfWorkAdapter (FastAPI generator-dependency).",
            "Wrote app/soft_delete.py — depend on get_uow to soft-delete via register_removed().",
        ],
        next_steps=[
            "Add `is_deleted: bool` (or similar) column to any model you want soft-deleted.",
            "In routes: `uow=Depends(get_uow); uow.register_removed(entity)`.",
            "Swap _soft_delete_flush for your SQLAlchemy session.flush() when ready.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
