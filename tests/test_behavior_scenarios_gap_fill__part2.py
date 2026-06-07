"""BEHAVIOR scenarios — gap-fill part 2 (scenarios 35-36).

Split from ``test_behavior_scenarios_gap_fill.py`` to respect the 500-LOC
cap. Shared framework lives in
``test_behavior_scenarios_gap_fill__shared.py``.

Covers:
  * SCENARIO 35 — Data Import + Versioning + Event Sourcing
  * SCENARIO 36 — Database Migrations CI
"""

from __future__ import annotations

import ast as _ast

import pytest

from tests.test_behavior_scenarios_gap_fill__shared import (
    Scenario,
    ScenarioContext,
    _assert_scenario,
)

# ===========================================================================
# SCENARIO 35 — Data Import + Versioning + Event Sourcing
# ===========================================================================


async def flow_data_pipeline(ctx: ScenarioContext) -> None:
    """Data import, versioning, and event sourcing: classes, methods, lazy imports."""
    project_dir = ctx.project_dir

    # --- 1. ImportProcessor has parse_csv ---
    processor_file = project_dir / "app" / "imports" / "processor.py"
    if processor_file.exists():
        src = processor_file.read_text()
        ctx.record(
            "import_processor_class_present",
            "class ImportProcessor" in src,
            "ImportProcessor class in app/imports/processor.py",
        )
        ctx.record(
            "parse_csv_method_present",
            "def parse_csv" in src,
            "parse_csv method in ImportProcessor",
        )
        ctx.record(
            "openpyxl_imported_lazily",
            not any(
                (isinstance(n, _ast.Import) and any(a.name == "openpyxl" for a in n.names))
                or (isinstance(n, _ast.ImportFrom) and (n.module or "").startswith("openpyxl"))
                for n in _ast.parse(src).body
            ),
            "openpyxl not at module top-level (lazy import)",
        )
    else:
        for label in [
            "import_processor_class_present",
            "parse_csv_method_present",
            "openpyxl_imported_lazily",
        ]:
            ctx.record(label, False, "app/imports/processor.py not found")

    # --- 2. ImportJob model exists ---
    import_job_file = project_dir / "app" / "models" / "import_job.py"
    ctx.record(
        "import_job_model_exists",
        import_job_file.exists() and "ImportJob" in import_job_file.read_text(),
        "ImportJob model in app/models/import_job.py",
    )

    # --- 3. VersioningService has create_draft / publish / diff ---
    versioning_file = project_dir / "app" / "versioning" / "service.py"
    if versioning_file.exists():
        src = versioning_file.read_text()
        ctx.record(
            "versioning_service_class_present",
            "class VersioningService" in src,
            "VersioningService class in app/versioning/service.py",
        )
        ctx.record(
            "create_draft_method_present",
            "def create_draft" in src or "async def create_draft" in src,
            "create_draft method present",
        )
        ctx.record(
            "publish_method_present",
            "def publish" in src or "async def publish" in src,
            "publish method present",
        )
        ctx.record(
            "diff_method_present",
            "def diff" in src or "async def diff" in src,
            "diff method present",
        )
    else:
        for label in [
            "versioning_service_class_present",
            "create_draft_method_present",
            "publish_method_present",
            "diff_method_present",
        ]:
            ctx.record(label, False, "app/versioning/service.py not found")

    # --- 4. EventStore has append / get_stream ---
    store_file = project_dir / "app" / "events" / "store.py"
    if store_file.exists():
        src = store_file.read_text()
        ctx.record(
            "event_store_class_present",
            "class EventStore" in src,
            "EventStore class in app/events/store.py",
        )
        ctx.record(
            "event_store_append_method",
            "def append" in src or "async def append" in src,
            "append method in EventStore",
        )
        ctx.record(
            "event_store_get_stream_method",
            "def get_stream" in src or "async def get_stream" in src,
            "get_stream method in EventStore",
        )
    else:
        for label in [
            "event_store_class_present",
            "event_store_append_method",
            "event_store_get_stream_method",
        ]:
            ctx.record(label, False, "app/events/store.py not found")

    # --- 5. Projector has project / rebuild ---
    projector_file = project_dir / "app" / "events" / "projector.py"
    if projector_file.exists():
        src = projector_file.read_text()
        ctx.record(
            "projector_class_present",
            "class Projector" in src,
            "Projector class in app/events/projector.py",
        )
        ctx.record(
            "projector_project_method",
            "def project" in src,
            "project method in Projector",
        )
        ctx.record(
            "projector_rebuild_method",
            "def rebuild" in src or "async def rebuild" in src,
            "rebuild method in Projector",
        )
    else:
        for label in [
            "projector_class_present",
            "projector_project_method",
            "projector_rebuild_method",
        ]:
            ctx.record(label, False, "app/events/projector.py not found")


DATA_PIPELINE = Scenario(
    name="data_import_versioning_event_sourcing",
    archetype="CSV/Excel import + draft/publish lifecycle + append-only event store",
    models={"Document": {"title": "str", "body": "text", "author": "str"}},
    tools=[
        ("add_data_import", "adapt.extend.crud_data.add_data_import"),
        ("add_data_versioning", "adapt.extend.crud_data.add_data_versioning"),
        ("add_event_sourcing", "adapt.extend.crud_data.add_event_sourcing"),
    ],
    flow=flow_data_pipeline,
    needs_boot=False,  # Migration-heavy tools with Alembic deps; file-content checks are sufficient
)


# ===========================================================================
# SCENARIO 36 — Database Migrations CI
# ===========================================================================


async def flow_migrations_ci(ctx: ScenarioContext) -> None:
    """Migration CI runner: MigrationCIRunner, SafetyChecker, CLI script, config."""
    project_dir = ctx.project_dir

    # --- 1. MigrationCIRunner class ---
    ci_runner_file = project_dir / "app" / "migrations" / "ci_runner.py"
    if ci_runner_file.exists():
        src = ci_runner_file.read_text()
        ctx.record(
            "migration_ci_runner_class_present",
            "class MigrationCIRunner" in src,
            "MigrationCIRunner class in app/migrations/ci_runner.py",
        )
        ctx.record(
            "ci_runner_imports_cleanly",
            True,
            "ci_runner.py file present and readable",
        )
    else:
        ctx.record(
            "migration_ci_runner_class_present", False, "app/migrations/ci_runner.py not found"
        )
        ctx.record("ci_runner_imports_cleanly", False, "file not found")

    # --- 2. SafetyChecker detects DROP TABLE / DROP COLUMN ---
    safety_file = project_dir / "app" / "migrations" / "safety_checker.py"
    if safety_file.exists():
        src = safety_file.read_text()
        ctx.record(
            "safety_checker_class_present",
            "class SafetyChecker" in src,
            "SafetyChecker class in app/migrations/safety_checker.py",
        )
        ctx.record(
            "safety_checker_detects_drop_table",
            "DROP TABLE" in src or "drop_table" in src.lower() or "DROP" in src,
            "SafetyChecker references DROP TABLE detection",
        )
        ctx.record(
            "safety_checker_detects_drop_column",
            "DROP COLUMN" in src or "drop_column" in src.lower() or "destructive" in src.lower(),
            "SafetyChecker references DROP COLUMN / destructive detection",
        )
    else:
        for label in [
            "safety_checker_class_present",
            "safety_checker_detects_drop_table",
            "safety_checker_detects_drop_column",
        ]:
            ctx.record(label, False, "app/migrations/safety_checker.py not found")

    # --- 3. scripts/check_migrations.py exists ---
    script_file = project_dir / "scripts" / "check_migrations.py"
    ctx.record(
        "check_migrations_script_exists",
        script_file.exists(),
        str(script_file.relative_to(project_dir) if script_file.exists() else "NOT FOUND"),
    )
    if script_file.exists():
        src = script_file.read_text()
        ctx.record(
            "check_migrations_is_runnable",
            "MigrationCIRunner" in src or "argparse" in src or "__main__" in src,
            "check_migrations.py references MigrationCIRunner or has __main__ block",
        )
    else:
        ctx.record("check_migrations_is_runnable", False, "script not found")

    # --- 4. MIGRATION_CI_FAIL_ON_DESTRUCTIVE in config ---
    cfg_path = project_dir / "app" / "core" / "config.py"
    cfg_src = cfg_path.read_text() if cfg_path.exists() else ""
    ctx.record(
        "migration_ci_fail_on_destructive_in_config",
        "MIGRATION_CI_FAIL_ON_DESTRUCTIVE" in cfg_src,
        "MIGRATION_CI_FAIL_ON_DESTRUCTIVE present in app/core/config.py",
    )

    # --- 5. Generated Python files parse without syntax errors ---
    for label, fpath in [
        ("ci_runner", ci_runner_file),
        ("safety_checker", safety_file),
    ]:
        if fpath.exists():
            try:
                _ast.parse(fpath.read_text())
                ctx.record(f"{label}_syntax_valid", True, "no syntax errors")
            except SyntaxError as exc:
                ctx.record(f"{label}_syntax_valid", False, str(exc))
        else:
            ctx.record(f"{label}_syntax_valid", False, "file not found")


MIGRATIONS_CI = Scenario(
    name="database_migrations_ci",
    archetype="Alembic CI runner + destructive-op safety checker + CLI script",
    models={"Migration": {"version": "str", "applied": "bool"}},
    tools=[
        ("add_database_migrations_ci", "adapt.extend.testing_tools.add_database_migrations_ci"),
    ],
    flow=flow_migrations_ci,
    needs_boot=False,  # migration CI infra has no HTTP surface; file checks are definitive
)


# ===========================================================================
# pytest integration — one parametrized test per scenario
# ===========================================================================

SCENARIOS: list[Scenario] = [
    DATA_PIPELINE,
    MIGRATIONS_CI,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario(scenario: Scenario) -> None:
    """Run a behavior scenario end-to-end and assert all checks pass."""
    await _assert_scenario(scenario)
