"""TOOL-068: add_ml_model_server — framework-agnostic ML inference layer.

Migrated to per-tool directory + externalized templates (WP-06b).

Creates ``app/ml/`` (registry, loader, predictor), ``app/schemas/ml.py``,
``app/api/routes/ml.py``.  Patches ``app/core/config.py``,
``app/routes/__init__.py``, and ``app/main.py`` (lifespan model loading).

Safety:
* All ML SDK imports (torch, onnxruntime, joblib, sklearn) are LAZY —
  inside function bodies only (S2: boots on CPU-only hosts).
* ``torch.load`` is called with ``weights_only=True`` to prevent
  deserialisation-RCE on untrusted checkpoints (S1).
* Registry ``get()`` raises ``KeyError`` on unknown model id — NO silent
  fallback to a default model (S3 mis-route guard).

Idempotency fingerprint: ``"ModelRegistry"`` in ``app/ml/registry.py``.
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
    "name": "fastapi_resiliency_add_ml_model_server",
    "description": (
        "Add a framework-agnostic ML inference layer with ModelRegistry, Predictor, "
        "batch prediction, and health endpoints.  Zero new pip dependencies — "
        "torch/sklearn/onnxruntime are imported lazily."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_ml_model_server",
}


def add_ml_model_server(inp: ToolInput) -> ToolResult:
    """Add a framework-agnostic ML model serving layer to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    app_dir = project / "app"
    registry_file = app_dir / "ml" / "registry.py"
    if registry_file.exists() and "ModelRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ModelRegistry already present — ML model server already installed, skipped."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/ml/ package (registry.py, loader.py, predictor.py),",
                "         app/schemas/ml.py (PredictionRequest, PredictionResponse),",
                "         app/api/routes/ml.py (POST /predict, POST /predict/batch,",
                "           GET /models, GET /models/{name}/health).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 1: app/ml/ package
    ml_dir = app_dir / "ml"
    ml_dir.mkdir(parents=True, exist_ok=True)
    ml_init = ml_dir / "__init__.py"
    if not ml_init.exists():
        render_to(_HERE, "ml_init.py.tmpl", dest=ml_init, substitutions={})
        files_created.append(str(ml_init))

    # Step 2: registry + loader + predictor
    render_to(_HERE, "registry.py.tmpl", dest=registry_file, substitutions={})
    files_created.append(str(registry_file))
    loader_file = ml_dir / "loader.py"
    render_to(_HERE, "loader.py.tmpl", dest=loader_file, substitutions={})
    files_created.append(str(loader_file))
    predictor_file = ml_dir / "predictor.py"
    render_to(_HERE, "predictor.py.tmpl", dest=predictor_file, substitutions={})
    files_created.append(str(predictor_file))

    # Step 3: schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    ml_schema_file = schemas_dir / "ml.py"
    render_to(_HERE, "ml_schemas.py.tmpl", dest=ml_schema_file, substitutions={})
    files_created.append(str(ml_schema_file))

    # Step 4: HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    ml_routes_file = routes_dir / "ml.py"
    render_to(_HERE, "ml_routes.py.tmpl", dest=ml_routes_file, substitutions={})
    files_created.append(str(ml_routes_file))

    # Step 5: patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 6: register router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 7: patch main.py lifespan
    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    # Step 8: emit project test (P1 #15)
    _emit_project_test(project, files_created)

    # Step 9: ast.parse validation
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

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "ML model server added: ModelRegistry singleton, lazy loader, Predictor,",
            "PredictionRequest/PredictionResponse schemas, and 4 HTTP routes.",
            "All ML framework imports (torch, sklearn, onnxruntime, numpy, tensorflow) are lazy.",
            "app.main boots without any ML library installed.",
            "Model health endpoint tracks last_latency_ms and error_count per model.",
            "Batch prediction respects ML_MAX_BATCH_SIZE from settings.",
        ],
        next_steps=[
            "Register your model loader in app/main.py lifespan:",
            "  from app.ml.registry import get_registry",
            "  from app.ml.loader import load_model",
            "  registry = get_registry()",
            "  registry.register('my_model', lambda: load_model('/path/to/model.pkl'))",
            "Set ML_MODEL_DIR, ML_DEFAULT_MODEL, ML_MAX_BATCH_SIZE, ML_PREDICTION_TIMEOUT_MS in .env.",
            "Restart the FastAPI app so the /ml/* routes are active.",
            'Verify: POST /predict with {"input": [...], "model_name": "my_model"}',
        ],
        execution_time_ms=_ms(start),
    )


def _patch_config(config_file: Path) -> None:
    """Inject ML settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "ML_MODEL_DIR" in src:
        return
    block = (
        "\n"
        "    # --- ML model server settings — added by add_ml_model_server tool ---\n"
        '    ML_MODEL_DIR: str = "/models"\n'
        '    ML_DEFAULT_MODEL: str = "default"\n'
        "    ML_MAX_BATCH_SIZE: int = 32\n"
        "    ML_PREDICTION_TIMEOUT_MS: int = 5000\n"
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
    """Register the ML router in ``app/routes/__init__.py`` idempotently."""
    import_line = "from app.api.routes.ml import router as ml_router"
    include_line = "api_router.include_router(ml_router)"
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


def _patch_main(main_file: Path) -> bool:
    """Inject ``get_registry()`` in ``app/main.py``'s lifespan startup."""
    src = main_file.read_text()
    if "ml_model_server" in src:
        return False
    lines = src.splitlines()
    last_from_app = max((i for i, ln in enumerate(lines) if ln.startswith("from app.")), default=-1)
    if last_from_app == -1:
        return False
    lines.insert(
        last_from_app + 1,
        "from app.ml.registry import get_registry  # ml_model_server",
    )
    yield_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1)
    if yield_idx != -1:
        indent = lines[yield_idx][: len(lines[yield_idx]) - len(lines[yield_idx].lstrip())]
        lines.insert(
            yield_idx,
            f"{indent}get_registry()  # ML registry initialised — register models here",
        )
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit the project-level test (P1 #15)."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_ml_model_server_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_ml_model_server_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
