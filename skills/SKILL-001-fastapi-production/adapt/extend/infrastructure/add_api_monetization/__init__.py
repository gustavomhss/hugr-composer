"""TOOL-119: add_api_monetization — usage-metered billing with Stripe Billing Meters v2.

Writes a ``MeteringMiddleware`` that tracks per-endpoint call counts,
a metering rules DSL, a Stripe Meter sync service (batching + retry +
dead-letter), usage dashboard routes (GET /billing/usage, /billing/history,
/billing/limits), tier-enforcement (429 on quota exhaustion), self-serve
plan management (POST /billing/upgrade, GET /billing/plans), usage alerts
at 80/90/100%, revenue analytics for admins, a ``UsageRecord`` SQLAlchemy
model with an Alembic migration, and all required ``settings`` fields.

Idempotency — a second run detects the ``MeteringMiddleware`` fingerprint
and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_api_monetization",
    "description": (
        "Add usage-metered billing with Stripe Billing Meters v2: MeteringMiddleware, "
        "metering rules DSL, Stripe Meter sync with batching+retry, usage dashboard, "
        "tier enforcement 429 on quota exhaustion, self-serve plan management, "
        "usage alerts at 80/90/100%, and revenue analytics for admins."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_api_monetization",
}


def add_api_monetization(inp: ToolInput) -> ToolResult:
    """Add usage-metered API billing via Stripe Billing Meters v2.

    Creates MeteringMiddleware, metering rules DSL, Stripe Meter sync,
    billing routes, UsageRecord model, Alembic migration, and config fields.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
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

    project = Path(inp.project_dir)
    app_dir = project / "app"

    metering_file = app_dir / "billing" / "metering.py"
    if metering_file.exists() and "MeteringMiddleware" in metering_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "MeteringMiddleware already present in app/billing/metering.py — "
                "API monetization already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/billing/metering.py, app/billing/rules.py,",
                "         app/billing/stripe_meter_sync.py, app/models/usage_record.py,",
                "         app/schemas/billing.py, app/api/routes/billing.py,",
                "         and an Alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    billing_dir = app_dir / "billing"
    billing_dir.mkdir(parents=True, exist_ok=True)
    billing_init = billing_dir / "__init__.py"
    if not billing_init.exists():
        billing_init.write_text('"""Billing and metering package."""\n')
        files_created.append(str(billing_init))

    render_to(_HERE, "metering.py.tmpl", dest=metering_file, substitutions={})
    files_created.append(str(metering_file))

    rules_file = billing_dir / "rules.py"
    render_to(_HERE, "rules.py.tmpl", dest=rules_file, substitutions={})
    files_created.append(str(rules_file))

    sync_file = billing_dir / "stripe_meter_sync.py"
    render_to(_HERE, "stripe_meter_sync.py.tmpl", dest=sync_file, substitutions={})
    files_created.append(str(sync_file))

    usage_model_file = app_dir / "models" / "usage_record.py"
    render_to(_HERE, "usage_record_model.py.tmpl", dest=usage_model_file, substitutions={})
    files_created.append(str(usage_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("usage_record", "UsageRecord")])
        files_modified.append(str(models_init))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    billing_schema_file = schemas_dir / "billing.py"
    render_to(_HERE, "billing_schemas.py.tmpl", dest=billing_schema_file, substitutions={})
    files_created.append(str(billing_schema_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    billing_route_file = routes_dir / "billing.py"
    render_to(_HERE, "billing_routes.py.tmpl", dest=billing_route_file, substitutions={})
    files_created.append(str(billing_route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or None
        rev_id = "0_add_usage_records"
        down_rev_repr = f'"{down_rev}"' if down_rev else "None"
        migration_file = versions_dir / f"{rev_id}.py"
        render_to(
            _HERE,
            "migration.py.tmpl",
            dest=migration_file,
            substitutions={
                "rev_id": rev_id,
                "down_rev": down_rev or "",
                "down_rev_repr": down_rev_repr,
            },
        )
        files_created.append(str(migration_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "API Monetization added: MeteringMiddleware, metering rules DSL,",
            "Stripe Meter sync with batching+retry, UsageRecord model,",
            "GET /billing/usage, GET /billing/history, GET /billing/limits,",
            "POST /billing/upgrade, GET /billing/plans,",
            "Usage alerts at 80/90/100%, admin revenue analytics.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set METERING_ENABLED=true, STRIPE_METER_API_KEY, METERING_BATCH_SIZE in .env",
            "Register MeteringMiddleware in app/main.py after auth middleware",
            "Define metering rules via meter() DSL in app/billing/rules.py",
            "Configure USAGE_ALERT_WEBHOOK_URL for 80/90/100% quota alerts",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path, entries: list[tuple[str, str]]) -> None:
    """Register model imports in app/models/__init__.py."""
    content = models_init.read_text()
    lines_to_add = []
    for module, cls in entries:
        import_line = f"from app.models.{module} import {cls}  # noqa: F401"
        if import_line not in content and f"from app.models.{module} import {cls}" not in content:
            lines_to_add.append(import_line)
    if lines_to_add:
        models_init.write_text(content.rstrip() + "\n" + "\n".join(lines_to_add) + "\n")


def _patch_config(config_file: Path) -> None:
    """Inject metering config fields into Settings class."""
    content = config_file.read_text()
    if "METERING_ENABLED" in content:
        return
    block = (
        "\n"
        "    # --- API Monetization — added by add_api_monetization tool ---\n"
        "    METERING_ENABLED: bool = False\n"
        '    STRIPE_METER_API_KEY: str = ""\n'
        "    METERING_BATCH_SIZE: int = 100\n"
        '    USAGE_ALERT_WEBHOOK_URL: str = ""\n'
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in content:
        content = content.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in content:
            content = content.replace(
                settings_line,
                block.lstrip("\n") + "\n\n" + settings_line,
            )
    config_file.write_text(content)


def _patch_routes_init(routes_init: Path) -> None:
    """Register billing router in app/routes/__init__.py."""
    content = routes_init.read_text()
    import_line = "from app.api.routes.billing import router as billing_router"
    include_line = "api_router.include_router(billing_router)"
    if "billing_router" not in content:
        content = content.rstrip() + f"\n{import_line}\n{include_line}\n"
        routes_init.write_text(content)


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure stripe and httpx are in requirements.txt."""
    content = requirements_file.read_text()
    additions = []
    if "stripe>=" not in content:
        additions.append("stripe>=7.0.0\n")
    if "httpx>=" not in content:
        additions.append("httpx>=0.28.0\n")
    if additions:
        requirements_file.write_text(content.rstrip() + "\n" + "".join(additions))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_api_monetization_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_api_monetization_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_api_monetization_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
