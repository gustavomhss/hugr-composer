"""TOOL-091: add_database_migrations_ci — Alembic CI runner + rollback safety + schema diff.

Generates ``app/migrations/__init__.py``, ``app/migrations/ci_runner.py`` with
``MigrationCIRunner``, ``app/migrations/safety_checker.py`` with ``SafetyChecker``,
and ``scripts/check_migrations.py`` CLI.

The tool is idempotent: a second run detects ``MigrationCIRunner`` and returns
``status="no_op"``.
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
    "name": "fastapi_testing_add_database_migrations_ci",
    "description": "Add Alembic CI runner with rollback safety and schema diff to FastAPI.",
    "tags": ["extend", "testing_tools"],
    "entry": "add_database_migrations_ci",
}


def add_database_migrations_ci(inp: ToolInput) -> ToolResult:
    """Add Alembic CI migrations tooling to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.

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
        Prereq.REQUIREMENTS_TXT,
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
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    ci_runner_file = app_dir / "migrations" / "ci_runner.py"
    if ci_runner_file.exists() and "MigrationCIRunner" in ci_runner_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["MigrationCIRunner already present — migration CI already enabled, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create migrations/__init__.py, ci_runner.py, "
                "safety_checker.py, scripts/check_migrations.py, patch config.py."
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    migrations_dir = app_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    migrations_init = migrations_dir / "__init__.py"
    if not migrations_init.exists():
        render_to(_HERE, "migrations_init.py.tmpl", dest=migrations_init, substitutions={})
        files_created.append(str(migrations_init))

    render_to(_HERE, "ci_runner.py.tmpl", dest=ci_runner_file, substitutions={})
    files_created.append(str(ci_runner_file))

    safety_file = migrations_dir / "safety_checker.py"
    render_to(_HERE, "safety_checker.py.tmpl", dest=safety_file, substitutions={})
    files_created.append(str(safety_file))

    scripts_dir = project / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    check_script = scripts_dir / "check_migrations.py"
    render_to(_HERE, "check_migrations_cli.py.tmpl", dest=check_script, substitutions={})
    files_created.append(str(check_script))

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
    emitted = project / "tests" / "test_add_database_migrations_ci_emitted.py"
    if not emitted.exists():
        render_to(
            _HERE, "test_add_database_migrations_ci_emitted.py.tmpl", dest=emitted, substitutions={}
        )
        files_created.append(str(emitted))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Migration CI tooling added: pending check, rollback safety, schema diff.",
            "MigrationCIRunner.check_pending() detects unapplied migrations.",
            "MigrationCIRunner.verify_rollback() dry-runs downgrade -1 safely.",
            "SafetyChecker.detect_destructive() flags DROP TABLE/COLUMN operations.",
            "scripts/check_migrations.py: CLI runner for CI pipelines.",
        ],
        next_steps=[
            "Add to CI pipeline: python scripts/check_migrations.py --pending",
            "Add rollback check: python scripts/check_migrations.py --rollback",
            "Add schema diff: python scripts/check_migrations.py --diff",
            "Set MIGRATION_CI_FAIL_ON_DESTRUCTIVE=true in CI environment.",
            "alembic must be installed and DATABASE_URL set before running checks.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[
            ("MIGRATION_CI_FAIL_ON_DESTRUCTIVE", "MIGRATION_CI_FAIL_ON_DESTRUCTIVE: bool = True"),
            ("MIGRATION_CI_REQUIRE_ROLLBACK", "MIGRATION_CI_REQUIRE_ROLLBACK: bool = True"),
        ],
    )


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
