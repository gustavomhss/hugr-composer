"""TOOL-065: add_stripe_subscription — Stripe subscription billing for a FastAPI project.

Writes ``app/core/stripe_billing.py`` (lazy SDK glue over the shipped
Billing motor + Stripe adapter), ``Subscription`` model (status, period
tracking, cancel semantics), PII-safe Pydantic schemas
(``SubscriptionPublic`` omits ``stripe_customer_id``), async CRUD,
HTTP routes (create, list-mine, cancel, change-plan, webhook), an
Alembic migration, and required settings fields.

Webhook authenticity is enforced via the BillingAdapter's
``construct_webhook_event`` (wraps ``stripe.Webhook.construct_event``,
HMAC-SHA256 with replay tolerance); the ``stripe`` SDK is imported
lazily inside the adapter so the project boots without the SDK.

Emitted code lives in ``templates/*.py.tmpl``; this module is
orchestration only. The tool is idempotent: a second run detects
``StripeBilling`` in ``app/core/stripe_billing.py`` and returns
``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_stripe_subscription",
    "description": (
        "Add production-grade Stripe subscription billing with Subscription model, "
        "webhook receiver, proration on plan change, and idempotent event processing."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_stripe_subscription",
    "imports_primitives": ["core.venous.billing.Billing"],
    "imports_adapters": ["core.venous._adapters.stripe.BillingAdapter"],
}

_SUCCESS_NOTES = [
    "Stripe Subscriptions added: lazy billing helper, Subscription model + schemas + CRUD,",
    "POST /subscriptions, GET /subscriptions/me, POST /subscriptions/{id}/cancel,",
    "POST /subscriptions/{id}/change-plan, and",
    "POST /subscriptions/webhook/stripe (signature-verified via stripe.Webhook.construct_event).",
    "Alembic migration for `subscriptions` table.",
    "Billing motor + StripeBillingAdapter shipped into core/venous/; stripe_billing.py is thin glue. `stripe` is imported lazily inside the adapter — app boots cleanly without the SDK installed (tool still adds it to requirements.txt).",
    "Proration enabled on plan change (create_prorations).",
]
_NEXT_STEPS = [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_BILLING_PORTAL_RETURN_URL in .env.",
    "Expose the webhook: `stripe listen --forward-to http://localhost:8000/api/v1/subscriptions/webhook/stripe` (dev) or configure an endpoint in the Stripe dashboard (prod).",
    "Restart the FastAPI app so the /subscriptions/* routes are loaded.",
    "Test: POST /subscriptions with a valid Stripe price_id and test card (4242 4242 4242 4242).",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_stripe_subscription(inp: ToolInput) -> ToolResult:
    """Add production-grade Stripe subscription billing to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    billing_file = app_dir / "core" / "stripe_billing.py"

    if billing_file.exists() and "StripeBilling" in billing_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "StripeBilling already present in app/core/stripe_billing.py — Stripe subscriptions already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/stripe_billing.py, app/models/subscription.py,",
                "         app/schemas/subscription.py, app/crud/subscription.py,",
                "         app/api/routes/subscriptions.py, and an Alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.billing.Billing"],
        adapters=["core.venous._adapters.stripe.BillingAdapter"],
    )
    files_created.append(manifest.path)

    billing_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "stripe_billing.py.tmpl", dest=billing_file, substitutions={})
    files_created.append(str(billing_file))

    sub_model_file = app_dir / "models" / "subscription.py"
    sub_model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "subscription_model.py.tmpl", dest=sub_model_file, substitutions={})
    files_created.append(str(sub_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("subscription", "Subscription")])
        files_modified.append(str(models_init))

    schema_file = app_dir / "schemas" / "subscription.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "subscription_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_file = app_dir / "crud" / "subscription.py"
    crud_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "subscription_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    route_file = app_dir / "api" / "routes" / "subscriptions.py"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "subscriptions_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_file = versions_dir / "add_stripe_subscription.py"
        render_to(
            _HERE,
            "subscription_migration.py.tmpl",
            dest=migration_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(migration_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

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
        notes=_SUCCESS_NOTES,
        next_steps=_NEXT_STEPS,
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker not in content:
            new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    models_init.write_text(content + "\n".join(new_lines) + "\n")


def _patch_config(config_file: Path) -> None:
    src = config_file.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return
    block = (
        "\n"
        "    # --- Stripe subscriptions — added by add_stripe_subscription tool ---\n"
        '    STRIPE_SECRET_KEY: str = ""\n'
        '    STRIPE_WEBHOOK_SECRET: str = ""\n'
        '    STRIPE_BILLING_PORTAL_RETURN_URL: str = "http://localhost:8000/billing"\n'
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    elif "settings = Settings()" in src:
        src = src.replace("settings = Settings()", block.lstrip("\n") + "\n\nsettings = Settings()")
    else:
        src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    import_line = "from app.api.routes.subscriptions import router as subscriptions_router"
    include_line = "api_router.include_router(subscriptions_router)"
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)
    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    if "stripe" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "stripe>=11.0.0\n")


