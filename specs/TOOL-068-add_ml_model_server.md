---
spec_id: "TOOL-068"
tool_name: "add_ml_model_server"
generator: "generators/database/model.py"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-MMS-01"
  - "INV-MMS-02"
  - "INV-MMS-03"
  - "INV-MMS-04"
  - "INV-MMS-05"
  - "INV-MMS-06"
  - "INV-MMS-07"
  - "INV-MMS-08"
  - "INV-MMS-09"
  - "INV-MMS-10"
  - "INV-MMS-11"
  - "INV-MMS-12"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
  - "CC-24"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
  - "T-24"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-068: add_ml_model_server

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_ml_model_server` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings, asyncio (stdlib) |
| Signature | `add_ml_model_server(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_ml_model_server", "description": "Add a framework-agnostic ML inference layer with ModelRegistry, Predictor, batch prediction, and health endpoints. Zero new pip dependencies — torch/sklearn/onnxruntime are imported lazily.", "tags": ["extend", "infrastructure"], "entry": "add_ml_model_server"}` |
| Files created (typical) | 6+ — `app/ml/__init__.py`, `app/ml/registry.py`, `app/ml/loader.py`, `app/ml/predictor.py`, `app/schemas/ml.py`, `app/api/routes/ml.py` |
| Files modified (typical) | 2–3 — `app/core/config.py`, `app/routes/__init__.py`, `app/main.py` (when lifespan present) |

---

## 2. Purpose

The `fastapi_add_ml_model_server` tool installs a production-grade, framework-agnostic ML inference layer into a FastAPI project **without adding a single new pip dependency**. Every ML framework — torch, scikit-learn, onnxruntime, numpy, tensorflow, joblib — is imported lazily, inside function bodies only. The FastAPI application boots cleanly on a CPU-only machine or one with no ML library installed at all. This is the defining constraint: the FastAPI process must remain importable regardless of which (if any) ML framework the developer ultimately chooses.

Teams that install ML serving naively end up with three failure modes: (1) import-time crashes when the ML library is absent in certain deploy environments (workers, CI containers), (2) per-request model loading that serialises every inference call through disk I/O and pickle parsing, and (3) no visibility into whether models are healthy or what their recent latency looks like. This tool eliminates all three failure modes by generating (a) a `ModelRegistry` singleton that loads models lazily on first access and caches them for the lifetime of the process, managed via the FastAPI lifespan hook; (b) a `load_model` helper that dispatches on file extension to `torch.load`, `onnxruntime.InferenceSession`, or `joblib.load` — all lazy — and supports HTTP URL downloads; (c) a `Predictor` class that wraps any registered model's `predict()` or `__call__` interface with `asyncio.wait_for` timeout enforcement, thread-pool offloading via `loop.run_in_executor`, per-prediction structured logging, and `update_stats` calls so `ModelRegistry` tracks last latency and error counts; (d) four HTTP routes under the `/ml` prefix guarded by `CurrentUser` authentication; (e) Pydantic v2 request/response schemas for both single and batch prediction; and (f) patches to `app/core/config.py` that land four `ML_*` fields inside the `Settings` class body so pydantic-settings binds them from environment variables.

The tool is idempotent: a second run detects `"ModelRegistry"` in `app/ml/registry.py` and returns `status="no_op"` without touching any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-10) |
| Files created | ≥ 6 | ml package, schemas, routes (CC-04) |
| Files modified | ≥ 2 | Config, routes init; optionally main.py (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (CC-07) |
| Model load on first access | Lazy, once per process | Cached in `ModelRegistry._models` dict; no per-request I/O |
| `POST /ml/predict` latency (model loaded) | < `ML_PREDICTION_TIMEOUT_MS` | `asyncio.wait_for` enforces hard timeout |
| Batch prediction chunk size | ≤ `ML_MAX_BATCH_SIZE` | Enforced in `predict_batch` loop and route handler |
| `GET /ml/models/{name}/health` latency | < 5 ms | Pure in-memory dict lookup in `ModelRegistry` |
| Model health error tracking | Per-model counters | `update_stats(error=True)` increments `error_count` |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no ModelRegistry in lifespan
│   ├── core/
│   │   └── config.py        # Settings class, no ML_* fields
│   ├── models/
│   │   └── base.py
│   ├── routes/
│   │   └── __init__.py      # api_router, no ml router
│   └── api/
│       └── deps.py          # CurrentUser dependency
└── requirements.txt
```

Every inference call either (a) loads the model from disk on every request — prohibitively slow at scale — or (b) uses a module-level global that crashes at import time when the ML library is absent. Batch prediction has no size guard. There is no visibility into model health, last latency, or error counts.

### 4.2 ModelRegistry singleton: AFTER

```python
# app/ml/registry.py (excerpt)
class ModelRegistry:
    """Dict-based singleton registry for ML model instances.

    Attributes:
        _models: Maps ``name:version`` to the loaded model object.
        _loaders: Maps ``name:version`` to the loader callable.
        _meta: Maps ``name:version`` to metadata dict (version string,
            load time, last_latency_ms, error_count).
    """

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    def register(self, name: str, loader_fn: Callable[[], Any], version: str = "latest") -> None:
        key = f"{name}:{version}"
        self._loaders[key] = loader_fn
        self._meta[key] = {"name": name, "version": version, "loaded": False,
                            "last_latency_ms": None, "error_count": 0}
        logger.info("model registered", extra={"model_name": name, "model_version": version})

    def get(self, name: str, version: str = "latest") -> Any:
        key = f"{name}:{version}"
        if key not in self._loaders:
            raise KeyError(f"Model '{key}' is not registered")
        if key not in self._models:
            self._models[key] = self._loaders[key]()
            self._meta[key]["loaded"] = True
        return self._models[key]

    def list_models(self) -> list[dict[str, Any]]:
        return list(self._meta.values())

    def update_stats(self, name: str, version: str, latency_ms: float, *, error: bool = False) -> None:
        key = f"{name}:{version}"
        if key not in self._meta:
            return
        self._meta[key]["last_latency_ms"] = latency_ms
        if error:
            self._meta[key]["error_count"] += 1

_registry: ModelRegistry | None = None

def get_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry
```

### 4.3 Lazy model loader: AFTER

```python
# app/ml/loader.py (excerpt)
def load_model(path_or_url: str) -> Any:
    """Load a model from a local path or HTTP URL.

    Dispatch is based on file extension:
    * ``.pt`` / ``.pth``  → ``torch.load``
    * ``.onnx``           → ``onnxruntime.InferenceSession``
    * ``.pkl`` / ``.joblib`` → ``joblib.load``
    * anything else       → ``joblib.load`` (generic pickle fallback)

    All ML framework imports are lazy — this function is the ONLY place
    they are imported.
    """
    resolved_path = _resolve_path(path_or_url)
    ext = Path(resolved_path).suffix.lower()
    if ext in (".pt", ".pth"):
        return _load_torch(resolved_path)
    if ext == ".onnx":
        return _load_onnx(resolved_path)
    return _load_joblib(resolved_path)


def _load_torch(path: str) -> Any:
    import torch  # lazy — not at module level
    model = torch.load(path, map_location="cpu", weights_only=True)
    logger.info("torch model loaded", extra={"path": path})
    return model
```

### 4.4 Async Predictor with timeout: AFTER

```python
# app/ml/predictor.py (excerpt)
class Predictor:
    async def predict(self, input_data: Any) -> tuple[Any, float]:
        return await asyncio.wait_for(
            self._predict_inner(input_data),
            timeout=self.timeout_ms / 1000.0,
        )

    async def _predict_inner(self, input_data: Any) -> tuple[Any, float]:
        t0 = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            output = await loop.run_in_executor(None, self._call_model, input_data)
            latency_ms = (time.monotonic() - t0) * 1000.0
            self.registry.update_stats(self.model_name, self.model_version, latency_ms)
            return output, latency_ms
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000.0
            self.registry.update_stats(self.model_name, self.model_version, latency_ms, error=True)
            raise

    def _call_model(self, input_data: Any) -> Any:
        model = self.registry.get(self.model_name, self.model_version)
        if hasattr(model, "predict"):
            return model.predict(input_data)
        return model(input_data)
```

### 4.5 HTTP routes: AFTER

```python
# app/api/routes/ml.py (excerpt)
router = APIRouter(prefix="/ml", tags=["ml"])

@router.post("/predict", response_model=PredictionResponse, status_code=200)
async def predict(req: PredictionRequest, current_user: CurrentUser) -> PredictionResponse:
    """Run a single model prediction."""
    predictor = _get_predictor(req.model_name, req.model_version)
    try:
        output, latency_ms = await predictor.predict(req.input)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail={"detail": "Prediction timed out"})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"detail": str(exc)})
    return PredictionResponse(output=output, model_name=req.model_name,
                              model_version=req.model_version, latency_ms=latency_ms)

@router.post("/predict/batch", response_model=BatchPredictionResponse, status_code=200)
async def predict_batch(req: BatchPredictionRequest, current_user: CurrentUser) -> BatchPredictionResponse:
    """Run batch predictions (respects ML_MAX_BATCH_SIZE)."""
    if len(req.inputs) > settings.ML_MAX_BATCH_SIZE:
        raise HTTPException(status_code=422,
            detail={"detail": f"Batch size {len(req.inputs)} exceeds limit {settings.ML_MAX_BATCH_SIZE}"})
    predictor = _get_predictor(req.model_name, req.model_version)
    outputs, latency_ms = await predictor.predict_batch(req.inputs, max_batch_size=settings.ML_MAX_BATCH_SIZE)
    return BatchPredictionResponse(outputs=outputs, model_name=req.model_name,
                                   model_version=req.model_version, latency_ms=latency_ms, count=len(outputs))

@router.get("/models", response_model=ModelListResponse, status_code=200)
async def list_models(current_user: CurrentUser) -> ModelListResponse:
    """List all registered models with metadata."""
    registry = get_registry()
    models = [ModelInfo(**m) for m in registry.list_models()]
    return ModelListResponse(data=models, count=len(models))

@router.get("/models/{name}/health", status_code=200)
async def model_health(name: str, current_user: CurrentUser) -> dict:
    """Return health info for a specific model."""
    registry = get_registry()
    meta = next((m for m in registry.list_models() if m["name"] == name), None)
    if meta is None:
        raise HTTPException(status_code=404, detail={"detail": f"Model '{name}' is not registered."})
    return {"name": meta["name"], "loaded": meta.get("loaded", False),
            "last_latency_ms": meta.get("last_latency_ms"),
            "error_count": meta.get("error_count", 0)}
```

### 4.6 Config patch (settings injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- ML model server settings — added by add_ml_model_server tool ---
    ML_MODEL_DIR: str = "/models"
    ML_DEFAULT_MODEL: str = "default"
    ML_MAX_BATCH_SIZE: int = 32
    ML_PREDICTION_TIMEOUT_MS: int = 5000
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

### 4.7 `app/ml/__init__.py` re-exports: AFTER

```python
# app/ml/__init__.py
from app.ml.loader import load_model
from app.ml.predictor import Predictor
from app.ml.registry import ModelRegistry, get_registry

__all__ = ["ModelRegistry", "Predictor", "get_registry", "load_model"]
```

### 4.8 Typical caller usage (after install)

```python
# app/main.py  (lifespan wired by _patch_main)
from app.ml.registry import get_registry
# ...
@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = get_registry()
    registry.register("my_model", lambda: load_model("/models/classifier.pkl"))
    yield
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_ml_model_server` checks `"ModelRegistry" in app/ml/registry.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | Returns success+notes before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | Validation loop at end: `ast.parse` on each created `.py` file; returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers in registry, loader, predictor, routes kept small by construction; asserted by AST walk in test harness |
| QS-5 | **All ML framework imports are lazy** | `torch`, `sklearn`, `onnxruntime`, `numpy`, `tensorflow`, `joblib` appear only inside function bodies in `loader.py` — never at module top-level |
| QS-6 | **`Predictor` uses `asyncio.wait_for` for timeout** | `predict()` wraps `_predict_inner` in `asyncio.wait_for(timeout=self.timeout_ms / 1000.0)` |
| QS-7 | **Batch endpoint enforces `ML_MAX_BATCH_SIZE`** | Route handler checks `len(req.inputs) > settings.ML_MAX_BATCH_SIZE` → 422 |
| QS-8 | **`ML_*` settings live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-9 | **Model health endpoint tracks `error_count`** | `model_health` returns `error_count` from registry metadata |
| QS-10 | **`get_registry` singleton** | Process-wide singleton via module-level `_registry` variable; no per-request allocation |
| QS-11 | **HTTP routes require authentication** | `POST /predict`, `POST /predict/batch`, `GET /models`, `GET /models/{name}/health` all declare `current_user: CurrentUser` |
| QS-12 | **`app/ml/__init__.py` re-exports the public API** | Re-exports `ModelRegistry`, `Predictor`, `get_registry`, `load_model` |
| QS-13 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` runs first |
| QS-14 | **`app/main.py` references `get_registry`** | `_patch_main` injects `get_registry` reference into lifespan |
| QS-15 | **Tool records execution time** | `ToolResult.execution_time_ms` set via `_elapsed_ms(start)` on every return path |
| QS-16 | **`next_steps` guides model registration** | `next_steps` list includes `"register"` guidance and env-var instructions |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_ml_model_server.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `ML_MODEL_DIR`, `ML_DEFAULT_MODEL`, `ML_MAX_BATCH_SIZE`, `ML_PREDICTION_TIMEOUT_MS` exist inside `class Settings` with 4-space indent | String scan + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `ml_router` is registered in `app/routes/__init__.py` | `"ml_router" in content` and `"include_router" in content` | T-09 (`test_routes_registered`) |
| CC-10 | `execution_time_ms` is a positive integer | `result.execution_time_ms > 0` | T-10 (`test_execution_time_recorded`) |
| CC-11 | `app/ml/registry.py` exists with `ModelRegistry`, `get_registry`, `register`, `get`, `list_models` | File exists + substring checks | T-11 (`test_ml_registry_created`) |
| CC-12 | `app/ml/loader.py` exists with `load_model` function | File exists + `"def load_model" in content` | T-12 (`test_ml_loader_created`) |
| CC-13 | `app/ml/predictor.py` exists with `Predictor`, `async def predict`, `async def predict_batch` | File exists + substring checks | T-13 (`test_ml_predictor_created`) |
| CC-14 | `app/schemas/ml.py` exists with `PredictionRequest`, `PredictionResponse`, `BatchPredictionRequest`, `BatchPredictionResponse` | File exists + class name checks | T-14 (`test_ml_schemas_created`) |
| CC-15 | `app/api/routes/ml.py` exists with `router.post`, `predict_batch`, `list_models`, `model_health` | File exists + substring checks | T-15 (`test_ml_routes_created`) |
| CC-16 | `app/ml/__init__.py` re-exports `ModelRegistry`, `Predictor`, `get_registry`, `load_model` | File exists + all four symbols present | T-16 (`test_ml_init_re_exports`) |
| CC-17 | `app/main.py` references `get_registry` after tool application | `"get_registry" in main.py content` | T-17 (`test_main_patched`) |
| CC-18 | `next_steps` is non-empty and mentions model registration | `len(result.next_steps) > 0` and `"register" in combined.lower()` | T-18 (`test_next_steps_present`) |
| CC-19 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-19 (`test_idempotent_project_still_parses`) |
| CC-20 | `loader.py` has NO top-level imports of ML libraries (`torch`, `sklearn`, `onnxruntime`, `numpy`, `tensorflow`, `joblib`) | AST walk of `tree.body` for `ast.Import`/`ast.ImportFrom` | T-20 (`test_lazy_imports_in_loader`) |
| CC-21 | `predictor.py` uses `asyncio.wait_for` | `"asyncio.wait_for" in content` | T-21 (`test_predictor_uses_asyncio_wait_for`) |
| CC-22 | Batch route checks `ML_MAX_BATCH_SIZE` | `"ML_MAX_BATCH_SIZE" in routes content` | T-22 (`test_batch_route_checks_max_batch_size`) |
| CC-23 | Health endpoint references `error_count` | `"error_count" in routes content` | T-23 (`test_model_health_returns_error_count`) |
| CC-24 | `registry.py` has `update_stats` method | `"def update_stats" in registry content` | T-24 (`test_registry_update_stats_method`) |

---

## 7. Definition of Done (DoD)

- [ ] All 24 Completeness Criteria verified by `test_add_ml_model_server.py`
- [ ] `add_ml_model_server.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_ml_model_server.py` detects `"ModelRegistry"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `loader.py` has zero top-level ML framework imports — lazy everywhere
- [ ] `predictor.py` uses `asyncio.wait_for` for timeout enforcement
- [ ] `predict_batch` route enforces `ML_MAX_BATCH_SIZE` → HTTP 422
- [ ] `model_health` endpoint returns `error_count` from registry metadata
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `app/ml/__init__.py` re-exports all four public symbols
- [ ] `next_steps` includes model registration guidance and env-var instructions
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-MMS-01 | Tool is ALWAYS idempotent on second invocation | Fingerprint check `"ModelRegistry" in registry_file.read_text()` short-circuits to `status="no_op"` | T-02, T-19 |
| INV-MMS-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-MMS-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: ast.parse(p)` | T-06, T-19 |
| INV-MMS-04 | ML framework imports MUST be lazy — never at module top-level in `loader.py` | AST walk of `loader.py`'s `tree.body` checks for `torch`, `sklearn`, `onnxruntime`, `numpy`, `tensorflow`, `joblib` at module scope | T-20 |
| INV-MMS-05 | `asyncio.wait_for` MUST be used in `Predictor.predict` for timeout enforcement | `"asyncio.wait_for" in predictor.py content` | T-21 |
| INV-MMS-06 | Batch endpoint MUST enforce `ML_MAX_BATCH_SIZE` | Route checks `len(req.inputs) > settings.ML_MAX_BATCH_SIZE` → 422 | T-22 |
| INV-MMS-07 | `ML_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-MMS-08 | HTTP inference routes MUST require authentication | `POST /predict`, `POST /predict/batch`, `GET /models`, `GET /models/{name}/health` all declare `current_user: CurrentUser` | T-15 |
| INV-MMS-09 | `ModelRegistry` MUST track `error_count` per model | `update_stats(error=True)` increments `_meta[key]["error_count"]` | T-24 |
| INV-MMS-10 | `app/ml/__init__.py` MUST re-export all four public symbols | `ModelRegistry`, `Predictor`, `get_registry`, `load_model` in `__all__` | T-16 |
| INV-MMS-11 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-10 |
| INV-MMS-12 | `next_steps` MUST reference model registration so operators know post-install steps | Contains `"register"` token | T-18 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install ML inference into a clean FastAPI project**
- **As a** backend engineer who needs to serve ML models
- **I want** to run one tool call and get a complete inference layer
- **So that** I do not hand-roll model loading and HTTP routes
- **Given:** A FastAPI project with `app/core/config.py`, `app/routes/__init__.py`, `requirements.txt`
- **When:** `add_ml_model_server(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-MMS-01)
  - `files_created` contains ≥ 6 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/ml/registry.py` already contains `ModelRegistry`
- **When:** `add_ml_model_server(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-MMS-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-MMS-03)
  - Verified by T-02, T-19

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_ml_model_server(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-MMS-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `registry.py`, `loader.py`, `predictor.py`, `schemas/ml.py`, `routes/ml.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: FastAPI boots without ML libraries**
- **As a** CI container that has no torch installed
- **I want** the FastAPI app to import and start without ImportError
- **So that** I can run tests in a lightweight environment
- **Given:** `loader.py`, `predictor.py`, `registry.py` generated
- **When:** Python imports `app.ml`
- **Then:**
  - No `import torch` / `import onnxruntime` at module level
  - No `ImportError` at startup
  - Verified by T-20 (INV-MMS-04)

### 9.2 ModelRegistry (US-06 .. US-10)

**US-06: Register a model at startup**
- **As a** FastAPI lifespan hook
- **I want** `registry.register("my_model", loader_fn)` to cache the loader
- **So that** the model is loaded once and reused for all requests
- **Given:** `get_registry()` returns the singleton
- **When:** Lifespan calls `register("resnet50", lambda: load_model("/models/resnet50.pt"))`
- **Then:**
  - `_loaders["resnet50:latest"]` is set
  - First call to `get("resnet50")` invokes the loader and caches result
  - Verified by T-11

**US-07: Look up a model by name**
- **As a** route handler
- **I want** `registry.get("my_model")` to return the cached model object
- **So that** inference runs without disk I/O
- **Given:** Model registered via `register()`
- **When:** Route calls `registry.get("my_model")`
- **Then:**
  - Returns cached model instance
  - `KeyError` if name not registered
  - Verified by T-11

**US-08: List all models with health metadata**
- **As an** operator dashboard
- **I want** `GET /ml/models` to return all models with latency and error counts
- **So that** I can see model health at a glance
- **Given:** Multiple models registered
- **When:** `GET /ml/models` with auth
- **Then:**
  - Returns `ModelListResponse` with `data` and `count`
  - Each entry has `name`, `version`, `loaded`, `last_latency_ms`, `error_count`
  - Verified by T-15

**US-09: Track prediction errors per model**
- **As a** model operator
- **I want** `error_count` to increment each time a prediction raises
- **So that** I can detect degraded models before they affect SLOs
- **Given:** `Predictor._predict_inner` catches exceptions
- **When:** Model raises during `_call_model`
- **Then:**
  - `update_stats(error=True)` called
  - `_meta[key]["error_count"]` incremented
  - Visible in `GET /ml/models/{name}/health`
  - Verified by T-23, T-24

**US-10: Update latency stats on every prediction**
- **As an** SLO monitor
- **I want** `last_latency_ms` updated per successful prediction
- **So that** I can alert when inference slows
- **Given:** `Predictor._predict_inner` times the executor call
- **When:** Prediction completes successfully
- **Then:**
  - `update_stats(latency_ms=...)` called without `error=True`
  - `_meta[key]["last_latency_ms"]` = wall-clock time
  - Verified by T-11, T-24

### 9.3 HTTP inference routes (US-11 .. US-15)

**US-11: Single prediction via POST**
- **As a** client application
- **I want** `POST /ml/predict` with `{"input": [...], "model_name": "my_model"}`
- **So that** I get a prediction in a single HTTP call
- **Given:** Model registered and `app/main.py` lifespan active
- **When:** Authenticated POST to `/ml/predict`
- **Then:**
  - Returns `PredictionResponse` with `output`, `model_name`, `model_version`, `latency_ms`
  - 404 if model not registered
  - 504 on timeout
  - Verified by T-15

**US-12: Batch prediction with size guard**
- **As a** client doing bulk inference
- **I want** `POST /ml/predict/batch` with `{"inputs": [...], "model_name": "my_model"}`
- **So that** I process many items in one call
- **Given:** `ML_MAX_BATCH_SIZE` configured in settings
- **When:** Batch size exceeds the limit
- **Then:**
  - Returns HTTP 422 `"Batch size N exceeds limit M"`
  - Otherwise returns `BatchPredictionResponse` with all outputs
  - Verified by T-15, T-22 (INV-MMS-06)

**US-13: Prediction timeout enforcement**
- **As a** resilient service
- **I want** predictions that take too long to be cancelled
- **So that** a slow model does not hold worker connections indefinitely
- **Given:** `ML_PREDICTION_TIMEOUT_MS` in settings
- **When:** Model inference exceeds the timeout
- **Then:**
  - `asyncio.wait_for` raises `asyncio.TimeoutError`
  - Route returns HTTP 504
  - Verified by T-21 (INV-MMS-05)

**US-14: Model health check endpoint**
- **As an** operator
- **I want** `GET /ml/models/{name}/health`
- **So that** I can check if a model is loaded and healthy
- **Given:** Model registered and optionally loaded
- **When:** `GET /ml/models/my_model/health` with auth
- **Then:**
  - Returns `{"name", "loaded", "last_latency_ms", "error_count", "status"}`
  - 404 if not registered
  - Verified by T-15, T-23

**US-15: Unauthenticated inference is denied**
- **As a** security reviewer
- **I want** no anonymous access to inference endpoints
- **So that** model outputs are not accessible without credentials
- **Given:** Routes declare `current_user: CurrentUser`
- **When:** Anonymous request hits `/ml/predict`
- **Then:**
  - FastAPI DI resolves `CurrentUser`, missing auth → 401
  - Verified by route signature (INV-MMS-08)

### 9.4 Model loader (US-16 .. US-20)

**US-16: Load a PyTorch model**
- **As a** developer using PyTorch
- **I want** `load_model("/models/resnet50.pt")` to return the torch object
- **So that** I do not write the loading boilerplate
- **Given:** `.pt` extension detected
- **When:** `load_model` called
- **Then:**
  - `torch.load(path, map_location="cpu", weights_only=True)` called lazily
  - No `import torch` at module level
  - Verified by T-12, T-20

**US-17: Load a scikit-learn model**
- **As a** developer using sklearn
- **I want** `load_model("/models/classifier.pkl")` to return the sklearn pipeline
- **So that** I have a consistent loading interface
- **Given:** `.pkl` or `.joblib` extension
- **When:** `load_model` called
- **Then:**
  - `joblib.load(path)` called lazily
  - Verified by T-12, T-20

**US-18: Load an ONNX model**
- **As a** developer using ONNX runtime
- **I want** `load_model("/models/model.onnx")` to return an `InferenceSession`
- **So that** I can serve cross-framework models
- **Given:** `.onnx` extension
- **When:** `load_model` called
- **Then:**
  - `onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])` called lazily
  - Verified by T-12, T-20

**US-19: Load a model from a URL**
- **As a** developer who stores models in object storage
- **I want** `load_model("https://bucket.s3.amazonaws.com/model.pkl")` to work
- **So that** I do not need to pre-download models at build time
- **Given:** HTTP/HTTPS URL
- **When:** `load_model` called
- **Then:**
  - `_resolve_path` downloads to a temp file via `urllib.request.urlretrieve`
  - Extension-based dispatch runs on the temp file
  - Verified by T-12

**US-20: `Predictor` supports both sklearn and torch conventions**
- **As a** developer using different model interfaces
- **I want** `Predictor` to call `model.predict(input)` or `model(input)` depending on availability
- **So that** I do not need separate predictor classes per framework
- **Given:** Model has `predict` attribute (sklearn) or is callable (torch)
- **When:** `_call_model` runs
- **Then:**
  - `hasattr(model, "predict")` branch takes sklearn convention
  - Else falls back to `model(input_data)` (torch/callable)
  - Verified by T-13

### 9.5 Config, schemas, and operator experience (US-21 .. US-25)

**US-21: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `ML_MAX_BATCH_SIZE=64` in `.env` to take effect without code changes
- **So that** I can tune per-deployment
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `ML_*` fields inside `class Settings` pick up env vars (INV-MMS-07)
  - Anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
  - Verified by T-08

**US-22: Pydantic schemas capture all prediction fields**
- **As a** frontend developer
- **I want** typed request/response schemas
- **So that** I can generate a client SDK from the OpenAPI spec
- **Given:** `app/schemas/ml.py` generated
- **When:** I inspect the schema
- **Then:**
  - `PredictionRequest`: `input`, `model_name`, `model_version`
  - `PredictionResponse`: `output`, `model_name`, `model_version`, `latency_ms`
  - `BatchPredictionRequest`: `inputs`, `model_name`, `model_version`
  - `BatchPredictionResponse`: `outputs`, `model_name`, `model_version`, `latency_ms`, `count`
  - Verified by T-14

**US-23: `app/ml` package provides a clean public API**
- **As a** developer importing from the package
- **I want** `from app.ml import ModelRegistry, Predictor, load_model, get_registry`
- **So that** I do not need to know the internal module structure
- **Given:** `app/ml/__init__.py` re-exports all public symbols
- **When:** Python resolves the import
- **Then:**
  - All four symbols available at `app.ml` package level
  - Verified by T-16 (INV-MMS-10)

**US-24: Operator knows post-install steps**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include model registration guidance
- **So that** I know exactly what to do to serve my first model
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Mentions `registry.register` or `get_registry`
  - Contains env-var configuration instructions
  - Verified by T-18 (INV-MMS-12)

**US-25: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-MMS-11)
  - Verified by T-10

---

## 10. Test Plan

All 24 tests live in `adapt/extend/infrastructure/test_add_ml_model_server.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `ml_t01` | `add_ml_model_server(ToolInput(project_dir))` | `result.status == "success"` (INV-MMS-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `ml_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-MMS-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `ml_t03`; snapshot all `.py` | `add_ml_model_server(ToolInput(dry_run=True))` | `status == "success"`; empty lists; byte-identical filesystem (INV-MMS-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `ml_t04` | Run tool | `len(files_created) >= 6`; every path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `ml_t05` | Run tool | `len(files_modified) >= 2`; every path exists (CC-05) |
| T-06 | `test_all_py_parse` | Fixture `ml_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-MMS-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `ml_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `ml_t08`; run tool | Read `app/core/config.py` | Contains all 4 `ML_*` fields; `ML_MODEL_DIR` line starts with 4-space indent (INV-MMS-07, CC-08) |
| T-09 | `test_routes_registered` | Fixture `ml_t09`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"ml_router"` and `"include_router"` (CC-09) |
| T-10 | `test_execution_time_recorded` | Fixture `ml_t10`; run tool | Read `result.execution_time_ms` | `> 0` (INV-MMS-11, CC-10) |

### 10.2 Category B — Generated code quality (T-11 .. T-11, cross-reference)

See Category A rows T-06, T-07, T-08.

### 10.3 Category C — Domain-specific modules (T-11 .. T-24)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_ml_registry_created` | Fixture `ml_t11`; run tool | Read `app/ml/registry.py` | Exists; contains `class ModelRegistry`, `def get_registry`, `def register`, `def get`, `def list_models` (INV-MMS-09, CC-11) |
| T-12 | `test_ml_loader_created` | Fixture `ml_t12`; run tool | Read `app/ml/loader.py` | Exists; contains `def load_model` (CC-12) |
| T-13 | `test_ml_predictor_created` | Fixture `ml_t13`; run tool | Read `app/ml/predictor.py` | Exists; contains `class Predictor`, `async def predict`, `async def predict_batch` (CC-13) |
| T-14 | `test_ml_schemas_created` | Fixture `ml_t14`; run tool | Read `app/schemas/ml.py` | Exists; contains `PredictionRequest`, `PredictionResponse`, `BatchPredictionRequest`, `BatchPredictionResponse` (CC-14) |
| T-15 | `test_ml_routes_created` | Fixture `ml_t15`; run tool | Read `app/api/routes/ml.py` | Exists; contains `router.post` or `POST /ml/predict`, `predict_batch`, `list_models`, `model_health` (CC-15) |
| T-16 | `test_ml_init_re_exports` | Fixture `ml_t16`; run tool | Read `app/ml/__init__.py` | Exists; contains `ModelRegistry`, `Predictor`, `get_registry`, `load_model` (INV-MMS-10, CC-16) |
| T-17 | `test_main_patched` | Fixture `ml_t17`; run tool | Read `app/main.py` | Contains `"get_registry"` (CC-17) |
| T-18 | `test_next_steps_present` | Fixture `ml_t18`; run tool | Read `result.next_steps` | Non-empty; `"register" in combined.lower()` (INV-MMS-12, CC-18) |
| T-19 | `test_idempotent_project_still_parses` | Fixture `ml_t19`; run twice | AST-parse every `.py` | No `SyntaxError` (INV-MMS-01, INV-MMS-03, CC-19) |
| T-20 | `test_lazy_imports_in_loader` | Fixture `ml_t20`; run tool | AST-walk `tree.body` of `loader.py` | No ML lib in top-level `ast.Import`/`ast.ImportFrom` (INV-MMS-04, CC-20) |
| T-21 | `test_predictor_uses_asyncio_wait_for` | Fixture `ml_t21`; run tool | Read `app/ml/predictor.py` | `"asyncio.wait_for" in content` (INV-MMS-05, CC-21) |
| T-22 | `test_batch_route_checks_max_batch_size` | Fixture `ml_t22`; run tool | Read `app/api/routes/ml.py` | `"ML_MAX_BATCH_SIZE" in content` (INV-MMS-06, CC-22) |
| T-23 | `test_model_health_returns_error_count` | Fixture `ml_t23`; run tool | Read `app/api/routes/ml.py` | `"error_count" in content` (CC-23) |
| T-24 | `test_registry_update_stats_method` | Fixture `ml_t24`; run tool | Read `app/ml/registry.py` | `"def update_stats" in content` (INV-MMS-09, CC-24) |

### 10.4 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_ml_model_server.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_ml_model_server.py
```

Target: 24/24 passed, 0 failed. The standalone runner prints `TOOL-068 STRUCTURAL: 24/24 passed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_ml_gpu_inference` (TOOL-069) | Yes | Compatible — TOOL-068 runs FIRST | TOOL-069 upgrades the `app/ml/` package with `app/ml/gpu/` sub-package; `GPUPredictor` wraps the model objects loaded by `load_model` |
| `add_ml_model_registry` (TOOL-070) | No | Compatible | TOOL-070 adds a DB-backed registry for artefact metadata; TOOL-068's in-process `ModelRegistry` singleton is the runtime serving layer — the two are complementary |
| `add_cache_layer` (TOOL-021) | No | Compatible | Result caching via the cache layer can wrap inference outputs for repeated inputs; cache key should include `model_name`, `model_version`, and a hash of `input` |
| `add_arq_worker` (TOOL-053) | No | Compatible | Long-running batch inference jobs can be offloaded to the arq worker; worker tasks call `get_registry().get("model")` directly |
| `add_circuit_breaker` (TOOL-022) | No | Compatible | `Predictor._call_model` calls can be wrapped in the breaker to handle flaky models or resource exhaustion |
| `add_rate_limiting` (TOOL-057) | No | Compatible | `POST /ml/predict` should be rate-limited per user to prevent inference abuse; `ML_MAX_BATCH_SIZE` is a complementary guard |
| `add_api_key_auth` (TOOL-010) | No | Compatible | API keys work as `CurrentUser` identities for inference endpoints |
| `add_oauth2_provider` (TOOL-011) | No | Compatible | OAuth2 JWTs work via the same `CurrentUser` dependency |
| `add_audit_log` (TOOL-005) | No | Caution | Audit logging of model predictions may inadvertently log PII in `input`/`output`; scrub before persisting |
| `add_event_driven` (TOOL-046) | No | Compatible | `prediction.completed` / `prediction.failed` events can be emitted from `Predictor._predict_inner` for async consumers |

**Conflicts:** None. TOOL-068 is the CPU-path runtime serving layer; TOOL-069 extends it to GPU; TOOL-070 adds DB-backed metadata management.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/routes/__init__.py \
  app/main.py

rm -rf app/ml/
rm -f app/schemas/ml.py
rm -f app/api/routes/ml.py
```

### 12.2 No database rollback required

TOOL-068 creates no database tables or migrations. Rollback is a pure filesystem operation.

### 12.3 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

Because the ast.parse validation loop runs **at the end** of the success path, a mid-execution failure may leave partially-written files. Revert modified paths and delete created paths to restore.

### 12.4 Uninstall validator

```bash
test ! -d app/ml || (echo "app/ml still present" && exit 1)
test ! -f app/schemas/ml.py || (echo "ml schemas still present" && exit 1)
grep -q "ML_MODEL_DIR" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing a prerequisite | `ensure_prerequisites` returns errors → `status="error"` with list of missing prereqs |
| EC-03 | `app/ml/registry.py` already contains `ModelRegistry` | Early return `status="no_op"` with single note — zero file writes |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded |
| EC-05 | `app/core/config.py` already contains `ML_MODEL_DIR` | `_patch_config` early-returns; no duplicate block appended |
| EC-06 | `app/core/config.py` lacks `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; last resort appends at EOF |
| EC-07 | `app/routes/__init__.py` missing | Routes patch step is skipped; developer must wire the router manually |
| EC-08 | `app/main.py` missing or already contains `get_registry` | `_patch_main` conditional — skipped or returns False without corruption |
| EC-09 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `ml.py` |
| EC-10 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing routes |
| EC-11 | Generated `predictor.py` fails `ast.parse` | Validation loop returns `status="error"` with file path and `SyntaxError` detail |
| EC-12 | Model registered with same name twice | `_loaders` and `_meta` keys overwritten silently (dict assignment) |
| EC-13 | Batch request with `inputs=[]` (empty list) | `predict_batch` loop has zero iterations; returns empty `outputs` list with `latency_ms` |
| EC-14 | `load_model` given an unsupported extension | Falls through to `_load_joblib` (generic pickle fallback) |
| EC-15 | `load_model` given an HTTP URL with no file extension | `suffix = ""` → `_load_joblib` with `.bin` temp file |
| EC-16 | `ML_MAX_BATCH_SIZE` set to 0 in env | Every non-empty batch → 422; single predictions unaffected |
| EC-17 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-19) |
| EC-18 | `app/routes/__init__.py` already contains ml router import | `_register_router` early-returns; no duplicate `include_router` call |

---

## 14. Acceptance Criteria (Final Sign-off)

1. All 24 Completeness Criteria verified via `test_add_ml_model_server.py` passing
2. `test_add_ml_model_server.py` reports `24/24 passed` via both pytest and standalone runner
3. Tool execution time < 5 s measured on reference hardware
4. Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-MMS-01)
5. `dry_run=True` produces zero filesystem writes (INV-MMS-02)
6. Every generated `.py` file AST-parses cleanly on first and second runs (INV-MMS-03)
7. No generated function in `app/` exceeds 50 LOC (QS-4)
8. `ML_*` settings live inside `class Settings` body with 4-space indentation (INV-MMS-07)
9. `loader.py` has zero top-level ML framework imports (INV-MMS-04)
10. `predictor.py` uses `asyncio.wait_for` for timeout enforcement (INV-MMS-05)
11. Batch endpoint enforces `ML_MAX_BATCH_SIZE` → 422 (INV-MMS-06)
12. All four HTTP routes declare `current_user: CurrentUser` (INV-MMS-08)
13. `app/ml/__init__.py` re-exports all four public symbols (INV-MMS-10)
14. `next_steps` includes model registration guidance (INV-MMS-12)
15. Developer successfully registers a model in lifespan, calls `POST /ml/predict`, and receives a `PredictionResponse`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` passes with auto-scaffold
- [ ] `app/ml/registry.py` does NOT contain `"ModelRegistry"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 `app/ml/` package

- [ ] `mkdir -p app/ml`
- [ ] Write `app/ml/__init__.py` if missing: re-exports `load_model`, `Predictor`, `ModelRegistry`, `get_registry`
- [ ] Write `app/ml/registry.py` via `_ML_REGISTRY_PY`: `ModelRegistry` class, `get_registry` singleton
- [ ] Write `app/ml/loader.py` via `_ML_LOADER_PY`: `load_model`, `_resolve_path`, `_load_torch`, `_load_onnx`, `_load_joblib` — all ML imports lazy
- [ ] Write `app/ml/predictor.py` via `_ML_PREDICTOR_PY`: `Predictor` class, `predict`, `predict_batch`, `_predict_inner`, `_call_model` — uses `asyncio.wait_for`

### 15.3 Schemas

- [ ] `mkdir -p app/schemas` if missing
- [ ] Write `app/schemas/ml.py` via `_ML_SCHEMAS_PY`: `PredictionRequest`, `PredictionResponse`, `BatchPredictionRequest`, `BatchPredictionResponse`, `ModelInfo`, `ModelListResponse`
- [ ] All fields use `pydantic.Field` with descriptions

### 15.4 HTTP routes

- [ ] `mkdir -p app/api/routes` if missing
- [ ] Write `app/api/routes/ml.py` via `_ML_ROUTES_PY`: `APIRouter(prefix="/ml", tags=["ml"])`
- [ ] `_get_predictor(model_name, model_version)` raises 404 if not in registry
- [ ] `predict`: timeout → 504; not found → 404; generic → 500
- [ ] `predict_batch`: size check → 422; timeout → 504; generic → 500
- [ ] `list_models`: returns `ModelListResponse`
- [ ] `model_health`: returns dict with `error_count`; 404 if not registered
- [ ] All four endpoints declare `current_user: CurrentUser`

### 15.5 Config patch

- [ ] Early-return if `"ML_MODEL_DIR" in src`
- [ ] Block emits `ML_MODEL_DIR`, `ML_DEFAULT_MODEL`, `ML_MAX_BATCH_SIZE`, `ML_PREDICTION_TIMEOUT_MS`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.6 Routes init patch

- [ ] Early-return if import line already present
- [ ] Insert `from app.api.routes.ml import router as ml_router` after last `from app.` import
- [ ] Insert `api_router.include_router(ml_router)` after last `include_router` call
- [ ] Preserve trailing newline

### 15.7 Main patch

- [ ] If `app/main.py` exists: inject `get_registry` reference into lifespan
- [ ] Conditional — no-op if already present

### 15.8 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `status="error"` with file path on `SyntaxError`

### 15.9 Result assembly

- [ ] `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe lazy imports, ModelRegistry singleton, batch size guard, health endpoint
- [ ] `next_steps` include `registry.register` example, env-var setup, restart hint, verification steps

### 15.10 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and lazy-import rationale
- [ ] `add_ml_model_server` docstring documents args and return type

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/ml/__init__.py",
    "/tmp/fixture/app/ml/registry.py",
    "/tmp/fixture/app/ml/loader.py",
    "/tmp/fixture/app/ml/predictor.py",
    "/tmp/fixture/app/schemas/ml.py",
    "/tmp/fixture/app/api/routes/ml.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py",
    "/tmp/fixture/app/main.py"
  ],
  "notes": [
    "ML model server added: ModelRegistry singleton, lazy loader, Predictor,",
    "PredictionRequest/PredictionResponse schemas, and 4 HTTP routes.",
    "All ML framework imports (torch, sklearn, onnxruntime, numpy, tensorflow) are lazy.",
    "app.main boots without any ML library installed.",
    "Model health endpoint tracks last_latency_ms and error_count per model.",
    "Batch prediction respects ML_MAX_BATCH_SIZE from settings."
  ],
  "next_steps": [
    "Register your model loader in app/main.py lifespan:",
    "  from app.ml.registry import get_registry",
    "  from app.ml.loader import load_model",
    "  registry = get_registry()",
    "  registry.register('my_model', lambda: load_model('/path/to/model.pkl'))",
    "Set ML_MODEL_DIR, ML_DEFAULT_MODEL, ML_MAX_BATCH_SIZE, ML_PREDICTION_TIMEOUT_MS in .env.",
    "Restart the FastAPI app so the /ml/* routes are active.",
    "Verify: POST /predict with {\"input\": [...], \"model_name\": \"my_model\"}"
  ],
  "execution_time_ms": 118
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "ModelRegistry already present — ML model server already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 2
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/ml/ package (registry.py, loader.py, predictor.py),",
    "         app/schemas/ml.py (PredictionRequest, PredictionResponse),",
    "         app/api/routes/ml.py (POST /predict, POST /predict/batch,",
    "           GET /models, GET /models/{name}/health).",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 2
}
```

---
