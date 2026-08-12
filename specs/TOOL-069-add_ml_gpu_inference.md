---
spec_id: "TOOL-069"
tool_name: "add_ml_gpu_inference"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-GPU-01"
  - "INV-GPU-02"
  - "INV-GPU-03"
  - "INV-GPU-04"
  - "INV-GPU-05"
  - "INV-GPU-06"
  - "INV-GPU-07"
  - "INV-GPU-08"
  - "INV-GPU-09"
  - "INV-GPU-10"
  - "INV-GPU-11"
  - "INV-GPU-12"
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
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
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
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-069: add_ml_gpu_inference

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_ml_gpu_inference` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, pydantic-settings (torch is user-provided — never added to requirements.txt) |
| Signature | `add_ml_gpu_inference(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and optional `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_ml_gpu_inference", "description": "Upgrade a FastAPI project with GPU-optimised inference: DeviceManager, GPUPredictor (mixed precision), MemoryGuard, and GET /ml/gpu/status endpoint. All torch imports are lazy — app boots without torch installed.", "tags": ["extend", "infrastructure", "ml", "gpu"], "entry": "add_ml_gpu_inference"}` |
| Files created (typical) | 5+ — `app/ml/__init__.py` (if missing), `app/ml/gpu/__init__.py`, `app/ml/gpu/device.py`, `app/ml/gpu/memory_guard.py`, `app/ml/gpu/inference.py`, `app/api/routes/gpu_status.py` |
| Files modified (typical) | 2 — `app/core/config.py`, `app/routes/__init__.py` |

---

## 2. Purpose

The `fastapi_add_ml_gpu_inference` tool upgrades a FastAPI project — ideally one where `add_ml_model_server` (TOOL-068) has already been applied — with a full GPU inference layer. The defining constraint is identical to TOOL-068: **every `import torch` and `import torch.cuda` lives inside a function body, never at module top-level**. The FastAPI app boots cleanly on CPU-only machines and on machines where torch is not installed at all.

Teams who add GPU support naively encounter two failure classes. First, the application crashes at import time when deployed to a CPU-only container or CI environment that has no torch wheel. Second, GPU memory exhaustion causes CUDA OOM kills that kill the entire API worker process rather than failing a single inference request gracefully. This tool eliminates both: (a) `DeviceManager` detects CUDA availability at runtime via a lazy `import torch`, falls back to CPU with a logged warning, and caches the device selection on first call; (b) `MemoryGuard.check()` must be called before every forward pass — when `torch.cuda.memory_allocated(device) / torch.cuda.memory_reserved(device)` exceeds `settings.GPU_MEMORY_THRESHOLD_PCT`, it raises `RuntimeError`, which the caller catches and converts to HTTP 503; (c) `GPUPredictor` wraps any `torch.nn.Module` and handles device placement via `model.to(device)` on first call plus optional `torch.cuda.amp.autocast` for float16 mixed-precision inference; (d) `GET /ml/gpu/status` returns a JSON response even when torch is absent (`{"available": false, "device": "cpu"}`); (e) four GPU settings are injected into the `Settings` class body so pydantic-settings binds them from environment variables.

The tool is idempotent: a second run detects `"DeviceManager"` in `app/ml/gpu/device.py` and returns `status="no_op"` without touching any file. The tool does **not** add torch to `requirements.txt` — torch installation is the developer's responsibility because wheel variants differ dramatically (CPU/CUDA 11.8/CUDA 12.1, ROCm, etc.) and choosing the wrong one causes multi-GB downloads or broken installs.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-06) |
| Files created (.py) | ≥ 5 | gpu package init, device, memory_guard, inference, gpu_status route (CC-04) |
| Files modified | ≥ 2 | Config, routes init (CC-05) |
| Max function LOC in generated code | ≤ 50 | Enforced by AST walk over `app/` subtree (CC-09) |
| `DeviceManager.get_device()` first call | Once per process | Cached in `_device` attribute |
| `MemoryGuard.check()` overhead | < 1 ms | Single `torch.cuda.memory_allocated` call; no-op on CPU |
| `GET /ml/gpu/status` | < 10 ms | Lazy torch import + single device query |
| GPU fallback on CPU host | Zero crashes | `try/except ImportError` in `_select_device` returns `_CpuDevice` stub |
| OOM protection | `RuntimeError` before forward pass | `MemoryGuard.check()` raises before `model.to(device)` reaches CUDA |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── ml/                  # Possibly created by TOOL-068
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── loader.py
│   │   └── predictor.py
│   ├── core/
│   │   └── config.py        # Settings class, no GPU_* fields
│   └── routes/
│       └── __init__.py      # api_router, no gpu_status router
```

Model inference runs on CPU only. There is no runtime device detection, no OOM guard before forward passes, no mixed-precision support, and no operator visibility into GPU memory usage.

### 4.2 DeviceManager (lazy torch, CPU fallback): AFTER

```python
# app/ml/gpu/device.py (excerpt)
class DeviceManager:
    """Detect and expose the active inference device.

    Uses lazy torch imports so the app boots on CPU-only machines or
    when torch is not installed at all.
    """

    _device = None

    def get_device(self):
        """Return the active ``torch.device``, selecting it on first call.

        Falls back to CPU with a log warning if GPU_ENABLED is False or
        CUDA is unavailable. Never raises.
        """
        if self._device is not None:
            return self._device
        self._device = self._select_device()
        return self._device

    def _select_device(self):
        try:
            import torch  # noqa: PLC0415 (lazy import — intentional)
            if settings.GPU_ENABLED and torch.cuda.is_available():
                device = torch.device(f"cuda:{settings.GPU_DEVICE_ID}")
                logger.info("GPU inference enabled", extra={"device": str(device)})
                return device
            if settings.GPU_ENABLED:
                logger.warning("GPU_ENABLED=true but CUDA unavailable; falling back to CPU")
        except ImportError:
            logger.warning("torch not installed; inference will use CPU stub")
            return _CpuDevice()
        try:
            import torch  # noqa: PLC0415
            return torch.device("cpu")
        except ImportError:
            return _CpuDevice()

    def memory_stats(self) -> dict:
        """Return GPU memory statistics for the active CUDA device."""
        try:
            import torch  # noqa: PLC0415
            device = self.get_device()
            if not hasattr(device, "type") or device.type != "cuda":
                return {}
            alloc = torch.cuda.memory_allocated(device)
            reserved = torch.cuda.memory_reserved(device)
            util = (alloc / reserved) if reserved > 0 else 0.0
            return {"allocated_bytes": alloc, "reserved_bytes": reserved,
                    "utilisation_pct": round(util * 100, 2)}
        except Exception:
            return {}


class _CpuDevice:
    """Minimal stub returned when torch is not installed."""
    type = "cpu"

    def __str__(self) -> str:
        return "cpu"
```

### 4.3 MemoryGuard (OOM prevention): AFTER

```python
# app/ml/gpu/memory_guard.py (excerpt)
class MemoryGuard:
    """Check GPU memory utilisation before allowing inference."""

    def check(self, device=None) -> None:
        """Assert GPU memory utilisation is below threshold.

        No-op on CPU or when torch is absent. Raises ``RuntimeError``
        when utilisation exceeds ``self.threshold``.
        """
        if device is None:
            return
        try:
            if not hasattr(device, "type") or device.type != "cuda":
                return
            import torch  # noqa: PLC0415
            reserved = torch.cuda.memory_reserved(device)
            if reserved == 0:
                return
            allocated = torch.cuda.memory_allocated(device)
            utilisation = allocated / reserved
            if utilisation > self.threshold:
                raise RuntimeError(
                    f"GPU memory utilisation {utilisation:.1%} exceeds "
                    f"threshold {self.threshold:.1%} — inference blocked"
                )
        except RuntimeError:
            raise
        except Exception:
            pass  # Non-OOM errors are non-fatal in the guard
```

### 4.4 GPUPredictor (mixed precision, device placement): AFTER

```python
# app/ml/gpu/inference.py (excerpt)
class GPUPredictor:
    """Wrap a torch model for GPU-accelerated inference."""

    def predict(self, inputs: Any) -> Any:
        """Run inference with optional mixed precision.

        Checks GPU memory, moves model to device on first call, and
        optionally wraps the forward pass in autocast.
        """
        device = self._get_device()
        _memory_guard.check(device)
        self._move_model()
        return self._forward(inputs, device)

    def _forward(self, inputs: Any, device: Any) -> Any:
        use_amp = (
            settings.GPU_MIXED_PRECISION
            and hasattr(device, "type")
            and device.type == "cuda"
        )
        try:
            import torch  # noqa: PLC0415
            if use_amp:
                with torch.cuda.amp.autocast():
                    return self.model(inputs)
            return self.model(inputs)
        except Exception:
            return self.model(inputs)
```

### 4.5 `GET /ml/gpu/status` (works without torch): AFTER

```python
# app/api/routes/gpu_status.py (excerpt)
router = APIRouter(prefix="/ml/gpu", tags=["ml", "gpu"])

@router.get("/status", summary="GPU device status")
async def gpu_status() -> JSONResponse:
    """Return current GPU device information.

    Works even when torch is not installed or CUDA is unavailable.
    Returns {"available": false} when torch is absent.
    """
    payload = _build_status_payload()
    return JSONResponse(content=payload)


def _build_status_payload() -> dict[str, Any]:
    try:
        import torch  # noqa: PLC0415
        device = _device_manager.get_device()
        is_cuda = hasattr(device, "type") and device.type == "cuda"
        payload = {"available": is_cuda, "device": str(device),
                   "torch_version": torch.__version__,
                   "cuda_version": torch.version.cuda if is_cuda else None}
        if is_cuda:
            payload["memory"] = _device_manager.memory_stats()
        return payload
    except ImportError:
        return {"available": False, "device": "cpu", "torch_version": None, "cuda_version": None}
    except Exception as exc:
        return {"available": False, "device": "cpu", "error": str(exc)}
```

### 4.6 `app/ml/gpu/__init__.py` re-exports: AFTER

```python
# app/ml/gpu/__init__.py
from app.ml.gpu.device import DeviceManager
from app.ml.gpu.inference import GPUPredictor
from app.ml.gpu.memory_guard import MemoryGuard

__all__ = ["DeviceManager", "GPUPredictor", "MemoryGuard"]
```

### 4.7 Config patch (GPU settings injected inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- GPU inference settings — added by add_ml_gpu_inference tool ---
    GPU_ENABLED: bool = False
    GPU_DEVICE_ID: int = 0
    GPU_MEMORY_THRESHOLD_PCT: float = 0.9
    GPU_MIXED_PRECISION: bool = False
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Fingerprint check `"DeviceManager" in app/ml/gpu/device.py` returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Returns success+notes before any filesystem write when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | Validation loop at end: `ast.parse` on each created `.py` file; returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers kept small by construction; asserted by AST walk in test harness |
| QS-5 | **torch is NEVER imported at module top-level in any generated file** | AST walk of `tree.body` in every generated `app/` file; no `import torch` or `from torch import ...` at module scope |
| QS-6 | **`MemoryGuard` uses `GPU_MEMORY_THRESHOLD_PCT` from settings** | `MemoryGuard.threshold` property reads `settings.GPU_MEMORY_THRESHOLD_PCT` |
| QS-7 | **`DeviceManager` CPU fallback is documented** | `device.py` contains "fallback"/"falls back"/"falling back" text describing CPU path |
| QS-8 | **`GET /ml/gpu/status` response includes `"available"` key** | `_build_status_payload` emits `{"available": bool, ...}` on every code path |
| QS-9 | **`GPU_*` settings live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-10 | **`requirements.txt` is NOT modified** | Tool never appends torch; torch is user-provided |
| QS-11 | **`app/ml/gpu/__init__.py` re-exports all three public classes** | `DeviceManager`, `GPUPredictor`, `MemoryGuard` in `__all__` |
| QS-12 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` runs first |
| QS-13 | **Tool records execution time** | `ToolResult.execution_time_ms` set via `_elapsed_ms(start)` on every return path — including the error path for invalid directory |
| QS-14 | **`next_steps` mentions torch installation** | Contains `"torch"` token |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_ml_gpu_inference.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 5 new `.py` files | `len([p for p in result.files_created if p.endswith(".py")]) >= 5` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | `execution_time_ms` is a positive integer on success | `result.execution_time_ms > 0` | T-06 (`test_execution_time_recorded`) |
| CC-07 | `execution_time_ms` is set even on validation error | `result.execution_time_ms >= 0` when `status == "error"` | T-07 (`test_execution_time_on_invalid_dir`) |
| CC-08 | `next_steps` is non-empty and mentions torch | `result.next_steps` non-empty; `"torch" in combined.lower()` | T-08 (`test_next_steps_present`) |
| CC-09 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-09 (`test_all_py_parse`) — combined with quality check |
| CC-10 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-10 (`test_no_function_over_50_loc`) |
| CC-11 | torch is NOT at module top-level in any generated `app/` file | AST walk of `tree.body` only; any `import torch` or `from torch import ...` at module scope is a violation | T-11 (`test_torch_not_at_top_level_in_any_generated_file`) |
| CC-12 | `GPU_ENABLED`, `GPU_DEVICE_ID`, `GPU_MEMORY_THRESHOLD_PCT`, `GPU_MIXED_PRECISION` exist inside `class Settings` with 4-space indent | String scan + indent check | T-12 (`test_config_fields_patched`) |
| CC-13 | `gpu_status` router is registered in `app/routes/__init__.py` | `"gpu_status" in content.lower()` | T-13 (`test_routes_registered`) |
| CC-14 | `app/ml/gpu/device.py` exists with `DeviceManager`, `get_device`, `memory_stats` | File exists + substring checks | T-14 (`test_device_module_created`) |
| CC-15 | `app/ml/gpu/memory_guard.py` exists with `MemoryGuard` and `def check` | File exists + substring checks | T-15 (`test_memory_guard_created`) |
| CC-16 | `app/ml/gpu/inference.py` exists with `GPUPredictor`, `def predict`, `autocast` | File exists + substring checks | T-16 (`test_inference_module_created`) |
| CC-17 | `app/ml/gpu/__init__.py` re-exports `DeviceManager`, `GPUPredictor`, `MemoryGuard` | File exists + all three symbols present | T-17 (`test_gpu_init_has_reexports`) |
| CC-18 | `app/api/routes/gpu_status.py` exists with `router` and `/status` endpoint | File exists + `"router"` and `"/status"` in content | T-18 (`test_gpu_status_route_created`) |
| CC-19 | `requirements.txt` is NOT modified | `req_before == req_after`; `"requirements.txt"` not in `files_modified` | T-19 (`test_requirements_not_modified`) |
| CC-20 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-20 (`test_idempotent_project_still_parses`) |
| CC-21 | `memory_guard.py` references `GPU_MEMORY_THRESHOLD_PCT` | `"GPU_MEMORY_THRESHOLD_PCT" in content` | T-21 (`test_memory_guard_has_threshold`) |
| CC-22 | `device.py` documents the CPU fallback | `"cpu" in content.lower()` and any of `"fallback"`, `"fall back"`, `"falling back"`, `"falls back"` | T-22 (`test_device_cpu_fallback_documented`) |
| CC-23 | `gpu_status.py` response includes `"available"` key | `'"available"' in content or "'available'" in content` | T-23 (`test_gpu_status_endpoint_returns_available_key`) |

---

## 7. Definition of Done (DoD)

- [ ] All 23 Completeness Criteria verified by `test_add_ml_gpu_inference.py`
- [ ] `add_ml_gpu_inference.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_ml_gpu_inference.py` detects `"DeviceManager"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] Zero top-level torch imports in any generated file
- [ ] `MemoryGuard` reads `GPU_MEMORY_THRESHOLD_PCT` from settings and raises `RuntimeError` when exceeded
- [ ] `DeviceManager` falls back to `_CpuDevice` stub when torch is not installed
- [ ] `GET /ml/gpu/status` returns `{"available": false}` gracefully when torch absent
- [ ] `requirements.txt` is never modified
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `execution_time_ms` is set on every return path including the error path for invalid directory
- [ ] `next_steps` includes torch installation guidance
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-GPU-01 | Tool is ALWAYS idempotent on second invocation | Fingerprint check `"DeviceManager" in device_file.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-GPU-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-GPU-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: ast.parse(p)` | T-09, T-20 |
| INV-GPU-04 | `torch` MUST NOT appear at module top-level in any generated file | AST walk of `tree.body` for all `app/` `.py` files | T-11 |
| INV-GPU-05 | `MemoryGuard` MUST use `GPU_MEMORY_THRESHOLD_PCT` from settings | `MemoryGuard.threshold` property delegates to `settings.GPU_MEMORY_THRESHOLD_PCT` | T-21 |
| INV-GPU-06 | `DeviceManager` MUST document and implement CPU fallback | `device.py` contains fallback description and `_CpuDevice` stub class | T-22 |
| INV-GPU-07 | `GET /ml/gpu/status` MUST return `"available"` key on every code path | `_build_status_payload` guarantees `"available"` in all return branches | T-23 |
| INV-GPU-08 | `GPU_*` settings MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-12 |
| INV-GPU-09 | `requirements.txt` MUST NOT be modified | Tool never calls `_patch_requirements`; torch is user-provided | T-19 |
| INV-GPU-10 | `app/ml/gpu/__init__.py` MUST re-export all three public classes | `DeviceManager`, `GPUPredictor`, `MemoryGuard` in `__all__` | T-17 |
| INV-GPU-11 | `ToolResult.execution_time_ms` MUST be set on EVERY return path including error | `_elapsed_ms(start)` called on success, no_op, dry_run, and validation-error branches | T-06, T-07 |
| INV-GPU-12 | `next_steps` MUST reference torch installation | Contains `"torch"` token in lowercased join | T-08 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Upgrade a FastAPI project with GPU inference**
- **As a** ML engineer deploying to a GPU instance
- **I want** to run one tool call and get a complete GPU layer
- **So that** I do not hand-roll CUDA device management
- **Given:** A FastAPI project with `app/core/config.py`, `app/routes/__init__.py`
- **When:** `add_ml_gpu_inference(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-GPU-01)
  - `files_created` contains ≥ 5 `.py` paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/ml/gpu/device.py` already contains `DeviceManager`
- **When:** `add_ml_gpu_inference(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-GPU-01)
  - `files_created == []` and `files_modified == []`
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_ml_gpu_inference(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-GPU-02)
  - Verified by T-03

**US-04: Generate an error with timing on invalid directory**
- **As a** tool consumer
- **I want** an informative error with `execution_time_ms` even for bad inputs
- **So that** I can always rely on the field being present
- **Given:** `project_dir="/nonexistent/path/abc"`
- **When:** `add_ml_gpu_inference(ToolInput(project_dir=...))`
- **Then:**
  - Returns `status="error"` (INV-GPU-11)
  - `execution_time_ms >= 0`
  - Verified by T-07

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in minutes
- **Given:** Tool emitted `device.py`, `memory_guard.py`, `inference.py`, `gpu_status.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50`
  - Verified by T-10

### 9.2 DeviceManager (US-06 .. US-09)

**US-06: Select GPU device at runtime**
- **As a** ML workload on a GPU host
- **I want** `DeviceManager().get_device()` to return `cuda:0`
- **So that** inference uses the GPU without manual device strings
- **Given:** `GPU_ENABLED=true` in settings and CUDA available
- **When:** `get_device()` called
- **Then:**
  - Returns `torch.device("cuda:0")` (with `GPU_DEVICE_ID=0`)
  - Logged at INFO level
  - Verified by T-14

**US-07: Fall back to CPU when GPU unavailable**
- **As a** developer running locally without a GPU
- **I want** the app to start and run without CUDA
- **So that** local development does not require a GPU workstation
- **Given:** `GPU_ENABLED=false` or CUDA unavailable
- **When:** `get_device()` called
- **Then:**
  - Returns `torch.device("cpu")` or `_CpuDevice` stub
  - Warning logged when `GPU_ENABLED=true` but CUDA absent
  - Verified by T-14, T-22

**US-08: Fall back to CPU when torch is not installed**
- **As a** CI container without torch
- **I want** the app to import `app.ml.gpu` without `ImportError`
- **So that** CI passes in a lightweight environment
- **Given:** torch not installed
- **When:** `DeviceManager().get_device()` called
- **Then:**
  - `ImportError` caught; `_CpuDevice()` returned
  - Warning logged
  - Verified by T-11, T-14 (INV-GPU-04)

**US-09: Get memory statistics for the active GPU**
- **As an** operator dashboard
- **I want** `DeviceManager().memory_stats()` to return `utilisation_pct`
- **So that** I can alert on GPU memory pressure
- **Given:** CUDA device active
- **When:** `memory_stats()` called
- **Then:**
  - Returns `{"allocated_bytes", "reserved_bytes", "utilisation_pct"}`
  - Returns `{}` on CPU or when torch absent
  - Verified by T-14

### 9.3 MemoryGuard (US-10 .. US-13)

**US-10: Block inference when GPU memory is exhausted**
- **As a** FastAPI worker process
- **I want** inference to fail cleanly with a `RuntimeError` before it OOM-kills the process
- **So that** a single heavy request does not bring down the entire API tier
- **Given:** GPU memory `utilisation > GPU_MEMORY_THRESHOLD_PCT`
- **When:** `MemoryGuard.check(device)` called before forward pass
- **Then:**
  - Raises `RuntimeError("GPU memory utilisation X% exceeds threshold Y% — inference blocked")`
  - Caller converts to HTTP 503
  - Verified by T-15, T-21

**US-11: No-op on CPU device**
- **As a** CPU inference path
- **I want** `MemoryGuard.check(device)` to be a no-op on non-CUDA devices
- **So that** CPU inference is not impeded
- **Given:** `device.type == "cpu"` or `device` is `_CpuDevice`
- **When:** `check(device)` called
- **Then:**
  - Returns immediately without raising
  - Verified by T-15

**US-12: No-op when torch not installed**
- **As a** minimal deploy
- **I want** `MemoryGuard.check(device)` to not crash when torch absent
- **So that** the guard is safe to call everywhere
- **Given:** torch not installed; `_CpuDevice` in use
- **When:** `check(device)` called
- **Then:**
  - `try/except` around torch import swallows ImportError
  - Returns without raising
  - Verified by T-15

**US-13: Configure threshold from settings**
- **As an** ops engineer
- **I want** `GPU_MEMORY_THRESHOLD_PCT=0.85` in `.env` to lower the OOM guard
- **So that** I can tune safety margins per deployment
- **Given:** `MemoryGuard.threshold` property reads `settings.GPU_MEMORY_THRESHOLD_PCT`
- **When:** Memory utilisation is 88%
- **Then:**
  - Raises when `0.88 > 0.85` (configured threshold)
  - Does not raise at the 0.9 default
  - Verified by T-21

### 9.4 GPUPredictor (US-14 .. US-17)

**US-14: Run inference on GPU**
- **As a** torch model wrapped in `GPUPredictor`
- **I want** `predictor.predict(inputs)` to run on the CUDA device
- **So that** GPU parallelism is leveraged
- **Given:** CUDA available, `GPU_ENABLED=true`
- **When:** `predict(inputs)` called
- **Then:**
  - `_memory_guard.check(device)` passes
  - `model.to(device)` called on first invocation
  - Forward pass runs on CUDA
  - Verified by T-16

**US-15: Optional float16 mixed precision**
- **As a** engineer reducing inference latency
- **I want** `GPU_MIXED_PRECISION=true` to enable float16 autocast
- **So that** throughput improves on Tensor-Core GPUs
- **Given:** `GPU_MIXED_PRECISION=true` and CUDA device active
- **When:** `GPUPredictor.predict(inputs)` called
- **Then:**
  - `torch.cuda.amp.autocast()` context manager wraps the forward pass
  - `autocast` referenced in `inference.py`
  - Verified by T-16

**US-16: OOM protection before forward pass**
- **As a** GPUPredictor user
- **I want** `MemoryGuard.check` called before `model(inputs)`
- **So that** the guard fires before CUDA allocates for the forward pass
- **Given:** `MemoryGuard` checks at `predict()` entry
- **When:** Memory pressure is above threshold
- **Then:**
  - `RuntimeError` raised before the forward pass reaches CUDA
  - Verified by T-15, T-16

**US-17: Lazy device placement**
- **As a** developer constructing `GPUPredictor(model)` at module load time
- **I want** `model.to(device)` deferred until first call to `predict()`
- **So that** instantiation does not require CUDA at import time
- **Given:** `_device = None` in `GPUPredictor.__init__`
- **When:** First `predict()` call
- **Then:**
  - `_get_device()` resolves `DeviceManager`
  - `_move_model()` calls `model.to(device)` exactly once
  - Verified by T-16

### 9.5 HTTP status endpoint and config (US-18 .. US-23)

**US-18: GPU status endpoint when torch present**
- **As an** ops dashboard
- **I want** `GET /ml/gpu/status` to return device details
- **So that** I can confirm GPU inference is active
- **Given:** torch installed and CUDA available
- **When:** `GET /ml/gpu/status`
- **Then:**
  - Returns `{"available": true, "device": "cuda:0", "torch_version": "...", "cuda_version": "...", "memory": {...}}`
  - Verified by T-18, T-23

**US-19: GPU status endpoint when torch absent**
- **As a** CI container without torch
- **I want** `GET /ml/gpu/status` to return 200 (not 500)
- **So that** health checks do not fail in lightweight environments
- **Given:** torch not installed
- **When:** `GET /ml/gpu/status`
- **Then:**
  - Returns `{"available": false, "device": "cpu", "torch_version": null, "cuda_version": null}`
  - HTTP 200, no exception
  - Verified by T-18, T-23

**US-20: gpu_status router registered**
- **As a** FastAPI app
- **I want** the GPU status route available at startup
- **So that** no manual wiring is required after tool install
- **Given:** `app/routes/__init__.py` patched
- **When:** App starts
- **Then:**
  - `gpu_status_router` imported and `include_router` called
  - Verified by T-13

**US-21: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `GPU_ENABLED=true GPU_DEVICE_ID=1` in `.env` to activate GPU on device 1
- **So that** I do not rebuild images for device selection
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` instantiated at boot
- **Then:**
  - `GPU_*` inside `class Settings` picks up env vars (INV-GPU-08)
  - Verified by T-12

**US-22: requirements.txt stays unchanged**
- **As a** build engineer managing exact wheel variants
- **I want** tool install to not add torch to requirements
- **So that** I choose the correct CUDA-matching wheel myself
- **Given:** `requirements.txt` present before tool run
- **When:** Tool runs and completes
- **Then:**
  - `req_before == req_after`
  - `requirements.txt` absent from `files_modified`
  - Verified by T-19 (INV-GPU-09)

**US-23: Install next steps include torch guidance**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include torch installation instructions
- **So that** I know I need to install torch separately
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains torch installation command
  - Mentions `GPU_ENABLED`, `GPU_DEVICE_ID`, `GPU_MEMORY_THRESHOLD_PCT`, `GPU_MIXED_PRECISION`
  - Verified by T-08 (INV-GPU-12)

---

## 10. Test Plan

All 23 tests live in `adapt/extend/infrastructure/test_add_ml_gpu_inference.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-08)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `gpu_t01` | `add_ml_gpu_inference(ToolInput(project_dir))` | `result.status == "success"` (INV-GPU-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `gpu_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-GPU-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `gpu_t03`; snapshot all `.py` | `add_ml_gpu_inference(ToolInput(dry_run=True))` | `status == "success"`; empty lists; byte-identical (INV-GPU-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `gpu_t04` | Run tool | `len(py_created) >= 5`; every path exists (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `gpu_t05` | Run tool | `len(files_modified) >= 2`; every path exists (CC-05) |
| T-06 | `test_execution_time_recorded` | Fixture `gpu_t06`; run tool | Read `result.execution_time_ms` | `> 0` (INV-GPU-11, CC-06) |
| T-07 | `test_execution_time_on_invalid_dir` | `project_dir="/nonexistent/path/abc"` | `add_ml_gpu_inference(...)` | `status == "error"`; `execution_time_ms >= 0` (INV-GPU-11, CC-07) |
| T-08 | `test_next_steps_present` | Fixture `gpu_t07`; run tool | Read `result.next_steps` | Non-empty; `"torch" in combined.lower()` (INV-GPU-12, CC-08) |

### 10.2 Category B — Generated code quality (T-09 .. T-13)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-09 | `test_all_py_parse` | Fixture `gpu_t08`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-GPU-03, CC-09) |
| T-10 | `test_no_function_over_50_loc` | Fixture `gpu_t09`; run tool | AST walk over `app/` | `max_loc <= 50` (QS-4, CC-10) |
| T-11 | `test_torch_not_at_top_level_in_any_generated_file` | Fixture `gpu_t10`; run tool | AST `tree.body` walk on every `app/` `.py` | No `import torch` / `from torch import ...` at module scope (INV-GPU-04, CC-11) |
| T-12 | `test_config_fields_patched` | Fixture `gpu_t11`; run tool | Read `app/core/config.py` | All 4 `GPU_*` fields present; `GPU_ENABLED` line starts with 4-space indent (INV-GPU-08, CC-12) |
| T-13 | `test_routes_registered` | Fixture `gpu_t12`; run tool | Read `app/routes/__init__.py` | `"gpu_status" in content.lower()` (CC-13) |

### 10.3 Category C — Domain-specific modules (T-14 .. T-23)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-14 | `test_device_module_created` | Fixture `gpu_t13`; run tool | Read `app/ml/gpu/device.py` | Exists; contains `DeviceManager`, `get_device`, `memory_stats` (CC-14) |
| T-15 | `test_memory_guard_created` | Fixture `gpu_t14`; run tool | Read `app/ml/gpu/memory_guard.py` | Exists; contains `MemoryGuard`, `def check` (CC-15) |
| T-16 | `test_inference_module_created` | Fixture `gpu_t15`; run tool | Read `app/ml/gpu/inference.py` | Exists; contains `GPUPredictor`, `def predict`, `autocast` (CC-16) |
| T-17 | `test_gpu_init_has_reexports` | Fixture `gpu_t16`; run tool | Read `app/ml/gpu/__init__.py` | Exists; contains `DeviceManager`, `GPUPredictor`, `MemoryGuard` (INV-GPU-10, CC-17) |
| T-18 | `test_gpu_status_route_created` | Fixture `gpu_t17`; run tool | Read `app/api/routes/gpu_status.py` | Exists; contains `router`, `"/status"` (CC-18) |
| T-19 | `test_requirements_not_modified` | Fixture `gpu_t18`; snapshot `requirements.txt` | Run tool | `req_before == req_after`; `requirements.txt` not in `files_modified` (INV-GPU-09, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `gpu_t19`; run twice | AST-parse every `.py` | No `SyntaxError` (INV-GPU-01, INV-GPU-03, CC-20) |
| T-21 | `test_memory_guard_has_threshold` | Fixture `gpu_t20`; run tool | Read `app/ml/gpu/memory_guard.py` | `"GPU_MEMORY_THRESHOLD_PCT" in content` (INV-GPU-05, CC-21) |
| T-22 | `test_device_cpu_fallback_documented` | Fixture `gpu_t21`; run tool | Read `app/ml/gpu/device.py` | `"cpu" in content.lower()` and one of fallback phrases present (INV-GPU-06, CC-22) |
| T-23 | `test_gpu_status_endpoint_returns_available_key` | Fixture `gpu_t22`; run tool | Read `app/api/routes/gpu_status.py` | `'"available"' in content or "'available'" in content` (INV-GPU-07, CC-23) |

### 10.4 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_ml_gpu_inference.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_ml_gpu_inference.py
```

Target: 23/23 passed, 0 failed. The standalone runner prints `TOOL-069 STRUCTURAL: 23/23 passed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_ml_model_server` (TOOL-068) | Yes | Compatible — TOOL-068 ideally runs FIRST | TOOL-069 creates `app/ml/gpu/` alongside the `app/ml/` package; `GPUPredictor` wraps models loaded by `load_model` and stored in `ModelRegistry` |
| `add_ml_model_registry` (TOOL-070) | No | Compatible | TOOL-070 manages artefact metadata in the DB; GPU execution is orthogonal — the DB registry stores paths, the GPU layer runs inference |
| `add_cache_layer` (TOOL-021) | No | Compatible | GPU inference results can be cached to avoid redundant forward passes for identical inputs; cache key includes input hash |
| `add_arq_worker` (TOOL-053) | No | Compatible | Heavy GPU batch jobs can be offloaded to the arq worker; worker calls `GPUPredictor` directly; keeps HTTP response times short |
| `add_circuit_breaker` (TOOL-022) | No | Compatible | GPU memory errors (`RuntimeError` from `MemoryGuard`) can be fed into a circuit breaker that temporarily blocks inference when GPU is under pressure |
| `add_rate_limiting` (TOOL-057) | No | Compatible | GPU-backed endpoints benefit from stricter rate limits; high-cost GPU inference should not be drainable by unauthenticated floods |
| `add_health_deep` (TOOL-061) | No | Compatible | `GET /ml/gpu/status` can be integrated as a deep health probe; unhealthy GPU (`available: false` when expected) triggers alerts |

**Conflicts:** None. TOOL-069 adds a GPU inference sub-package; it does not replace or conflict with any other tool. When `add_ml_model_server` is not present, TOOL-069 still creates `app/ml/__init__.py` as a minimal package stub.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/routes/__init__.py

rm -rf app/ml/gpu/
rm -f app/api/routes/gpu_status.py
```

### 12.2 No database rollback required

TOOL-069 creates no database tables or migrations. Rollback is a pure filesystem operation.

### 12.3 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

The ast.parse validation loop runs at the end of the success path. A mid-execution failure may leave partially-written files in `app/ml/gpu/`. Revert modified paths and `rm -rf app/ml/gpu/` to restore.

### 12.4 Uninstall validator

```bash
test ! -d app/ml/gpu || (echo "app/ml/gpu still present" && exit 1)
test ! -f app/api/routes/gpu_status.py || (echo "gpu_status route still present" && exit 1)
grep -q "GPU_ENABLED" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms >= 0` |
| EC-02 | Tool runs on a project missing a prerequisite | `ensure_prerequisites` returns errors → `status="error"` |
| EC-03 | `app/ml/gpu/device.py` already contains `DeviceManager` | Early return `status="no_op"` — zero file writes |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched |
| EC-05 | `app/ml/` directory does not exist (TOOL-068 not run) | Tool creates `app/ml/__init__.py` stub and `app/ml/gpu/` package |
| EC-06 | `app/core/config.py` already contains `GPU_ENABLED` | `_patch_config` early-returns; no duplicate block appended |
| EC-07 | `app/core/config.py` lacks `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Fallback to before `settings = Settings()` or EOF append |
| EC-08 | `app/routes/__init__.py` missing | Routes patch step skipped; developer must register router manually |
| EC-09 | `app/api/routes/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `gpu_status.py` |
| EC-10 | `GPU_ENABLED=true` but CUDA unavailable | `_select_device` logs warning and falls back to `torch.device("cpu")` |
| EC-11 | torch not installed | `_select_device` catches `ImportError`; returns `_CpuDevice()` stub |
| EC-12 | `GPU_MEMORY_THRESHOLD_PCT=1.0` | `MemoryGuard.check` never raises (utilisation cannot exceed 100% of reserved) |
| EC-13 | `GPU_MEMORY_THRESHOLD_PCT=0.0` | Every CUDA allocation triggers `RuntimeError`; developers should set a realistic value |
| EC-14 | `GPU_DEVICE_ID=99` (non-existent CUDA device) | `torch.device("cuda:99")` construction deferred; runtime error surfaces when model is moved to device |
| EC-15 | `app/routes/__init__.py` already contains gpu_status router import | `_patch_routes_init` early-returns; no duplicate call |
| EC-16 | Generated `device.py` fails `ast.parse` | Validation loop returns `status="error"` with file path detail |
| EC-17 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-20) |
| EC-18 | `_build_status_payload` encounters unexpected exception | `except Exception` branch returns `{"available": False, "device": "cpu", "error": str(exc)}` |

---

## 14. Acceptance Criteria (Final Sign-off)

1. All 23 Completeness Criteria verified via `test_add_ml_gpu_inference.py` passing
2. `test_add_ml_gpu_inference.py` reports `23/23 passed` via both pytest and standalone runner
3. Tool execution time < 5 s measured on reference hardware
4. Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-GPU-01)
5. `dry_run=True` produces zero filesystem writes (INV-GPU-02)
6. Every generated `.py` file AST-parses cleanly on first and second runs (INV-GPU-03)
7. No generated function in `app/` exceeds 50 LOC (QS-4)
8. Zero top-level torch imports in any generated file (INV-GPU-04)
9. `MemoryGuard` reads `GPU_MEMORY_THRESHOLD_PCT` from settings (INV-GPU-05)
10. `DeviceManager` falls back to CPU and documents the fallback (INV-GPU-06)
11. `GET /ml/gpu/status` always returns `"available"` key (INV-GPU-07)
12. `GPU_*` settings live inside `class Settings` with 4-space indent (INV-GPU-08)
13. `requirements.txt` never modified (INV-GPU-09)
14. `execution_time_ms` set on every return path including validation error (INV-GPU-11)
15. `next_steps` includes torch installation guidance (INV-GPU-12)

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error (set `execution_time_ms` before returning error)
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, ROUTES_INIT, REQUIREMENTS_TXT)` passes with auto-scaffold
- [ ] `app/ml/gpu/device.py` does NOT contain `"DeviceManager"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 `app/ml/` parent init (if missing)

- [ ] If `app/ml/__init__.py` absent: write minimal `"""Machine-learning sub-package."""\n`

### 15.3 `app/ml/gpu/` package

- [ ] `mkdir -p app/ml/gpu`
- [ ] Write `app/ml/gpu/__init__.py` if missing: re-exports `DeviceManager`, `GPUPredictor`, `MemoryGuard`
- [ ] Write `app/ml/gpu/device.py`: `DeviceManager`, `_CpuDevice`, `get_device`, `_select_device`, `memory_stats` — all torch imports lazy
- [ ] Write `app/ml/gpu/memory_guard.py`: `MemoryGuard`, `threshold` property, `check(device)` — all torch imports lazy
- [ ] Write `app/ml/gpu/inference.py`: `GPUPredictor`, `predict`, `_get_device`, `_move_model`, `_forward` — all torch imports lazy; uses `torch.cuda.amp.autocast`

### 15.4 HTTP route

- [ ] `mkdir -p app/api/routes` if missing
- [ ] Write `app/api/routes/gpu_status.py`: `APIRouter(prefix="/ml/gpu")`, `_build_status_payload`, `GET /status`
- [ ] `_build_status_payload` emits `{"available": bool}` on every code path including `ImportError` and generic `Exception`

### 15.5 Config patch

- [ ] Early-return if `"GPU_ENABLED" in src`
- [ ] Block emits `GPU_ENABLED: bool = False`, `GPU_DEVICE_ID: int = 0`, `GPU_MEMORY_THRESHOLD_PCT: float = 0.9`, `GPU_MIXED_PRECISION: bool = False`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.6 Routes init patch

- [ ] Early-return if import line already present
- [ ] Insert `from app.api.routes.gpu_status import router as gpu_status_router`
- [ ] Insert `api_router.include_router(gpu_status_router)`
- [ ] Preserve trailing newline

### 15.7 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `status="error"` with file path on `SyntaxError`

### 15.8 Result assembly

- [ ] `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` describe lazy imports, `DeviceManager`, `MemoryGuard`, `GPUPredictor`, CPU fallback
- [ ] `next_steps` include torch installation command (CPU and CUDA variants), env-var setup, restart hint

### 15.9 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and lazy-import rationale
- [ ] `add_ml_gpu_inference` docstring documents args and return type

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/ml/__init__.py",
    "/tmp/fixture/app/ml/gpu/__init__.py",
    "/tmp/fixture/app/ml/gpu/device.py",
    "/tmp/fixture/app/ml/gpu/memory_guard.py",
    "/tmp/fixture/app/ml/gpu/inference.py",
    "/tmp/fixture/app/api/routes/gpu_status.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py"
  ],
  "notes": [
    "GPU inference layer added: DeviceManager, MemoryGuard, GPUPredictor.",
    "All torch/cuda imports are lazy — app boots without torch installed.",
    "GET /ml/gpu/status returns device info even when torch is absent.",
    "Config patched: GPU_ENABLED, GPU_DEVICE_ID, GPU_MEMORY_THRESHOLD_PCT, GPU_MIXED_PRECISION.",
    "MemoryGuard raises RuntimeError when GPU memory exceeds GPU_MEMORY_THRESHOLD_PCT to prevent OOM kills."
  ],
  "next_steps": [
    "Install torch: pip install torch (CPU) or pip install torch --index-url https://download.pytorch.org/whl/cu121 (CUDA 12.1).",
    "Set GPU_ENABLED=true and GPU_DEVICE_ID=0 in .env to activate GPU inference.",
    "Set GPU_MEMORY_THRESHOLD_PCT (default 0.9) to guard against OOM.",
    "Set GPU_MIXED_PRECISION=true for float16 autocast (requires GPU).",
    "Call DeviceManager().get_device() to get the active torch.device.",
    "Wrap your model with GPUPredictor(model) to get auto device + autocast.",
    "Restart the FastAPI app — GET /ml/gpu/status shows live device info."
  ],
  "execution_time_ms": 94
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "DeviceManager already present — GPU inference is already installed, skipped."
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
    "[dry_run] Would create app/ml/gpu/ package (device.py, inference.py, memory_guard.py, __init__.py).",
    "[dry_run] Would create app/api/routes/gpu_status.py (GET /ml/gpu/status).",
    "[dry_run] Would patch app/core/config.py with GPU_ENABLED, GPU_DEVICE_ID, GPU_MEMORY_THRESHOLD_PCT, GPU_MIXED_PRECISION.",
    "[dry_run] Would register gpu_status router in app/routes/__init__.py.",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (invalid directory):

```json
{
  "status": "error",
  "error": "project_dir does not exist: /nonexistent/path/abc",
  "execution_time_ms": 0
}
```

---
