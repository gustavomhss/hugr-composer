"""TOOL-109: add_canary_tokens — honeypot endpoints + fake creds + decoy DB records.

Three canary types:

1. Honeypot endpoints — ``/api/v1/internal/config``, ``/api/v1/admin/backup``,
   ``/api/v1/debug/env``.  Any access triggers an alert webhook.
2. Fake credentials — AWS keys, DB connection strings planted in a well-known
   but non-functional location.  If an attacker uses them, the canary fires.
3. Decoy DB records — fake admin users seeded into the User table; any query
   that returns them triggers an alert.

Critical guard: canaries NEVER block requests — the attacker must NOT know they
hit a canary.  Alerting is fire-and-forget (background task).

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``class CanaryRegistry`` in
``app/core/canary/registry.py`` and returns ``status="no_op"``.
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
    "name": "fastapi_resiliency_add_canary_tokens",
    "description": (
        "Add canary token infrastructure: honeypot endpoints, fake credentials, "
        "and decoy DB records that alert on access without blocking the attacker."
    ),
    "tags": ["extend", "infrastructure", "security"],
    "entry": "add_canary_tokens",
}


def add_canary_tokens(inp: ToolInput) -> ToolResult:
    """Add canary token infrastructure to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first."],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    registry_file = app_dir / "core" / "canary" / "registry.py"

    if registry_file.exists() and "class CanaryRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["Canary tokens already installed — skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=["[dry_run] Would install canary token infrastructure."],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    render_to(_HERE, "canary_registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))

    alert_file = app_dir / "core" / "canary" / "alerter.py"
    render_to(_HERE, "canary_alerter.py.tmpl", dest=alert_file, substitutions={})
    files_created.append(str(alert_file))

    honeypot_file = app_dir / "api" / "routes" / "canary_honeypot.py"
    render_to(_HERE, "canary_honeypot_routes.py.tmpl", dest=honeypot_file, substitutions={})
    files_created.append(str(honeypot_file))

    fake_creds_file = app_dir / "core" / "canary" / "fake_credentials.py"
    render_to(_HERE, "canary_fake_credentials.py.tmpl", dest=fake_creds_file, substitutions={})
    files_created.append(str(fake_creds_file))

    seeder_file = app_dir / "core" / "canary" / "decoy_seeder.py"
    render_to(_HERE, "canary_decoy_seeder.py.tmpl", dest=seeder_file, substitutions={})
    files_created.append(str(seeder_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.is_file():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.is_file():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

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

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Canary type 1: Honeypot endpoints /api/v1/internal/config, /api/v1/admin/backup, /api/v1/debug/env.",
            "Canary type 2: Fake credentials in app/core/canary/fake_credentials.py (never used in real code).",
            "Canary type 3: Decoy admin DB records seeded at startup via decoy_seeder.py.",
            "CRITICAL: Canaries NEVER block — attacker sees 200 OK but alert fires in background.",
            "Alert: POST to CANARY_ALERT_WEBHOOK_URL with full request context + canary ID.",
            "⚠ WEBHOOK DELIVERY IS NOT GUARANTEED: alerter is fire-and-forget; HTTP errors are swallowed.",
            "⚠ DECOY SEEDING IS NOT VERIFIED: seed_decoy_records swallows SQL errors so a missing users table is silent.",
        ],
        next_steps=[
            "Set CANARY_ALERT_WEBHOOK_URL in your .env file.",
            "Set CANARY_ENABLED=true in .env.",
            "Call seed_decoy_records(session) during startup (add to lifespan event).",
            "Monitor webhook for canary_triggered events.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject CANARY_* fields inside the Settings class body."""
    src = config_file.read_text()
    if "CANARY_ENABLED" in src:
        return
    fields = '    CANARY_ENABLED: bool = True\n    CANARY_ALERT_WEBHOOK_URL: str = ""\n'
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + fields.rstrip())
    else:
        target = "settings = Settings()"
        if target in src:
            src = src.replace(target, fields + "\n" + target)
        else:
            src = src.rstrip("\n") + "\n" + fields
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register honeypot router in routes/__init__.py idempotently."""
    content = routes_init.read_text()
    if "canary_honeypot" in content:
        return
    addition = (
        "\n"
        "from app.api.routes.canary_honeypot import router as canary_honeypot_router\n"
        "api_router.include_router(canary_honeypot_router)\n"
    )
    if not content.endswith("\n"):
        content += "\n"
    content += addition
    routes_init.write_text(content)


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_canary_tokens_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_canary_tokens_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
