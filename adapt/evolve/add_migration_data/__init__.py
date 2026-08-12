"""TOOL-043: add_migration_data — data migration framework for FastAPI/SQLAlchemy projects.

Generates a self-contained ``data_migrations/`` module with a ``DataMigration``
base class, cursor-based batching (``WHERE id > last_id``), checkpointing,
dry-run support, idempotent upsert via ``INSERT ... ON CONFLICT``, progress
reporting, and a CLI entry-point.

The tool is idempotent: a second run on a project that already contains
``data_migrations/`` detects the ``DataMigration`` fingerprint and returns
``status="no_op"`` without overwriting existing migration files.

Warnings:
    - The emitted ``DataMigration.undo()`` raises NotImplementedError by
      default. There is NO generic "downgrade reverses backfill" guarantee:
      reversal is feasible only for migrations whose subclass overrides
      ``undo()`` AND whose ``run_batch`` is genuinely reversible. For all
      other cases, restore from a pre-migration ``pg_dump`` snapshot.
    - Dry-run is ON by default; the operator must pass ``--live`` to write.
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
    "name": "fastapi_resiliency_add_migration_data",
    "description": "Add data migration support alongside schema migrations in Alembic.",
    "tags": ["evolve"],
    "entry": "add_migration_data",
}


def add_migration_data(
    inp: ToolInput,
    name: str = "sample_migration",
    batch_size: int = 1000,
    idempotent: bool = True,
    dry_run_default: bool = True,
    checkpoint_table: str = "data_migration_checkpoints",
) -> ToolResult:
    """Scaffold a data migration framework in the given project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would scaffold data_migrations/ for migration: {name}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )


    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
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

    dm_dir = project / "data_migrations"

    base_file = dm_dir / "base.py"
    if base_file.exists() and "DataMigration" in base_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DataMigration base class already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )


    files_modified: list[str] = []
    dm_dir.mkdir(parents=True, exist_ok=True)

    init_file = dm_dir / "__init__.py"
    render_to(_HERE, "init.py.tmpl", dest=init_file, substitutions={})
    files_created.append(str(init_file))

    render_to(
        _HERE,
        "base.py.tmpl",
        dest=base_file,
        substitutions={"checkpoint_table": checkpoint_table},
    )
    files_created.append(str(base_file))

    ckpt_file = dm_dir / "checkpoint_model.py"
    render_to(
        _HERE,
        "checkpoint_model.py.tmpl",
        dest=ckpt_file,
        substitutions={"table": checkpoint_table},
    )
    files_created.append(str(ckpt_file))

    runner_file = dm_dir / "runner.py"
    render_to(_HERE, "runner.py.tmpl", dest=runner_file, substitutions={})
    files_created.append(str(runner_file))

    cli_file = dm_dir / "cli.py"
    render_to(_HERE, "cli.py.tmpl", dest=cli_file, substitutions={})
    files_created.append(str(cli_file))

    sample_file = dm_dir / f"{name}.py"
    if not sample_file.exists():
        idempotent_note = (
            "# Idempotent: re-running on same rows is safe (ON CONFLICT UPDATE)"
            if idempotent
            else ""
        )
        render_to(
            _HERE,
            "sample_migration.py.tmpl",
            dest=sample_file,
            substitutions={
                "name": name,
                "batch_size": str(batch_size),
                "idempotent_note": idempotent_note,
            },
        )
        files_created.append(str(sample_file))

    makefile = project / "Makefile"
    if makefile.exists() and _patch_makefile(makefile, name):
        files_modified.append(str(makefile))

    _emit_project_test(project, files_created)

    # CLAUDE.md pattern #7 — validate emitted .py files parse cleanly.
    # Wave I-1.N closure of Codex v8 HIGH (preserved from pre-migration).
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.exists():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"emitted file failed ast.parse: {p} :: {exc}",
                )

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Data migration framework scaffolded at data_migrations/",
            f"Sample migration: data_migrations/{name}.py",
            f"Checkpoint table: {checkpoint_table}",
            "Dry-run is ON by default — pass --live to execute writes.",
        ],
        next_steps=[
            f"python -m data_migrations.cli run {name} --dry-run",
            f"python -m data_migrations.cli run {name} --live",
            "python -m data_migrations.cli status",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_makefile(makefile: Path, name: str) -> bool:
    """Append data migration Makefile targets if not already present. Returns True if patched."""
    src = makefile.read_text()
    if "data-migrate-dry" in src:
        return False
    # Tab-indented Makefile recipes (preserve original textual layout).
    targets = (
        "\n## Data Migrations\n"
        ".PHONY: data-migrate-dry data-migrate-live data-migrate-status\n"
        "data-migrate-dry:\n"
        f"\tpython -m data_migrations.cli run {name} --dry-run\n\n"
        "data-migrate-live:\n"
        f"\tpython -m data_migrations.cli run {name} --live\n\n"
        "data-migrate-status:\n"
        "\tpython -m data_migrations.cli status\n"
    )
    makefile.write_text(src + targets)
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit tests/test_add_migration_data_emitted.py into the generated project."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_migration_data_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_migration_data_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
