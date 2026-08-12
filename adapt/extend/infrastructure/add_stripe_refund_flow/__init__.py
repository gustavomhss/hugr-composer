"""TOOL-066: add_stripe_refund_flow — Stripe refund flow for a FastAPI project.

Writes ``app/models/refund.py`` (Refund audit table), PII-safe Pydantic
schemas (``RefundPublic`` omits ``stripe_refund_id``), async CRUD,
``app/core/stripe_refunds.py`` (lazy SDK import + idempotency key
``f"refund-{payment_id}-{amount_cents}"``), HTTP routes
(POST /refunds, GET /refunds/{id}, GET /refunds/payment/{payment_id},
POST /refunds/webhook/stripe), and an Alembic migration.

Webhook authenticity is enforced via ``stripe.Webhook.construct_event``
(HMAC-SHA256 with the SDK's 5-minute replay tolerance); the ``stripe``
SDK is imported lazily inside ``create_refund()`` and the webhook
handler, so the project boots without the SDK installed.

Emitted code lives in ``templates/*.py.tmpl``; this module is
orchestration only. The tool is idempotent: a second run detects
``class Refund`` in ``app/models/refund.py`` and returns
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
    "name": "fastapi_resiliency_add_stripe_refund_flow",
    "description": (
        "Add a production-grade Stripe refund flow with Refund model, "
        "PII-safe schemas, async CRUD, REST routes, and a signature-verified "
        "webhook receiver."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_stripe_refund_flow",
    "imports_primitives": [],
    "imports_adapters": [],

}

_SUCCESS_NOTES = [
    "Stripe Refund flow added: lazy SDK wrapper with idempotency key,",
    "Refund model + PII-safe schemas + CRUD,",
    "POST /refunds, GET /refunds/{id}, GET /refunds/payment/{payment_id},",
    "POST /refunds/webhook/stripe (signature-verified).",
    "Alembic migration for `refunds` table.",
    "Auto-approve threshold: refunds <= REFUND_AUTO_APPROVE_THRESHOLD_CENTS are issued immediately.",
    "Ownership-scoped: a non-superuser may only refund/list payments whose user_id is their own; "
    "a cross-user payment_id returns 404 (R5-O3-F4).",
    "Stripe SDK is imported lazily inside create_refund() — the app boots cleanly without `stripe` installed.",
]
_NEXT_STEPS = [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_REFUND_WEBHOOK_SECRET, REFUND_MAX_AMOUNT_CENTS, REFUND_AUTO_APPROVE_THRESHOLD_CENTS in .env.",
    "Expose the webhook endpoint to Stripe dashboard or use: `stripe listen --forward-to http://localhost:8000/api/v1/refunds/webhook/stripe`",
    "Test: POST /refunds with a valid payment_id and amount_cents.",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_stripe_refund_flow(inp: ToolInput) -> ToolResult:
    """Add a production-grade Stripe refund flow to a FastAPI project."""
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
    refund_model_file = app_dir / "models" / "refund.py"

    if refund_model_file.exists() and "class Refund" in refund_model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "class Refund already present in app/models/refund.py — Stripe Refund flow is already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/models/refund.py, app/schemas/refund.py,",
                "         app/crud/refund.py, app/api/routes/refunds.py,",
                "         app/core/stripe_refunds.py, and an Alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    refund_model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "refund_model.py.tmpl", dest=refund_model_file, substitutions={})
    files_created.append(str(refund_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("refund", "Refund")])
        files_modified.append(str(models_init))

    schema_file = app_dir / "schemas" / "refund.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "refund_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_file = app_dir / "crud" / "refund.py"
    crud_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "refund_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    stripe_refunds_file = app_dir / "core" / "stripe_refunds.py"
    stripe_refunds_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "stripe_refunds.py.tmpl", dest=stripe_refunds_file, substitutions={})
    files_created.append(str(stripe_refunds_file))

    route_file = app_dir / "api" / "routes" / "refunds.py"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "refunds_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_file = versions_dir / "add_stripe_refund_flow.py"
        render_to(
            _HERE,
            "refund_migration.py.tmpl",
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
    if "STRIPE_REFUND_WEBHOOK_SECRET" in src:
        return
    block = (
        "\n"
        "    # --- Stripe refunds — added by add_stripe_refund_flow tool ---\n"
        '    STRIPE_REFUND_WEBHOOK_SECRET: str = ""\n'
        "    REFUND_MAX_AMOUNT_CENTS: int = 100_000_00\n"
        "    REFUND_AUTO_APPROVE_THRESHOLD_CENTS: int = 5_000\n"
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
    import_line = "from app.api.routes.refunds import router as refunds_router"
    include_line = "api_router.include_router(refunds_router)"
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


