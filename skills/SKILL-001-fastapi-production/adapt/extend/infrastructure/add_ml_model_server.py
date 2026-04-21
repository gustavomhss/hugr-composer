"""TOOL-068: add_ml_model_server — add a framework-agnostic ML inference layer to a FastAPI project.

Writes an ``app/ml/`` package containing a lazy ``ModelRegistry``, a
``load_model`` helper, a ``Predictor`` class with timing + structured
logging, Pydantic request/response schemas, and four HTTP routes
(``POST /predict``, ``POST /predict/batch``, ``GET /models``,
``GET /models/{name}/health``).

Key design decisions:

* **Zero new pip dependencies** — torch, scikit-learn, onnxruntime, numpy
  and every other ML framework are imported **lazily** (inside function
  bodies only).  The FastAPI app boots without any ML library installed.
* **ModelRegistry singleton** — models are registered at startup via the
  FastAPI lifespan hook and cached in a dict; no per-request load churn.
* **Predictor wraps model.predict()** with ``asyncio.wait_for`` timeout and
  structured ``logging.getLogger(__name__)`` output.
* **Batch prediction** respects ``ML_MAX_BATCH_SIZE`` from settings.
* **Model health endpoint** returns last prediction latency + error rate.

The tool is idempotent: a second run detects ``ModelRegistry`` in
``app/ml/registry.py`` and returns ``status="no_op"`` without touching any
file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_ml_model_server import add_ml_model_server

    result = add_ml_model_server(ToolInput(project_dir="/path/to/project"))
    print(result.status)         # "success"
    print(result.files_created)  # ["…/app/ml/registry.py", …]
    print(result.next_steps)     # ["Register your model loader …"]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites


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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_ml_model_server(inp: ToolInput) -> ToolResult:
    """Add a framework-agnostic ML model serving layer to a FastAPI project.

    Creates ``app/ml/`` (registry, loader, predictor), ``app/schemas/ml.py``,
    ``app/api/routes/ml.py``.  Patches ``app/core/config.py``,
    ``app/routes/__init__.py``, and ``app/main.py`` (lifespan model loading).

    All ML framework imports (torch, sklearn, onnxruntime, numpy, tensorflow)
    are lazy — inside function bodies only.  ``app.main`` boots without any
    ML library installed.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Prerequisite check (standalone mode) --------------------------------
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

    files_created: list[str] = list(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: already installed? --------------------------------------
    registry_file = app_dir / "ml" / "registry.py"
    if registry_file.exists() and "ModelRegistry" in registry_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ModelRegistry already present — ML model server already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
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
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — app/ml/ package
    ml_dir = app_dir / "ml"
    ml_dir.mkdir(parents=True, exist_ok=True)
    ml_init = ml_dir / "__init__.py"
    if not ml_init.exists():
        ml_init.write_text(_ML_INIT_PY)
        files_created.append(str(ml_init))

    # Step 2 — registry
    _write_text_new(registry_file, _ML_REGISTRY_PY)
    files_created.append(str(registry_file))

    # Step 3 — loader
    loader_file = ml_dir / "loader.py"
    _write_text_new(loader_file, _ML_LOADER_PY)
    files_created.append(str(loader_file))

    # Step 4 — predictor
    predictor_file = ml_dir / "predictor.py"
    _write_text_new(predictor_file, _ML_PREDICTOR_PY)
    files_created.append(str(predictor_file))

    # Step 5 — schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    ml_schema_file = schemas_dir / "ml.py"
    _write_text_new(ml_schema_file, _ML_SCHEMAS_PY)
    files_created.append(str(ml_schema_file))

    # Step 6 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    ml_routes_file = routes_dir / "ml.py"
    _write_text_new(ml_routes_file, _ML_ROUTES_PY)
    files_created.append(str(ml_routes_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register ml router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9 — patch app/main.py lifespan for model loading
    main_file = app_dir / "main.py"
    if main_file.exists() and _patch_main(main_file):
        files_modified.append(str(main_file))

    # Step 10 — ast.parse validation loop (INV-03, CC-06, Bug #2)
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
            "Verify: POST /predict with {\"input\": [...], \"model_name\": \"my_model\"}",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Generated file templates
# ---------------------------------------------------------------------------

_ML_INIT_PY = textwrap.dedent("""\
    \"\"\"ML model serving sub-package.

    Re-exports the public API so callers can write::

        from app.ml import ModelRegistry, Predictor, load_model, get_registry
    \"\"\"

    from app.ml.loader import load_model
    from app.ml.predictor import Predictor
    from app.ml.registry import ModelRegistry, get_registry

    __all__ = ["ModelRegistry", "Predictor", "get_registry", "load_model"]
""")


_ML_REGISTRY_PY = textwrap.dedent("""\
    \"\"\"ML ModelRegistry — singleton registry for named model instances.

    Models are registered at FastAPI startup via the lifespan hook and
    retrieved at inference time.  The registry is a plain dict-based
    singleton; no lock is needed because Python's GIL makes dict reads and
    writes thread-safe for CPython.

    Usage::

        registry = get_registry()
        registry.register("resnet50", loader_fn=lambda: load_model("/models/resnet50.pt"))
        model = registry.get("resnet50")
    \"\"\"

    from __future__ import annotations

    import logging
    from collections.abc import Callable
    from typing import Any

    logger = logging.getLogger(__name__)


    class ModelRegistry:
        \"\"\"Dict-based singleton registry for ML model instances.

        Attributes:
            _models: Maps ``name:version`` to the loaded model object.
            _loaders: Maps ``name:version`` to the loader callable.
            _meta: Maps ``name:version`` to metadata dict (version string,
                load time, last_latency_ms, error_count).
        \"\"\"

        def __init__(self) -> None:
            \"\"\"Initialise empty registry stores.\"\"\"
            self._models: dict[str, Any] = {}
            self._loaders: dict[str, Callable[[], Any]] = {}
            self._meta: dict[str, dict[str, Any]] = {}

        def register(
            self,
            name: str,
            loader_fn: Callable[[], Any],
            version: str = "latest",
        ) -> None:
            \"\"\"Register a named model with its lazy loader callable.

            The loader is called at startup (or on first access) to produce
            the model object.  The model is cached after first load.

            Args:
                name: Unique model name (e.g. ``"resnet50"``).
                loader_fn: Zero-argument callable that returns the model.
                version: Optional version string.  Defaults to ``"latest"``.
            \"\"\"
            key = f"{name}:{version}"
            self._loaders[key] = loader_fn
            self._meta[key] = {
                "name": name,
                "version": version,
                "loaded": False,
                "last_latency_ms": None,
                "error_count": 0,
            }
            logger.info("model registered", extra={"model_name": name, "model_version": version})

        def get(self, name: str, version: str = "latest") -> Any:
            \"\"\"Return the model instance, loading it on first access.

            Args:
                name: Registered model name.
                version: Model version.  Defaults to ``"latest"``.

            Returns:
                The loaded model object.

            Raises:
                KeyError: If ``name:version`` is not registered.
                RuntimeError: If the loader callable raises.
            \"\"\"
            key = f"{name}:{version}"
            if key not in self._loaders:
                raise KeyError(f"Model '{key}' is not registered")
            if key not in self._models:
                logger.info("loading model", extra={"model_name": name, "model_version": version})
                self._models[key] = self._loaders[key]()
                self._meta[key]["loaded"] = True
            return self._models[key]

        def list_models(self) -> list[dict[str, Any]]:
            \"\"\"Return metadata for all registered models.

            Returns:
                List of metadata dicts (name, version, loaded, last_latency_ms,
                error_count).
            \"\"\"
            return list(self._meta.values())

        def update_stats(
            self, name: str, version: str, latency_ms: float, *, error: bool = False
        ) -> None:
            \"\"\"Update prediction statistics for a model.

            Args:
                name: Model name.
                version: Model version.
                latency_ms: Prediction latency in milliseconds.
                error: Set to ``True`` when the prediction raised an exception.
            \"\"\"
            key = f"{name}:{version}"
            if key not in self._meta:
                return
            self._meta[key]["last_latency_ms"] = latency_ms
            if error:
                self._meta[key]["error_count"] += 1


    _registry: ModelRegistry | None = None


    def get_registry() -> ModelRegistry:
        \"\"\"Return the process-wide ModelRegistry singleton, creating it lazily.

        Returns:
            The singleton ``ModelRegistry`` instance.
        \"\"\"
        global _registry
        if _registry is None:
            _registry = ModelRegistry()
        return _registry
""")


_ML_LOADER_PY = textwrap.dedent("""\
    \"\"\"ML model loader with lazy framework imports and warmup prediction.

    Supports torch (``.pt``/``.pth``), scikit-learn (``.pkl``/``.joblib``),
    ONNX (``.onnx``), and generic pickle models.  All ML framework imports
    are inside the load functions — ``app.main`` boots without any ML library.

    Usage::

        from app.ml.loader import load_model

        model = load_model("/models/classifier.pkl")
        model = load_model("https://example.com/model.onnx")
    \"\"\"

    from __future__ import annotations

    import logging
    from pathlib import Path
    from typing import Any

    logger = logging.getLogger(__name__)


    def load_model(path_or_url: str) -> Any:
        \"\"\"Load a model from a local path or HTTP URL.

        Dispatch is based on file extension:

        * ``.pt`` / ``.pth`` → ``torch.load``
        * ``.onnx`` → ``onnxruntime.InferenceSession``
        * ``.pkl`` / ``.joblib`` → ``joblib.load``
        * anything else → ``joblib.load`` (generic pickle fallback)

        All ML framework imports are lazy — this function is the ONLY place
        they are imported.

        Args:
            path_or_url: Absolute local path or HTTP(S) URL to the model
                artefact.

        Returns:
            The loaded model object (framework-specific).

        Raises:
            ValueError: If the URL scheme or file extension is unsupported.
            ImportError: If the required ML framework is not installed.
            FileNotFoundError: If a local path does not exist.
        \"\"\"
        resolved_path = _resolve_path(path_or_url)
        ext = Path(resolved_path).suffix.lower()

        if ext in (".pt", ".pth"):
            return _load_torch(resolved_path)
        if ext == ".onnx":
            return _load_onnx(resolved_path)
        return _load_joblib(resolved_path)


    def _resolve_path(path_or_url: str) -> str:
        \"\"\"Download URL to a temp file or return the local path as-is.

        Args:
            path_or_url: Local path or HTTP(S) URL.

        Returns:
            Absolute local path string.
        \"\"\"
        if path_or_url.startswith(("http://", "https://")):
            import tempfile
            import urllib.request

            suffix = Path(path_or_url.split("?")[0]).suffix or ".bin"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            logger.info("downloading model", extra={"url": path_or_url})
            urllib.request.urlretrieve(path_or_url, tmp.name)  # noqa: S310
            return tmp.name
        return path_or_url


    def _load_torch(path: str) -> Any:
        \"\"\"Load a PyTorch model checkpoint.

        Args:
            path: Local path to a ``.pt`` or ``.pth`` file.

        Returns:
            PyTorch model or state dict.
        \"\"\"
        import torch  # lazy — not at module level

        model = torch.load(path, map_location="cpu", weights_only=True)
        logger.info("torch model loaded", extra={"path": path})
        return model


    def _load_onnx(path: str) -> Any:
        \"\"\"Load an ONNX model via onnxruntime.

        Args:
            path: Local path to a ``.onnx`` file.

        Returns:
            ``onnxruntime.InferenceSession`` instance.
        \"\"\"
        import onnxruntime as ort  # lazy — not at module level

        session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        logger.info("onnx model loaded", extra={"path": path})
        return session


    def _load_joblib(path: str) -> Any:
        \"\"\"Load a joblib/pickle model.

        Args:
            path: Local path to the ``.pkl`` or ``.joblib`` file.

        Returns:
            Deserialized model object.
        \"\"\"
        import joblib  # lazy — not at module level

        model = joblib.load(path)
        logger.info("joblib model loaded", extra={"path": path})
        return model
""")


_ML_PREDICTOR_PY = textwrap.dedent("""\
    \"\"\"Predictor — wraps a loaded model with timeout, timing, and structured logging.

    The ``Predictor`` class is framework-agnostic: it calls ``model.predict()``
    (sklearn/joblib convention) and falls back to calling the model directly
    (``model(input)`` — torch/callable convention).  Results are timed and
    logged with ``logging.getLogger(__name__)``.

    Usage::

        from app.ml.predictor import Predictor
        from app.ml.registry import get_registry

        registry = get_registry()
        predictor = Predictor(registry, model_name="resnet50", timeout_ms=5000)
        output = await predictor.predict(input_data)
    \"\"\"

    from __future__ import annotations

    import asyncio
    import logging
    import time
    from typing import Any

    logger = logging.getLogger(__name__)


    class Predictor:
        \"\"\"Async predictor wrapping a registered model.

        Attributes:
            registry: The ``ModelRegistry`` that holds the model.
            model_name: Registered model name.
            model_version: Registered model version (default ``"latest"``).
            timeout_ms: Hard wall-clock timeout in milliseconds.
        \"\"\"

        def __init__(
            self,
            registry: Any,
            model_name: str,
            model_version: str = "latest",
            timeout_ms: int = 5000,
        ) -> None:
            \"\"\"Initialise the predictor.

            Args:
                registry: ``ModelRegistry`` instance.
                model_name: Name of the registered model.
                model_version: Model version.  Defaults to ``"latest"``.
                timeout_ms: Prediction timeout in milliseconds.
            \"\"\"
            self.registry = registry
            self.model_name = model_name
            self.model_version = model_version
            self.timeout_ms = timeout_ms

        async def predict(self, input_data: Any) -> tuple[Any, float]:
            \"\"\"Run a single prediction with timeout and timing.

            Args:
                input_data: Input to pass to the model.

            Returns:
                Tuple of ``(output, latency_ms)`` where *output* is the model
                prediction and *latency_ms* is wall-clock time in milliseconds.

            Raises:
                asyncio.TimeoutError: If prediction exceeds ``timeout_ms``.
                KeyError: If the model is not registered.
                RuntimeError: If the model call raises.
            \"\"\"
            return await asyncio.wait_for(
                self._predict_inner(input_data),
                timeout=self.timeout_ms / 1000.0,
            )

        async def predict_batch(
            self, inputs: list[Any], max_batch_size: int = 32
        ) -> tuple[list[Any], float]:
            \"\"\"Run batch predictions with timeout and timing.

            Splits the batch into chunks of *max_batch_size* and runs each
            chunk sequentially to avoid memory spikes.

            Args:
                inputs: List of inputs to predict on.
                max_batch_size: Maximum chunk size.

            Returns:
                Tuple of ``(outputs, latency_ms)`` where *outputs* is a list of
                predictions aligned with *inputs*.
            \"\"\"
            t0 = time.monotonic()
            outputs: list[Any] = []
            for i in range(0, len(inputs), max_batch_size):
                chunk = inputs[i : i + max_batch_size]
                chunk_out, _ = await asyncio.wait_for(
                    self._predict_inner(chunk),
                    timeout=self.timeout_ms / 1000.0,
                )
                if isinstance(chunk_out, list):
                    outputs.extend(chunk_out)
                else:
                    outputs.append(chunk_out)
            latency_ms = (time.monotonic() - t0) * 1000.0
            self.registry.update_stats(
                self.model_name, self.model_version, latency_ms
            )
            return outputs, latency_ms

        async def _predict_inner(self, input_data: Any) -> tuple[Any, float]:
            \"\"\"Execute the model call in a thread pool and time it.

            Args:
                input_data: Raw input to pass to the model.

            Returns:
                Tuple of ``(output, latency_ms)``.
            \"\"\"
            t0 = time.monotonic()
            try:
                loop = asyncio.get_running_loop()
                output = await loop.run_in_executor(
                    None, self._call_model, input_data
                )
                latency_ms = (time.monotonic() - t0) * 1000.0
                self.registry.update_stats(
                    self.model_name, self.model_version, latency_ms
                )
                logger.info(
                    "prediction complete",
                    extra={
                        "model": self.model_name,
                        "version": self.model_version,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
                return output, latency_ms
            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000.0
                self.registry.update_stats(
                    self.model_name, self.model_version, latency_ms, error=True
                )
                logger.error(
                    "prediction failed",
                    extra={"model": self.model_name, "error": str(exc)},
                )
                raise

        def _call_model(self, input_data: Any) -> Any:
            \"\"\"Call the model synchronously (runs in thread pool).

            Tries ``model.predict(input_data)`` first (sklearn convention),
            then falls back to ``model(input_data)`` (torch/callable convention).

            Args:
                input_data: Input to pass to the model.

            Returns:
                Model output (framework-specific).
            \"\"\"
            model = self.registry.get(self.model_name, self.model_version)
            if hasattr(model, "predict"):
                return model.predict(input_data)
            return model(input_data)
""")


_ML_SCHEMAS_PY = textwrap.dedent("""\
    \"\"\"Pydantic schemas for ML model prediction requests and responses.\"\"\"

    from __future__ import annotations

    from typing import Any

    from pydantic import BaseModel, Field


    class PredictionRequest(BaseModel):
        \"\"\"Request schema for a single prediction.

        Attributes:
            input: Input data for the model.  Accepts any JSON-serialisable
                value (list, dict, float, string, etc.).
            model_name: Name of the registered model to use.
            model_version: Model version.  Defaults to ``"latest"``.
        \"\"\"

        input: Any = Field(..., description="Input data for the model.")
        model_name: str = Field(..., description="Registered model name.")
        model_version: str = Field(
            default="latest", description="Model version (default: latest)."
        )


    class PredictionResponse(BaseModel):
        \"\"\"Response schema for a single prediction.

        Attributes:
            output: Model prediction output.
            model_name: Name of the model that produced the prediction.
            model_version: Version of the model used.
            latency_ms: Wall-clock prediction latency in milliseconds.
        \"\"\"

        output: Any = Field(..., description="Model prediction output.")
        model_name: str = Field(..., description="Model name used.")
        model_version: str = Field(..., description="Model version used.")
        latency_ms: float = Field(..., description="Prediction latency in ms.")


    class BatchPredictionRequest(BaseModel):
        \"\"\"Request schema for batch prediction.

        Attributes:
            inputs: List of input items to predict on.
            model_name: Registered model name.
            model_version: Model version.  Defaults to ``"latest"``.
        \"\"\"

        inputs: list[Any] = Field(..., description="List of inputs to predict on.")
        model_name: str = Field(..., description="Registered model name.")
        model_version: str = Field(
            default="latest", description="Model version (default: latest)."
        )


    class BatchPredictionResponse(BaseModel):
        \"\"\"Response schema for batch prediction.

        Attributes:
            outputs: List of predictions aligned with ``inputs``.
            model_name: Model name used.
            model_version: Model version used.
            latency_ms: Total batch latency in milliseconds.
            count: Number of predictions returned.
        \"\"\"

        outputs: list[Any] = Field(..., description="Batch prediction outputs.")
        model_name: str = Field(..., description="Model name used.")
        model_version: str = Field(..., description="Model version used.")
        latency_ms: float = Field(..., description="Total batch latency in ms.")
        count: int = Field(..., description="Number of predictions.")


    class ModelInfo(BaseModel):
        \"\"\"Public metadata for a registered model.

        Attributes:
            name: Model name.
            version: Model version string.
            loaded: Whether the model has been loaded into memory.
            last_latency_ms: Latency of the most recent prediction (ms).
            error_count: Total number of prediction errors since startup.
        \"\"\"

        name: str
        version: str
        loaded: bool
        last_latency_ms: float | None = None
        error_count: int = 0


    class ModelListResponse(BaseModel):
        \"\"\"Response schema for the models list endpoint.

        Attributes:
            data: List of model metadata objects.
            count: Total number of registered models.
        \"\"\"

        data: list[ModelInfo]
        count: int
""")


_ML_ROUTES_PY = textwrap.dedent("""\
    \"\"\"HTTP routes for ML model inference.

    Provides four endpoints:

    * ``POST /ml/predict``              — single prediction
    * ``POST /ml/predict/batch``        — batch prediction
    * ``GET  /ml/models``               — list all registered models
    * ``GET  /ml/models/{name}/health`` — health + last latency for a model

    All endpoints require authentication (``CurrentUser``) so inference
    cannot be triggered anonymously.
    \"\"\"

    from __future__ import annotations

    import asyncio
    import logging

    from fastapi import APIRouter, HTTPException, status

    from app.api.deps import CurrentUser
    from app.core.config import settings
    from app.ml.predictor import Predictor
    from app.ml.registry import get_registry
    from app.schemas.ml import (
        BatchPredictionRequest,
        BatchPredictionResponse,
        ModelInfo,
        ModelListResponse,
        PredictionRequest,
        PredictionResponse,
    )

    logger = logging.getLogger(__name__)

    router = APIRouter(prefix="/ml", tags=["ml"])


    def _get_predictor(model_name: str, model_version: str) -> Predictor:
        \"\"\"Build a ``Predictor`` for *model_name* or raise 404.

        Args:
            model_name: Registered model name.
            model_version: Model version string.

        Returns:
            A configured ``Predictor`` instance.

        Raises:
            HTTPException(404): Model not registered.
        \"\"\"
        registry = get_registry()
        models = {
            f"{m['name']}:{m['version']}"
            for m in registry.list_models()
        }
        if f"{model_name}:{model_version}" not in models:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model '{model_name}' version '{model_version}' is not registered.",
            )
        return Predictor(
            registry,
            model_name=model_name,
            model_version=model_version,
            timeout_ms=settings.ML_PREDICTION_TIMEOUT_MS,
        )


    @router.post("/predict", response_model=PredictionResponse, status_code=200)
    async def predict(
        req: PredictionRequest,
        current_user: CurrentUser,
    ) -> PredictionResponse:
        \"\"\"Run a single model prediction.

        Args:
            req: ``PredictionRequest`` with input, model_name, model_version.
            current_user: Authenticated user (auth gate only).

        Returns:
            ``PredictionResponse`` with output and latency_ms.

        Raises:
            HTTPException(404): Model not registered.
            HTTPException(504): Prediction timed out.
            HTTPException(500): Prediction raised an unexpected error.
        \"\"\"
        _ = current_user
        predictor = _get_predictor(req.model_name, req.model_version)
        try:
            output, latency_ms = await predictor.predict(req.input)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={"detail": "Prediction timed out"},
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": str(exc)},
            )
        except Exception as exc:
            logger.error("predict endpoint error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"detail": "Prediction failed"},
            )
        return PredictionResponse(
            output=output,
            model_name=req.model_name,
            model_version=req.model_version,
            latency_ms=latency_ms,
        )


    @router.post("/predict/batch", response_model=BatchPredictionResponse, status_code=200)
    async def predict_batch(
        req: BatchPredictionRequest,
        current_user: CurrentUser,
    ) -> BatchPredictionResponse:
        \"\"\"Run batch predictions (respects ML_MAX_BATCH_SIZE).

        Args:
            req: ``BatchPredictionRequest`` with inputs list, model_name, version.
            current_user: Authenticated user (auth gate only).

        Returns:
            ``BatchPredictionResponse`` with outputs list and total latency_ms.

        Raises:
            HTTPException(422): Batch exceeds ML_MAX_BATCH_SIZE.
            HTTPException(404): Model not registered.
            HTTPException(504): Prediction timed out.
            HTTPException(500): Unexpected error.
        \"\"\"
        _ = current_user
        if len(req.inputs) > settings.ML_MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"detail": f"Batch size {len(req.inputs)} exceeds limit {settings.ML_MAX_BATCH_SIZE}"},
            )
        predictor = _get_predictor(req.model_name, req.model_version)
        try:
            outputs, latency_ms = await predictor.predict_batch(
                req.inputs, max_batch_size=settings.ML_MAX_BATCH_SIZE
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={"detail": "Batch prediction timed out"},
            )
        except Exception as exc:
            logger.error("predict_batch endpoint error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"detail": "Batch prediction failed"},
            )
        return BatchPredictionResponse(
            outputs=outputs,
            model_name=req.model_name,
            model_version=req.model_version,
            latency_ms=latency_ms,
            count=len(outputs),
        )


    @router.get("/models", response_model=ModelListResponse, status_code=200)
    async def list_models(current_user: CurrentUser) -> ModelListResponse:
        \"\"\"List all registered models with metadata.

        Args:
            current_user: Authenticated user (auth gate only).

        Returns:
            ``ModelListResponse`` with data list and count.
        \"\"\"
        _ = current_user
        registry = get_registry()
        raw = registry.list_models()
        models = [ModelInfo(**m) for m in raw]
        return ModelListResponse(data=models, count=len(models))


    @router.get("/models/{name}/health", status_code=200)
    async def model_health(
        name: str,
        current_user: CurrentUser,
    ) -> dict:
        \"\"\"Return health info for a specific model.

        Args:
            name: Registered model name.
            current_user: Authenticated user (auth gate only).

        Returns:
            Dict with ``name``, ``loaded``, ``last_latency_ms``,
            ``error_count``, and ``status``.

        Raises:
            HTTPException(404): Model not registered.
        \"\"\"
        _ = current_user
        registry = get_registry()
        meta = next(
            (m for m in registry.list_models() if m["name"] == name), None
        )
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"detail": f"Model '{name}' is not registered."},
            )
        healthy = meta.get("error_count", 0) == 0 or meta.get("last_latency_ms") is not None
        return {
            "name": meta["name"],
            "version": meta["version"],
            "loaded": meta.get("loaded", False),
            "last_latency_ms": meta.get("last_latency_ms"),
            "error_count": meta.get("error_count", 0),
            "status": "ok" if healthy else "degraded",
        }
""")


# ---------------------------------------------------------------------------
# File-write helper
# ---------------------------------------------------------------------------

def _write_text_new(dest: Path, content: str) -> None:
    """Write *content* to *dest*, creating parent directories.

    Args:
        dest: Absolute destination path.
        content: Text content to write.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Inject ML settings into the ``Settings`` class body.

    The fields are injected with 4-space indent so pydantic-settings reads
    them from env vars.  Idempotent — no-op if ``ML_MODEL_DIR`` already present.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
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
    """Register the ML router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router(
        routes_init,
        import_line="from app.api.routes.ml import router as ml_router",
        include_line="api_router.include_router(ml_router)",
    )


def _register_router(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert.
        include_line: ``api_router.include_router(...)`` call.
    """
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()

    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
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
    """Inject a ``get_registry()`` call in ``app/main.py``'s lifespan startup.

    Adds a comment that instructs the developer to register their models.
    Idempotent: returns ``False`` if ``ml_model_server`` already referenced.

    Args:
        main_file: Path to ``app/main.py``.

    Returns:
        ``True`` if the file was modified.
    """
    src = main_file.read_text()
    if "ml_model_server" in src:
        return False
    lines = src.splitlines()
    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
    if last_from_app == -1:
        return False
    lines.insert(
        last_from_app + 1,
        "from app.ml.registry import get_registry  # ml_model_server",
    )
    yield_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1
    )
    if yield_idx != -1:
        indent = lines[yield_idx][: len(lines[yield_idx]) - len(lines[yield_idx].lstrip())]
        lines.insert(
            yield_idx,
            f"{indent}get_registry()  # ML registry initialised — register models here",
        )
    main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    return True


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
