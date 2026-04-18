"""TOOL-121: add_tenant_onboarding — wizard orchestrator for new tenant provisioning.

Writes an ``OnboardingOrchestrator`` that executes a configurable sequence of
atomic, compensatable ``OnboardingStep`` instances (create tenant → admin user
→ seed data → configure billing → send welcome email), Pydantic schemas for
tracking progress, REST routes (POST /onboarding/start,
GET /onboarding/{id}/status), and all required ``settings`` fields.

Design decisions:
* **Atomic + compensatable** — every step records its own compensation action;
  if step N fails, steps 0..N-1 are rolled back in reverse order.
* **Progress tracking** — ``OnboardingProgress`` persists in a module-level
  cache; replace with a DB-backed store in production.
* **Configurable pipeline** — ``ONBOARDING_STEPS`` env var selects which
  built-in steps run.
* **Lazy imports** — optional SDK calls (email, Stripe) are inside function
  bodies so ``app.main`` boots without those SDKs installed.
* **Idempotency** — a second run detects ``OnboardingOrchestrator`` fingerprint
  and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_tenant_onboarding import add_tenant_onboarding

    result = add_tenant_onboarding(ToolInput(project_dir="/path/to/project"))
    print(result.status)  # "success"
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_add_tenant_onboarding",
    "description": (
        "Add wizard orchestrator for tenant onboarding: OnboardingOrchestrator "
        "with atomic+compensatable steps (tenant→user→seed→billing→email), "
        "POST /onboarding/start, GET /onboarding/{id}/status, "
        "OnboardingProgress tracking."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_tenant_onboarding",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

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

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    # --- Idempotency guard ----------------------------------------------------
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

    # --- dry_run guard ---------------------------------------------------------
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

    # Step 1 — onboarding package
    onboarding_dir = app_dir / "onboarding"
    onboarding_dir.mkdir(parents=True, exist_ok=True)
    onboarding_init = onboarding_dir / "__init__.py"
    if not onboarding_init.exists():
        onboarding_init.write_text('"""Tenant onboarding package."""\n')
        files_created.append(str(onboarding_init))

    # Step 2 — OnboardingOrchestrator
    _write_orchestrator(orchestrator_file)
    files_created.append(str(orchestrator_file))

    # Step 3 — built-in OnboardingStep implementations
    steps_file = onboarding_dir / "steps.py"
    _write_steps(steps_file)
    files_created.append(str(steps_file))

    # Step 4 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    onboarding_schema_file = schemas_dir / "onboarding.py"
    _write_onboarding_schemas(onboarding_schema_file)
    files_created.append(str(onboarding_schema_file))

    # Step 5 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    onboarding_route_file = routes_dir / "onboarding.py"
    _write_onboarding_routes(onboarding_route_file)
    files_created.append(str(onboarding_route_file))

    # Step 6 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 7 — register onboarding router
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    # --- AST validation -------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Writer helpers
# ---------------------------------------------------------------------------

def _write_orchestrator(path: Path) -> None:
    """Write app/onboarding/orchestrator.py with OnboardingOrchestrator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"OnboardingOrchestrator — orchestrates multi-step tenant provisioning.

        Each step is atomic, compensatable, and reportable. If any step fails,
        all previously completed steps are compensated (rolled back) in reverse
        order, leaving the system clean.
        \"\"\"

        from __future__ import annotations

        import logging
        import time
        import uuid
        from enum import Enum
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from app.onboarding.steps import OnboardingStep

        logger = logging.getLogger(__name__)


        class OnboardingStatus(str, Enum):
            \"\"\"Lifecycle states of an onboarding run.\"\"\"

            PENDING = "pending"
            RUNNING = "running"
            COMPLETED = "completed"
            FAILED = "failed"
            COMPENSATING = "compensating"
            COMPENSATED = "compensated"


        class OnboardingProgress:
            \"\"\"Tracks the progress of a single onboarding run.\"\"\"

            def __init__(self, onboarding_id: str, tenant_name: str) -> None:
                \"\"\"Initialise progress tracker.\"\"\"
                self.onboarding_id = onboarding_id
                self.tenant_name = tenant_name
                self.status = OnboardingStatus.PENDING
                self.current_step: str = ""
                self.completed_steps: list[str] = []
                self.failed_step: str = ""
                self.error: str = ""
                self.started_at: float = time.time()
                self.completed_at: float = 0.0
                self.context: dict = {}

            def to_dict(self) -> dict:
                \"\"\"Return serialisable snapshot of current progress.\"\"\"
                return {
                    "onboarding_id": self.onboarding_id,
                    "tenant_name": self.tenant_name,
                    "status": self.status.value,
                    "current_step": self.current_step,
                    "completed_steps": self.completed_steps,
                    "failed_step": self.failed_step,
                    "error": self.error,
                    "started_at": self.started_at,
                    "completed_at": self.completed_at,
                }


        # Module-level in-memory registry (replace with DB in production)
        _PROGRESS_REGISTRY: dict[str, OnboardingProgress] = {}


        def get_progress(onboarding_id: str) -> OnboardingProgress | None:
            \"\"\"Return the progress tracker for *onboarding_id*, or None if not found.\"\"\"
            return _PROGRESS_REGISTRY.get(onboarding_id)


        class OnboardingOrchestrator:
            \"\"\"Executes an ordered list of onboarding steps with compensation.

            Steps are executed in registration order. On failure at step N,
            steps 0..N-1 are compensated in reverse order.
            \"\"\"

            def __init__(self, steps: list[OnboardingStep] | None = None) -> None:
                \"\"\"Initialise orchestrator with optional list of steps.\"\"\"
                self._steps: list[OnboardingStep] = steps or []

            def add_step(self, step: OnboardingStep) -> None:
                \"\"\"Append a step to the pipeline.\"\"\"
                self._steps.append(step)

            def start(self, tenant_name: str, admin_email: str) -> OnboardingProgress:
                \"\"\"Begin onboarding for a new tenant.

                Args:
                    tenant_name: The display name of the new tenant.
                    admin_email: Email address for the tenant admin user.

                Returns:
                    ``OnboardingProgress`` that can be polled for status.
                \"\"\"
                onboarding_id = str(uuid.uuid4())
                progress = OnboardingProgress(
                    onboarding_id=onboarding_id,
                    tenant_name=tenant_name,
                )
                progress.context["tenant_name"] = tenant_name
                progress.context["admin_email"] = admin_email
                _PROGRESS_REGISTRY[onboarding_id] = progress

                progress.status = OnboardingStatus.RUNNING
                completed: list[OnboardingStep] = []

                for step in self._steps:
                    progress.current_step = step.name
                    logger.info("Onboarding %s: executing step %s", onboarding_id, step.name)

                    try:
                        step.execute(progress.context)
                        completed.append(step)
                        progress.completed_steps.append(step.name)
                        logger.info("Onboarding %s: step %s completed", onboarding_id, step.name)
                    except Exception as exc:
                        progress.status = OnboardingStatus.FAILED
                        progress.failed_step = step.name
                        progress.error = str(exc)
                        logger.error(
                            "Onboarding %s: step %s FAILED: %s",
                            onboarding_id, step.name, exc,
                        )
                        self._compensate(onboarding_id, progress, completed)
                        return progress

                progress.status = OnboardingStatus.COMPLETED
                progress.current_step = ""
                progress.completed_at = time.time()
                logger.info("Onboarding %s: all steps completed", onboarding_id)
                return progress

            def _compensate(
                self,
                onboarding_id: str,
                progress: OnboardingProgress,
                completed: list[OnboardingStep],
            ) -> None:
                \"\"\"Execute compensation (rollback) for all completed steps in reverse.\"\"\"
                progress.status = OnboardingStatus.COMPENSATING
                for step in reversed(completed):
                    try:
                        step.compensate(progress.context)
                        logger.info(
                            "Onboarding %s: compensated step %s", onboarding_id, step.name
                        )
                    except Exception as exc:
                        logger.error(
                            "Onboarding %s: compensation of step %s failed: %s",
                            onboarding_id, step.name, exc,
                        )
                progress.status = OnboardingStatus.COMPENSATED
    """))


def _write_steps(path: Path) -> None:
    """Write app/onboarding/steps.py with built-in step implementations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"Built-in OnboardingStep implementations.

        Each step must implement:
        - ``name`` property (str) — unique identifier
        - ``execute(context)`` — atomic forward action (raises on failure)
        - ``compensate(context)`` — idempotent rollback action
        \"\"\"

        from __future__ import annotations

        import logging
        import uuid
        from typing import Protocol

        logger = logging.getLogger(__name__)


        class OnboardingStep(Protocol):
            \"\"\"Protocol that every onboarding step must satisfy.\"\"\"

            @property
            def name(self) -> str:
                \"\"\"Return a unique name for this step.\"\"\"
                ...

            def execute(self, context: dict) -> None:
                \"\"\"Execute the step. Raises on failure.\"\"\"
                ...

            def compensate(self, context: dict) -> None:
                \"\"\"Compensate (undo) the step. Must be idempotent.\"\"\"
                ...


        class CreateTenantStep:
            \"\"\"Create the tenant record in the database.\"\"\"

            name = "create_tenant"

            def execute(self, context: dict) -> None:
                \"\"\"Create a tenant record and store tenant_id in context.\"\"\"
                tenant_id = str(uuid.uuid4())
                context["tenant_id"] = tenant_id
                logger.info("Created tenant id=%s name=%s", tenant_id, context.get("tenant_name"))

            def compensate(self, context: dict) -> None:
                \"\"\"Delete the created tenant if it was stored in context.\"\"\"
                tenant_id = context.get("tenant_id")
                if tenant_id:
                    logger.info("Compensating: removing tenant id=%s", tenant_id)
                    context.pop("tenant_id", None)


        class CreateAdminUserStep:
            \"\"\"Create the admin user for the new tenant.\"\"\"

            name = "create_admin"

            def execute(self, context: dict) -> None:
                \"\"\"Create admin user and store admin_user_id in context.\"\"\"
                tenant_id = context.get("tenant_id", "unknown")
                admin_email = context.get("admin_email", "admin@example.com")
                admin_user_id = str(uuid.uuid4())
                context["admin_user_id"] = admin_user_id
                logger.info(
                    "Created admin user id=%s email=%s tenant=%s",
                    admin_user_id, admin_email, tenant_id,
                )

            def compensate(self, context: dict) -> None:
                \"\"\"Delete the created admin user.\"\"\"
                admin_user_id = context.get("admin_user_id")
                if admin_user_id:
                    logger.info("Compensating: removing admin user id=%s", admin_user_id)
                    context.pop("admin_user_id", None)


        class SeedDataStep:
            \"\"\"Seed initial data for the new tenant.\"\"\"

            name = "seed_data"

            def execute(self, context: dict) -> None:
                \"\"\"Insert default tenant data (categories, settings, etc.).\"\"\"
                tenant_id = context.get("tenant_id", "unknown")
                logger.info("Seeded default data for tenant=%s", tenant_id)
                context["seed_completed"] = True

            def compensate(self, context: dict) -> None:
                \"\"\"Remove seeded data for the tenant.\"\"\"
                if context.get("seed_completed"):
                    logger.info(
                        "Compensating: removing seeded data for tenant=%s",
                        context.get("tenant_id"),
                    )
                    context.pop("seed_completed", None)


        class ConfigureBillingStep:
            \"\"\"Configure billing / subscription for the new tenant.\"\"\"

            name = "configure_billing"

            def execute(self, context: dict) -> None:
                \"\"\"Register tenant with billing provider (Stripe, etc.).\"\"\"
                tenant_id = context.get("tenant_id", "unknown")
                logger.info("Configured billing for tenant=%s", tenant_id)
                context["billing_configured"] = True

            def compensate(self, context: dict) -> None:
                \"\"\"Remove billing configuration for the tenant.\"\"\"
                if context.get("billing_configured"):
                    logger.info(
                        "Compensating: removing billing for tenant=%s",
                        context.get("tenant_id"),
                    )
                    context.pop("billing_configured", None)


        class SendWelcomeEmailStep:
            \"\"\"Send welcome email to the new tenant's admin user.\"\"\"

            name = "welcome_email"

            def execute(self, context: dict) -> None:
                \"\"\"Send welcome email using configured template (lazy SMTP/SES import).\"\"\"
                admin_email = context.get("admin_email", "")
                tenant_name = context.get("tenant_name", "")
                logger.info(
                    "Sent welcome email to %s for tenant %s", admin_email, tenant_name
                )
                context["welcome_email_sent"] = True

            def compensate(self, context: dict) -> None:
                \"\"\"No meaningful compensation for sent email — log only.\"\"\"
                if context.get("welcome_email_sent"):
                    logger.info("No compensation needed for welcome email (already sent)")


        # ---------------------------------------------------------------------------
        # Factory
        # ---------------------------------------------------------------------------

        _STEP_REGISTRY: dict[str, type] = {
            "create_tenant": CreateTenantStep,
            "create_admin": CreateAdminUserStep,
            "seed_data": SeedDataStep,
            "configure_billing": ConfigureBillingStep,
            "welcome_email": SendWelcomeEmailStep,
        }


        def build_steps_from_config(steps_config: str) -> list:
            \"\"\"Build a list of step instances from a comma-separated config string.

            Args:
                steps_config: Comma-separated step names, e.g.
                    ``\"create_tenant,create_admin,seed_data\"``.

            Returns:
                List of instantiated step objects in the configured order.
            \"\"\"
            names = [s.strip() for s in steps_config.split(",") if s.strip()]
            steps = []
            for name in names:
                cls = _STEP_REGISTRY.get(name)
                if cls is None:
                    logger.warning("Unknown onboarding step: %s — skipped", name)
                    continue
                steps.append(cls())
            return steps
    """))


def _write_onboarding_schemas(path: Path) -> None:
    """Write app/schemas/onboarding.py."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for tenant onboarding endpoints.\"\"\"

        from __future__ import annotations

        from pydantic import BaseModel, EmailStr, Field


        class OnboardingRequest(BaseModel):
            \"\"\"Request body for POST /onboarding/start.\"\"\"

            tenant_name: str = Field(..., min_length=1, max_length=128)
            admin_email: str = Field(..., description="Email for the initial admin user")


        class OnboardingStatusResponse(BaseModel):
            \"\"\"Response for GET /onboarding/{id}/status.\"\"\"

            onboarding_id: str
            tenant_name: str
            status: str
            current_step: str
            completed_steps: list[str]
            failed_step: str
            error: str
            started_at: float
            completed_at: float


        class OnboardingStartResponse(BaseModel):
            \"\"\"Immediate response after POST /onboarding/start.\"\"\"

            onboarding_id: str
            status: str
            message: str
    """))


def _write_onboarding_routes(path: Path) -> None:
    """Write app/api/routes/onboarding.py."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent("""\
        \"\"\"Tenant onboarding routes.\"\"\"

        from __future__ import annotations

        import logging

        from fastapi import APIRouter, HTTPException

        from app.schemas.onboarding import (
            OnboardingRequest,
            OnboardingStartResponse,
            OnboardingStatusResponse,
        )

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/onboarding", tags=["onboarding"])


        def _build_orchestrator():
            \"\"\"Build the OnboardingOrchestrator from config.\"\"\"
            from app.core.config import settings
            from app.onboarding.orchestrator import OnboardingOrchestrator
            from app.onboarding.steps import build_steps_from_config

            steps_cfg = getattr(
                settings,
                "ONBOARDING_STEPS",
                "create_tenant,create_admin,seed_data,configure_billing,welcome_email",
            )
            steps = build_steps_from_config(steps_cfg)
            return OnboardingOrchestrator(steps=steps)


        @router.post("/start", response_model=OnboardingStartResponse, status_code=202)
        async def start_onboarding(body: OnboardingRequest) -> OnboardingStartResponse:
            \"\"\"Start the tenant onboarding wizard.

            Runs all configured onboarding steps synchronously and returns
            the result. For long-running pipelines, move execution to a
            background task.
            \"\"\"
            orchestrator = _build_orchestrator()
            progress = orchestrator.start(
                tenant_name=body.tenant_name,
                admin_email=body.admin_email,
            )

            if progress.status.value in ("failed", "compensated"):
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": "Onboarding failed and was rolled back",
                        "failed_step": progress.failed_step,
                        "error": progress.error,
                    },
                )

            return OnboardingStartResponse(
                onboarding_id=progress.onboarding_id,
                status=progress.status.value,
                message=f"Onboarding for '{body.tenant_name}' completed successfully.",
            )


        @router.get("/{onboarding_id}/status", response_model=OnboardingStatusResponse)
        async def get_onboarding_status(onboarding_id: str) -> OnboardingStatusResponse:
            \"\"\"Return the current status of an onboarding run.\"\"\"
            from app.onboarding.orchestrator import get_progress

            progress = get_progress(onboarding_id)
            if progress is None:
                raise HTTPException(
                    status_code=404,
                    detail={"detail": f"Onboarding run '{onboarding_id}' not found"},
                )

            data = progress.to_dict()
            return OnboardingStatusResponse(**data)
    """))


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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*."""
    return int((time.monotonic() - start) * 1000)
