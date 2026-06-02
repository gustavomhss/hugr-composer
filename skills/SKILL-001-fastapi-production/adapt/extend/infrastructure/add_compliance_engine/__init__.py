"""TOOL-097: add_compliance_engine — GDPR/SOC2 compliance scaffold for FastAPI.

Emits ``app/core/compliance_engine.py`` (PII registry, Fernet field
encryption, retention helpers), ``app/models/compliance_event.py`` (audit
table), ``app/schemas/compliance.py``, ``app/crud/compliance.py``,
``app/api/routes/compliance.py`` (erasure + SOC2 evidence + Article 30
endpoints), ``app/workers/retention_worker.py``, plus an Alembic migration.

Emitted code lives in ``templates/*.py.tmpl``; this module is orchestration
only.

The tool is idempotent: a second run detects ``ComplianceEngine`` in
``app/core/compliance_engine.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_compliance_engine",
    "description": (
        "Add a GDPR/SOC2 compliance scaffold: PII registry, Fernet field encryption, "
        "audit-log table, retention worker, erasure / evidence / Article 30 endpoints. "
        "Superuser-gated; not a turnkey production compliance engine."
    ),
    "tags": ["extend", "infrastructure", "compliance"],
    "entry": "add_compliance_engine",
}


def add_compliance_engine(inp: ToolInput) -> ToolResult:
    """Add a GDPR/SOC2 compliance scaffold to a FastAPI project.

    Ships the PII registry, Fernet field encryption, audit-log table, retention
    worker and erasure/evidence/Article-30 endpoints — but it is NOT a turnkey
    production engine: the retention worker is not auto-scheduled and nothing
    runs as blocking middleware (see ``warnings``). Erasure/retention act only
    when the endpoints or the worker are invoked; wire them before relying on it.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    engine_file = app_dir / "core" / "compliance_engine.py"

    if engine_file.exists() and "ComplianceEngine" in engine_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ComplianceEngine already present — skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/compliance_engine.py, "
                "app/models/compliance_event.py, app/schemas/compliance.py, "
                "app/crud/compliance.py, app/api/routes/compliance.py, "
                "app/workers/retention_worker.py, alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    engine_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "compliance_engine_core.py.tmpl", dest=engine_file, substitutions={})
    files_created.append(str(engine_file))

    model_file = app_dir / "models" / "compliance_event.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "compliance_event_model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))

    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("compliance_event", "ComplianceEvent")])
        files_modified.append(str(models_init))

    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "compliance.py"
    render_to(_HERE, "compliance_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "compliance.py"
    render_to(_HERE, "compliance_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "compliance.py"
    render_to(_HERE, "compliance_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    worker_file = workers_dir / "retention_worker.py"
    render_to(_HERE, "retention_worker.py.tmpl", dest=worker_file, substitutions={})
    files_created.append(str(worker_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_file = versions_dir / "add_compliance_engine.py"
        render_to(
            _HERE,
            "compliance_migration.py.tmpl",
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
                    execution_time_ms=_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Compliance engine installed: PII registry, Fernet field encryption,",
            "ComplianceEvent audit table, background retention enforcer,",
            "DELETE /compliance/erasure/{user_id} (cascade + certificate),",
            "GET /compliance/evidence/soc2 (SOC2 exporter),",
            "GET /compliance/article30 (GDPR Article 30 auto-gen).",
        ],
        warnings=[
            "COMPLIANCE_ENCRYPTION_KEY env var must be set — encrypt_field "
            "raises RuntimeError otherwise (fail-closed by design). Generate "
            'with `python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.',
            "The retention worker is NOT auto-scheduled — you must wire it "
            "into your lifespan or external scheduler for retention to be "
            "enforced.",
            "Policies emitted here are ADVISORY: the engine logs/audits, it "
            "does NOT act as a blocking middleware. Erasure and retention "
            "only run when the exposed endpoints or the worker are called.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs cryptography",
            "alembic upgrade head",
            "Set COMPLIANCE_ENCRYPTION_KEY (Fernet key) in .env: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"',
            "Set COMPLIANCE_ENABLED=true and COMPLIANCE_RETENTION_DEFAULT_DAYS in .env.",
            "Register retention_worker in your lifespan or scheduler.",
        ],
        execution_time_ms=_ms(start),
    )


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to app/models/__init__.py idempotently."""
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
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject compliance settings into the Settings class body."""
    src = config_file.read_text()
    if "COMPLIANCE_ENABLED" in src:
        return
    block = (
        "\n"
        "    # --- Compliance engine — added by add_compliance_engine tool ---\n"
        "    COMPLIANCE_ENABLED: bool = True\n"
        "    COMPLIANCE_RETENTION_DEFAULT_DAYS: int = 365\n"
        '    COMPLIANCE_ENCRYPTION_KEY: str = ""\n'
    )
    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the compliance router in app/routes/__init__.py."""
    import_line = "from app.api.routes.compliance import router as compliance_router"
    include_line = "api_router.include_router(compliance_router)"
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
    """Ensure cryptography is listed in requirements.txt."""
    src = requirements_file.read_text()
    if "cryptography" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "cryptography>=42.0.0\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_compliance_engine_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_compliance_engine_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
