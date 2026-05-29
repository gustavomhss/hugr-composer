"""TOOL-121: add_tenant_onboarding — wizard orchestrator for new tenant provisioning.

Writes an ``OnboardingOrchestrator`` that executes a configurable sequence of
atomic, compensatable ``OnboardingStep`` instances (create tenant → admin user
→ seed data → configure billing → send welcome email), Pydantic schemas for
tracking progress, REST routes (POST /onboarding/start,
GET /onboarding/{id}/status), and all required ``settings`` fields.

Idempotency — a second run detects ``OnboardingOrchestrator`` fingerprint
and returns ``status="no_op"``.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_tenant_onboarding",
    "description": (
        "Add wizard orchestrator for tenant onboarding: OnboardingOrchestrator "
        "with atomic+compensatable steps (tenant→user→seed→billing→email), "
        "POST /onboarding/start, GET /onboarding/{id}/status, "
        "OnboardingProgress tracking."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_tenant_onboarding",
}


def add_tenant_onboarding(inp: ToolInput) -> ToolResult:
    """Add tenant onboarding wizard orchestrator to a FastAPI project.

    Creates OnboardingOrchestrator, OnboardingStep protocol, Pydantic schemas,
    REST routes, and config fields.

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

    orchestrator_file = app_dir / "onboarding" / "orchestrator.py"
    if orchestrator_file.exists() and "OnboardingOrchestrator" in orchestrator_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "OnboardingOrchestrator already present in app/onboarding/orchestrator.py — "
                "tenant onboarding already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/onboarding/orchestrator.py, app/onboarding/steps.py,",
                "         app/schemas/onboarding.py, app/api/routes/onboarding.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    onboarding_dir = app_dir / "onboarding"
    onboarding_dir.mkdir(parents=True, exist_ok=True)
    onboarding_init = onboarding_dir / "__init__.py"
    if not onboarding_init.exists():
        onboarding_init.write_text('"""Tenant onboarding package."""\n')
        files_created.append(str(onboarding_init))

    render_to(_HERE, "orchestrator.py.tmpl", dest=orchestrator_file, substitutions={})
    files_created.append(str(orchestrator_file))

    steps_file = onboarding_dir / "steps.py"
    render_to(_HERE, "steps.py.tmpl", dest=steps_file, substitutions={})
    files_created.append(str(steps_file))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    onboarding_schema_file = schemas_dir / "onboarding.py"
    render_to(_HERE, "onboarding_schemas.py.tmpl", dest=onboarding_schema_file, substitutions={})
    files_created.append(str(onboarding_schema_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    onboarding_route_file = routes_dir / "onboarding.py"
    render_to(_HERE, "onboarding_routes.py.tmpl", dest=onboarding_route_file, substitutions={})
    files_created.append(str(onboarding_route_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Tenant Onboarding added: OnboardingOrchestrator with atomic+compensatable steps,",
            "Built-in steps: CreateTenantStep, CreateAdminUserStep, SeedDataStep,",
            "  ConfigureBillingStep, SendWelcomeEmailStep.",
            "POST /onboarding/start, GET /onboarding/{id}/status.",
        ],
        next_steps=[
            "Set ONBOARDING_STEPS (comma-separated) in .env, e.g.: "
            "create_tenant,create_admin,seed_data,configure_billing,welcome_email",
            "Set ONBOARDING_WELCOME_EMAIL_TEMPLATE to your email template path",
            "Replace in-memory OnboardingProgress store with DB-backed store in production",
            "Customise SeedDataStep.execute() with your domain seed data",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject onboarding config fields into Settings class."""
    content = config_file.read_text()
    if "ONBOARDING_STEPS" in content:
        return
    block = (
        "\n"
        "    # --- Tenant Onboarding — added by add_tenant_onboarding tool ---\n"
        '    ONBOARDING_STEPS: str = "create_tenant,create_admin,seed_data,configure_billing,welcome_email"\n'
        '    ONBOARDING_WELCOME_EMAIL_TEMPLATE: str = "welcome"\n'
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
    """Register onboarding router in app/routes/__init__.py."""
    content = routes_init.read_text()
    import_line = "from app.api.routes.onboarding import router as onboarding_router"
    include_line = "api_router.include_router(onboarding_router)"
    if "onboarding_router" not in content:
        content = content.rstrip() + f"\n{import_line}\n{include_line}\n"
        routes_init.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_tenant_onboarding_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_tenant_onboarding_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_tenant_onboarding_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
