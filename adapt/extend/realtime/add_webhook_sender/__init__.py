"""TOOL-015: add_webhook_sender — outbound webhook delivery backed by primitives.

Rails-style wiring (CONTRACT §B1.0): copy primitives, emit ≤20-line glue, emit
models/worker/CRUD/routes/schemas/migration.  Idempotent (DetachedSigner check).
Templates in ``templates/`` emit all generated source; this file orchestrates.

Warnings:
    Delivery at-most-once per attempt; exactly-once NOT guaranteed.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_realtime_add_webhook_sender",
    "description": (
        "Copy SignatureVerifier + RetryPolicy primitives into the project "
        "and wire a ≤20-line app/webhooks/sender.py glue that signs and "
        "retries outbound webhook POSTs."
    ),
    "tags": ["extend", "realtime"],
    "entry": "add_webhook_sender",
    "imports_primitives": [
        "core.venous.security.SignatureVerifier",
        "core.venous.resiliency.RetryPolicy",
    ],
    "imports_adapters": (),
}


def add_webhook_sender(
    inp: ToolInput,
    *,
    max_attempts: int = 7,
    http_timeout_seconds: float = 10.0,
    max_payload_bytes: int = 262_144,
    disable_after_consecutive_failures: int = 12,
) -> ToolResult:
    """Add outbound webhook delivery to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` and optional ``dry_run``.
        max_attempts: Total delivery attempts (default 7).
        http_timeout_seconds: Per-request HTTP timeout (default 10.0).
        max_payload_bytes: Payload size cap in bytes (default 262144).
        disable_after_consecutive_failures: Auto-disable threshold (default 12).

    Returns:
        ``ToolResult`` with status, files_created, files_modified, notes, next_steps.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first: fastapi_generate_project(...)"],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    sender_glue = app_dir / "webhooks" / "sender.py"
    if sender_glue.exists() and "DetachedSigner" in sender_glue.read_text():
        return ToolResult(
            status="no_op",
            notes=["Primitives already wired — skipped."],
            execution_time_ms=_ms(start),
        )
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create models, signer, worker, CRUD, routes, migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []
    worker_subs = {
        "http_timeout_seconds": str(http_timeout_seconds),
        "disable_after_consecutive_failures": str(disable_after_consecutive_failures),
    }
    core_subs = {"max_payload_bytes": str(max_payload_bytes)}

    # Step 0: Copy primitives + emit thin glue
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project), names=list(MCP_TOOL["imports_primitives"]), adapters=[]
    )
    files_created.append(manifest.path)
    _ensure_pkg(app_dir / "webhooks", '"""Webhook sender glue package."""\n', files_created)
    render_to(_HERE, "sender_glue.py.tmpl", dest=sender_glue, substitutions={})
    files_created.append(str(sender_glue))

    # Step 1: models
    model_file = app_dir / "models" / "webhook.py"
    if model_file.exists():
        _append_if_missing(model_file, "WebhookEndpoint", "webhook_models.py.tmpl")
        files_modified.append(str(model_file))
    else:
        render_to(_HERE, "webhook_models.py.tmpl", dest=model_file, substitutions={})
        files_created.append(str(model_file))
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("webhook", "WebhookEndpoint"), ("webhook", "WebhookDelivery")],
    )

    # Step 2–3: signer + backoff
    core_dir = app_dir / "core" / "webhooks"
    _ensure_pkg(core_dir, '"""Outbound webhooks sub-package."""\n', files_created)
    for tmpl, dest_name in [("signer.py.tmpl", "signer.py"), ("backoff.py.tmpl", "backoff.py")]:
        render_to(_HERE, tmpl, dest=core_dir / dest_name, substitutions={})
        files_created.append(str(core_dir / dest_name))
    render_to(_HERE, "sender_core.py.tmpl", dest=core_dir / "sender.py", substitutions=core_subs)
    files_created.append(str(core_dir / "sender.py"))

    # Step 4: CRUD
    crud_file = app_dir / "crud" / "webhook.py"
    crud_file.parent.mkdir(parents=True, exist_ok=True)
    if crud_file.exists():
        _append_if_missing(crud_file, "create_endpoint", "webhook_crud.py.tmpl")
        files_modified.append(str(crud_file))
    else:
        render_to(_HERE, "webhook_crud.py.tmpl", dest=crud_file, substitutions={})
        files_created.append(str(crud_file))

    # Step 5: schemas
    schema_file = app_dir / "schemas" / "webhook.py"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    if schema_file.exists() and "WebhookEndpointCreate" not in schema_file.read_text():
        _append_if_missing(schema_file, "WebhookEndpointCreate", "webhook_schemas.py.tmpl")
        files_modified.append(str(schema_file))
    elif not schema_file.exists():
        render_to(_HERE, "webhook_schemas.py.tmpl", dest=schema_file, substitutions={})
        files_created.append(str(schema_file))

    # Step 6: ARQ worker
    _ensure_pkg(app_dir / "workers", '"""Background workers sub-package."""\n', files_created)
    worker_file = app_dir / "workers" / "webhook_worker.py"
    render_to(_HERE, "webhook_worker.py.tmpl", dest=worker_file, substitutions=worker_subs)
    files_created.append(str(worker_file))

    # Step 7: routes
    route_file = app_dir / "api" / "routes" / "webhooks.py"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "webhook_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    # Step 8: migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0015_add_webhook_sender.py"
        render_to(
            _HERE, "webhook_migration.py.tmpl", dest=mig_file, substitutions={"down_rev": down_rev}
        )
        files_created.append(str(mig_file))

    # Step 9: patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            max_attempts,
            http_timeout_seconds,
            max_payload_bytes,
            disable_after_consecutive_failures,
        )
        files_modified.append(str(config_file))

    # Step 10a: patch requirements (worker imports arq at module top-level)
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Step 10: register router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(
            routes_init,
            "from app.api.routes.webhooks import router as webhooks_router",
            "api_router.include_router(webhooks_router)",
        )
        files_modified.append(str(routes_init))

    for path_str in files_created:
        _assert_parses(Path(path_str))

    glue_loc = _count_logic_lines(sender_glue.read_text())
    if glue_loc > 20:
        return ToolResult(
            status="error",
            error=f"Glue {sender_glue} has {glue_loc} logic lines (> 20).",
            execution_time_ms=_ms(start),
        )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Primitives: SignatureVerifier, RetryPolicy.",
            "Glue: app/webhooks/sender.py wires DetachedSigner + send_webhook.",
            f"Max attempts: {max_attempts}.  Auto-disable after: {disable_after_consecutive_failures} failures.",
            f"Payload cap: {max_payload_bytes}B.  HTTP timeout: {http_timeout_seconds}s.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — ARQ worker requires Redis.",
            "Run: arq app.workers.webhook_worker.WorkerSettings",
            "Restart the app so the webhooks router is active.",
        ],
        execution_time_ms=_ms(start),
    )


# --- Helpers -----------------------------------------------------------------


def _ensure_pkg(d: Path, doc: str, c: list[str]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    i = d / "__init__.py"
    if not i.exists():
        i.write_text(doc)
        c.append(str(i))


def _append_if_missing(dest: Path, marker: str, tmpl: str) -> None:
    existing = dest.read_text()
    if marker in existing:
        return
    dest.write_text(existing.rstrip("\n") + "\n\n" + render(_HERE, tmpl, {}))


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines = [
        f"from app.models.{m} import {c}  # noqa: F401"
        for m, c in class_imports
        if f"from app.models.{m} import {c}" not in content
    ]
    if new_lines:
        models_init.write_text(content.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n")


def _patch_config(
    config_file: Path, max_attempts: int, http_timeout: float, max_payload: int, disable_after: int
) -> None:
    src = config_file.read_text()
    if "WEBHOOK_MAX_ATTEMPTS" in src:
        return
    block = (
        "    # --- Webhook sender settings ---\n"
        f"    WEBHOOK_MAX_ATTEMPTS: int = {max_attempts}\n"
        f"    WEBHOOK_HTTP_TIMEOUT_SECONDS: float = {http_timeout}\n"
        f"    WEBHOOK_MAX_PAYLOAD_BYTES: int = {max_payload}\n"
        f"    WEBHOOK_DISABLE_AFTER_FAILURES: int = {disable_after}\n"
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        config_file.write_text(src.replace(anchor, anchor + "\n\n" + block))
    elif "settings = Settings()" in src:
        config_file.write_text(
            src.replace("settings = Settings()", block + "\nsettings = Settings()")
        )
    else:
        config_file.write_text(src.rstrip("\n") + "\n" + block)


def _patch_routes_init(routes_init: Path, import_line: str, include_line: str) -> None:
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_app = max((i for i, ln in enumerate(lines) if ln.startswith("from app.")), default=-1)
    if last_app == -1:
        last_app = max((i for i, ln in enumerate(lines) if "APIRouter()" in ln), default=0)
    lines.insert(last_app + 1, import_line)
    last_inc = max(
        (i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")), default=-1
    )
    if last_inc == -1:
        last_inc = max((i for i, ln in enumerate(lines) if "APIRouter()" in ln), default=0)
    lines.insert(last_inc + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``arq`` is in ``requirements.txt``.

    ``app/workers/webhook_worker.py`` imports ``arq`` at module top-level and
    the next-steps tell the operator to run ``arq ...`` — so arq is a real
    runtime dependency that must be declared. ``httpx`` and ``redis`` are
    already in the base requirements. Idempotent.
    """
    src = requirements_file.read_text()
    if "arq" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "arq>=0.25.0\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    emitted = tests_dir / "test_add_webhook_sender_emitted.py"
    if not emitted.exists():
        render_to(_HERE, "test_add_webhook_sender_emitted.py.tmpl", dest=emitted, substitutions={})
        created.append(str(emitted))


def _assert_parses(path: Path) -> None:
    if path.suffix != ".py" or not path.is_file():
        return
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(f"Generated file {path} has syntax error: {exc}") from exc


def _count_logic_lines(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    loc = sum(
        (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
    )
    return loc


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
