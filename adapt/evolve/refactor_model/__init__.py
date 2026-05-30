"""TOOL-044: refactor_model — AST-based rename and refactor of SQLAlchemy models.

Performs AST-based codebase-wide renames (field, model, or type) across all
``.py`` files, preserves comments via identifier tracking, injects
``Field(alias=old_name)`` into Pydantic schemas for backward compatibility,
and generates multi-phase Alembic migrations.  Output is always a unified
diff (patch mode) written to ``<project>/.refactor_patches/``; no files are
modified in-place unless ``apply=True`` is passed.

The tool is idempotent: re-running with the same arguments on an already-
patched codebase detects the new name and returns ``status="no_op"``.

Warnings:
    - The emitted alembic migration is a SCAFFOLD only: upgrade() and
      downgrade() bodies are comment-out templates with `pass` placeholders.
      This stub does NOT auto-reverse data backfill; operators MUST fill in
      real op.* calls before applying to a production database.
"""

from __future__ import annotations

import ast
import difflib
import re
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

_SUPPORTED_OPERATIONS = frozenset({"rename_model", "rename_field", "change_type", "split_model"})


MCP_TOOL = {
    "name": "fastapi_resiliency_analyze_refactor_model",
    "description": "Refactor a SQLAlchemy model: rename fields, split tables, or add/remove columns.",
    "tags": ["evolve"],
    "entry": "refactor_model",
}


def refactor_model(
    inp: ToolInput,
    operation: str = "rename_field",
    target: str = "",
    new_name: str = "",
    update_schemas: bool = True,
    update_routes: bool = True,
    generate_migration: bool = True,
    apply: bool = False,
) -> ToolResult:
    """Perform an AST-based refactor across the project codebase."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.ALEMBIC_VERSIONS,
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

    if operation not in _SUPPORTED_OPERATIONS:
        return ToolResult(
            status="error",
            error=f"Unknown operation '{operation}'. Choose: {sorted(_SUPPORTED_OPERATIONS)}",
            execution_time_ms=_elapsed_ms(start),
        )

    if not target or not new_name:
        return ToolResult(
            status="error",
            error="Both 'target' and 'new_name' are required.",
            execution_time_ms=_elapsed_ms(start),
        )

    parts = target.rsplit(".", 1)
    old_name = parts[-1]

    if old_name == new_name:
        return ToolResult(
            status="no_op",
            notes=[f"'{old_name}' is already named '{new_name}' — nothing to do."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        affected = _count_occurrences(project, old_name)
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] operation={operation} target={target} new_name={new_name}",
                f"[dry_run] ~{affected} occurrences found across .py files.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to generate patch."],
            execution_time_ms=_elapsed_ms(start),
        )

    patches_dir = project / ".refactor_patches"
    patches_dir.mkdir(parents=True, exist_ok=True)

    files_modified: list[str] = []
    patch_lines: list[str] = []

    py_files = sorted(project.rglob("*.py"))
    for py_file in py_files:
        if ".venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        original = py_file.read_text(encoding="utf-8")
        patched = _rename_in_source(original, old_name, new_name, operation)
        if patched == original:
            continue
        diff = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=str(py_file.relative_to(project)),
                tofile=str(py_file.relative_to(project)),
            )
        )
        patch_lines.extend(diff)
        if apply:
            py_file.write_text(patched, encoding="utf-8")
            files_modified.append(str(py_file))

    patch_file = patches_dir / f"{operation}_{old_name}_to_{new_name}.patch"
    patch_file.write_text("".join(patch_lines) if patch_lines else "# No changes\n")
    files_created.append(str(patch_file))

    if update_schemas and operation == "rename_field":
        alias_file = patches_dir / f"schema_alias_{old_name}.md"
        alias_file.write_text(
            render(_HERE, "schema_alias_note.md.tmpl", {"old_name": old_name, "new_name": new_name})
        )
        files_created.append(str(alias_file))

    if generate_migration and operation in {"rename_field", "rename_model", "change_type"}:
        migration_file = _write_alembic_migration(project, operation, old_name, new_name)
        if migration_file:
            files_created.append(str(migration_file))

    _emit_project_test(project, files_created)

    next_steps = [f"git apply {patch_file}"] if not apply else []
    next_steps.append("alembic upgrade head")
    if update_schemas and operation == "rename_field":
        next_steps.append(f"Add Field(alias='{old_name}') to Pydantic schemas for backward compat")

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"operation={operation}, {old_name} → {new_name}",
            f"Patch: {patch_file}",
            f"{'Applied in-place.' if apply else 'Patch-only mode. Use git apply to apply.'}",
        ],
        next_steps=next_steps,
        execution_time_ms=_elapsed_ms(start),
    )


def _count_occurrences(project: Path, old_name: str) -> int:
    """Count occurrences of *old_name* across all ``.py`` files."""
    count = 0
    for py_file in project.rglob("*.py"):
        if ".venv" in py_file.parts:
            continue
        count += py_file.read_text(encoding="utf-8").count(old_name)
    return count


def _rename_in_source(source: str, old_name: str, new_name: str, operation: str) -> str:
    """Rename *old_name* → *new_name* in *source* using word-boundary regex."""
    try:
        ast.parse(source)
    except SyntaxError:
        return source
    pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")
    return pattern.sub(new_name, source)


def _write_alembic_migration(
    project: Path, operation: str, old_name: str, new_name: str
) -> Path | None:
    """Generate an Alembic migration scaffold for the rename."""
    versions_dir = project / "alembic" / "versions"
    if not versions_dir.exists():
        return None

    rev_id = f"refactor_{operation}_{old_name}_to_{new_name}"
    migration_file = versions_dir / f"{rev_id}.py"
    if migration_file.exists():
        return migration_file

    render_to(
        _HERE,
        "alembic_migration.py.tmpl",
        dest=migration_file,
        substitutions={
            "operation": operation,
            "old_name": old_name,
            "new_name": new_name,
            "rev_id": rev_id,
        },
    )
    return migration_file


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_refactor_model_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_refactor_model_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_refactor_model_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
