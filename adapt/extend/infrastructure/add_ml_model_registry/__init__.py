"""TOOL-070: add_ml_model_registry — production-grade ML model registry.

Migrated to per-tool directory + externalized templates (WP-06b).

Pure DB registry — no ML framework (torch, sklearn, transformers) imported
anywhere.  Tracks artefact metadata + lifecycle state transitions:
``registered → staging → production`` with rollback + A/B split + compare.

Files created:
* ``app/models/ml_model.py``       — ``MLModel`` SQLAlchemy model
* ``app/schemas/ml_model.py``      — Pydantic schemas
* ``app/crud/ml_model.py``         — async CRUD helpers
* ``app/ml/registry_service.py``   — ``RegistryService``
* ``app/api/routes/ml_registry.py``  — REST endpoints
* ``alembic/versions/add_ml_model_registry.py``  — Alembic migration

Idempotency fingerprint: ``"class MLModel"`` in ``app/models/ml_model.py``.
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
    "name": "fastapi_resiliency_add_ml_model_registry",
    "description": (
        "Add a production-grade ML model registry with versioned artefacts, "
        "promote/rollback lifecycle, A/B split, and a compare endpoint. "
        "Pure DB registry — no ML framework imports."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_ml_model_registry",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_ml_model_registry(inp: ToolInput) -> ToolResult:
    """Add a production-grade ML model registry to a FastAPI project."""
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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    project = Path(inp.project_dir)
    app_dir = project / "app"
    model_file = app_dir / "models" / "ml_model.py"
    if model_file.exists() and "class MLModel" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "class MLModel already present in app/models/ml_model.py — "
                "ML model registry is already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/models/ml_model.py,",
                "         app/schemas/ml_model.py, app/crud/ml_model.py,",
                "         app/ml/registry_service.py,",
                "         app/api/routes/ml_registry.py,",
                "         and an Alembic migration for the ml_models table.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # Step 1: MLModel SQLAlchemy model
    model_file.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, "ml_model.py.tmpl", dest=model_file, substitutions={})
    files_created.append(str(model_file))

    # Step 2: register in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("ml_model", "MLModel")])
        files_modified.append(str(models_init))

    # Step 3: Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "ml_model.py"
    render_to(_HERE, "ml_model_schemas.py.tmpl", dest=schema_file, substitutions={})
    files_created.append(str(schema_file))

    # Step 4: CRUD helpers
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "ml_model.py"
    render_to(_HERE, "ml_model_crud.py.tmpl", dest=crud_file, substitutions={})
    files_created.append(str(crud_file))

    # Step 5: RegistryService
    ml_dir = app_dir / "ml"
    ml_dir.mkdir(parents=True, exist_ok=True)
    ml_init = ml_dir / "__init__.py"
    if not ml_init.exists():
        ml_init.write_text('"""ML subpackage."""\n')
        files_created.append(str(ml_init))
    registry_svc = ml_dir / "registry_service.py"
    render_to(_HERE, "registry_service.py.tmpl", dest=registry_svc, substitutions={})
    files_created.append(str(registry_svc))

    # Step 6: HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "ml_registry.py"
    render_to(_HERE, "ml_registry_routes.py.tmpl", dest=route_file, substitutions={})
    files_created.append(str(route_file))

    # Step 7: Alembic migration (chains onto current HEAD)
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "add_ml_model_registry.py"
        render_to(
            _HERE,
            "ml_migration.py.tmpl",
            dest=mig_file,
            substitutions={"down_rev": down_rev},
        )
        files_created.append(str(mig_file))

    # Step 8: patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 9: register router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 10: emit project test (P1 #15)
    _emit_project_test(project, files_created)

    # Step 11: ast.parse validation
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
            "ML model registry added: MLModel (registered/staging/production/"
            "archived/rolled_back), schemas, CRUD, RegistryService, REST routes.",
            "Endpoints: POST /ml/models, GET /ml/models, "
            "GET /ml/models/{name}/versions, POST /ml/models/{name}/promote, "
            "POST /ml/models/{name}/rollback, POST /ml/models/{name}/ab-test.",
            "Framework-agnostic: no torch/sklearn/etc. imports anywhere.",
            "A/B split uses add_feature_toggles_api if installed; stubs otherwise.",
        ],
        next_steps=[
            "alembic upgrade head",
            "POST /ml/models to register a model artefact.",
            "POST /ml/models/{name}/promote to move a version to production.",
            "GET /ml/models/{name}/versions to list all registered versions.",
            "POST /ml/models/{name}/ab-test to configure percentage rollout "
            "(requires add_feature_toggles_api for persistence).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject ML registry settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "ML_REGISTRY_DEFAULT_FRAMEWORK" in src:
        return
    block = (
        "\n"
        "    # --- ML model registry — added by add_ml_model_registry tool ---\n"
        '    ML_REGISTRY_DEFAULT_FRAMEWORK: str = "sklearn"\n'
        '    ML_REGISTRY_ARTIFACT_BASE_PATH: str = "/tmp/ml_artifacts"\n'
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
    """Register ml_registry router in ``app/routes/__init__.py`` idempotently."""
    import_line = "from app.api.routes.ml_registry import router as ml_registry_router"
    include_line = "api_router.include_router(ml_registry_router)"
    src = routes_init.read_text()
    if import_line in src:
        return
    lines = src.splitlines()
    last_from_app = max((i for i, ln in enumerate(lines) if ln.startswith("from app.")), default=-1)
    if last_from_app == -1:
        for i, ln in enumerate(lines):
            if "api_router" in ln and "APIRouter()" in ln:
                last_from_app = i - 1
                break
    lines.insert(last_from_app + 1, import_line)
    last_include = max(
        (i for i, ln in enumerate(lines) if ln.startswith("api_router.include_router")),
        default=-1,
    )
    if last_include == -1:
        for i, ln in enumerate(lines):
            if "api_router" in ln and "APIRouter()" in ln:
                last_include = i
                break
    lines.insert(last_include + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit the project-level test (P1 #15)."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_ml_model_registry_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_ml_model_registry_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
