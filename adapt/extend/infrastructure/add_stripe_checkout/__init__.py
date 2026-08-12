"""TOOL-023: add_stripe_checkout — Stripe Checkout flow for a FastAPI project.

Writes ``app/core/stripe_client.py`` (lazy SDK wrapper), ``Payment`` model
(tenant-aware when ``app/models/tenant.py`` exists), Pydantic schemas that
omit PII from public views, async CRUD keyed on the Stripe Session id,
HTTP routes (create, get, list-mine, webhook), and an Alembic migration.

Webhook authenticity is enforced via ``stripe.Webhook.construct_event``
(HMAC-SHA256 with the 5-minute replay tolerance baked into the SDK); the
``stripe`` SDK is imported lazily inside ``get_stripe()`` so the project
can boot without the SDK installed.

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only. The tool is idempotent: a second run detects ``get_stripe`` in
``app/core/stripe_client.py`` and returns ``status="no_op"``.
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
    "name": "fastapi_resiliency_add_stripe_checkout",
    "description": "Add a production-grade Stripe Checkout flow with Payment model, webhook receiver, and idempotent event processing.",
    "tags": ["extend", "infrastructure"],
    "entry": "add_stripe_checkout",
    "imports_primitives": [],
    "imports_adapters": [],

}

_PAYMENT_TENANT_COL_TENANTED = (
    "    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n"
    "        Uuid,\n"
    '        ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    "        nullable=True,\n"
    "        index=True,\n"
    '        comment="Tenant owning this payment record",\n'
    "    )"
)
_PAYMENT_TENANT_COL_PLAIN = (
    "    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n"
    "        Uuid,\n"
    "        nullable=True,\n"
    "        index=True,\n"
    '        comment="Tenant owning this payment record",\n'
    "    )"
)
_PAYMENT_MIGRATION_TENANT_TENANTED = (
    "        sa.Column(\n"
    '            "tenant_id", sa.Uuid(),\n'
    '            sa.ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    "            nullable=True,\n"
    "        ),"
)
_PAYMENT_MIGRATION_TENANT_PLAIN = '        sa.Column("tenant_id", sa.Uuid(), nullable=True),'

_SUCCESS_NOTES_TAIL = [
    "Stripe Checkout added: lazy SDK wrapper, Payment model + schemas + CRUD,",
    "POST /payments/checkout, GET /payments/{id}, GET /payments/me, and",
    "POST /payments/webhook/stripe (signature-verified via stripe.Webhook.construct_event).",
]
_NEXT_STEPS = [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET in .env.",
    "Expose the webhook endpoint: `stripe listen --forward-to "
    "http://localhost:8000/api/v1/payments/webhook/stripe` (dev) or configure "
    "an endpoint in the Stripe dashboard (prod).",
    "Restart the FastAPI app so the /payments/* routes are loaded.",
    "Test: POST /payments/checkout with a test amount/currency; open the "
    "returned checkout_url; complete with a Stripe test card (4242 4242 4242 4242).",
]
_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def add_stripe_checkout(
    inp: ToolInput,
    *,
    api_version: str = "2024-06-20",
    success_url: str = "http://localhost:8000/success",
    cancel_url: str = "http://localhost:8000/cancel",
) -> ToolResult:
    """Add a production-grade Stripe Checkout flow to a FastAPI project."""
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
    client_file = app_dir / "core" / "stripe_client.py"

    if client_file.exists() and "get_stripe" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "get_stripe already present in app/core/stripe_client.py — Stripe Checkout is already installed, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/stripe_client.py, app/models/payment.py,",
                "         app/schemas/payment.py, app/crud/payment.py, app/api/routes/payments.py,",
                "         and an Alembic migration for the `payments` table"
                + (" (tenant-aware)" if has_tenants else "")
                + ".",
                f"         Stripe api_version={api_version}, success_url={success_url}, cancel_url={cancel_url}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    render_to(_HERE, "stripe_client.py.tmpl", dest=client_file, substitutions={})
    files_created.append(str(client_file))

    payment_model_file = app_dir / "models" / "payment.py"
    tenant_col = _PAYMENT_TENANT_COL_TENANTED if has_tenants else _PAYMENT_TENANT_COL_PLAIN
    render_to(
        _HERE,
        "payment_model.py.tmpl",
        dest=payment_model_file,
        substitutions={"tenant_col": tenant_col},
    )
    files_created.append(str(payment_model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("payment", "Payment")])
        files_modified.append(str(models_init))

    schema_file = app_dir / "schemas" / "payment.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "payment_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_file = app_dir / "crud" / "payment.py"
    crud_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "payment_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    route_file = app_dir / "api" / "routes" / "payments.py"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "payments_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_tenant_col = (
            _PAYMENT_MIGRATION_TENANT_TENANTED if has_tenants else _PAYMENT_MIGRATION_TENANT_PLAIN
        )
        migration_file = versions_dir / "add_stripe_checkout.py"
        render_to(
            _HERE,
            "payment_migration.py.tmpl",
            dest=migration_file,
            substitutions={"down_rev": down_rev, "tenant_col": mig_tenant_col},
        )
        files_created.append(str(migration_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, api_version, success_url, cancel_url)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    env_example = project / ".env.example"
    if env_example.exists():
        _patch_env_example(env_example)
        files_modified.append(str(env_example))

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

    notes = list(_SUCCESS_NOTES_TAIL) + [
        "Alembic migration for `payments` table" + (" (tenant-aware)" if has_tenants else "") + ".",
        f"Stripe api_version pinned to {api_version}.",
        "Stripe SDK is imported lazily inside get_stripe() — the app boots cleanly without `stripe` installed (the tool still adds it to requirements.txt).",
    ]
    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=notes,
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


def _patch_config(config_file: Path, api_version: str, success_url: str, cancel_url: str) -> None:
    src = config_file.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return
    block = (
        "\n"
        "    # --- Stripe payments — added by add_stripe_checkout tool ---\n"
        '    STRIPE_SECRET_KEY: str = ""\n'
        '    STRIPE_PUBLISHABLE_KEY: str = ""\n'
        '    STRIPE_WEBHOOK_SECRET: str = ""\n'
        f'    STRIPE_API_VERSION: str = "{api_version}"\n'
        f'    STRIPE_CHECKOUT_SUCCESS_URL: str = "{success_url}"\n'
        f'    STRIPE_CHECKOUT_CANCEL_URL: str = "{cancel_url}"\n'
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
    import_line = "from app.api.routes.payments import router as payments_router"
    include_line = "api_router.include_router(payments_router)"
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


def _patch_env_example(env_example: Path) -> None:
    src = env_example.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    env_example.write_text(
        src + trailing + "\n# --- Stripe Checkout (add_stripe_checkout) ---\n"
        "STRIPE_SECRET_KEY=sk_test_...\n"
        "STRIPE_PUBLISHABLE_KEY=pk_test_...\n"
        "STRIPE_WEBHOOK_SECRET=whsec_...\n"
    )


