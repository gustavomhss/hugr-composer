"""TOOL-069: add_ml_gpu_inference — add GPU-optimised inference to a FastAPI project.

Upgrades an existing FastAPI project (ideally after ``add_ml_model_server``) with
a full GPU inference layer. Creates a ``app/ml/gpu/`` package with device
management, mixed-precision inference, and a memory guard, plus a companion HTTP
status endpoint at ``GET /ml/gpu/status``.

Key design decisions
--------------------
* **All torch/cuda imports are LAZY** — every ``import torch`` / ``import torch.cuda``
  lives inside a function body, never at module top-level. This guarantees the app
  boots cleanly on CPU-only machines (or when torch is not installed at all).
* ``DeviceManager`` detects CUDA at runtime and falls back to CPU with a warning;
  it never raises on import or construction.
* ``MemoryGuard`` checks ``torch.cuda.memory_allocated()`` before each inference
  call and raises ``RuntimeError`` when utilisation exceeds the configured
  threshold, preventing OOM kills.
* ``GPUPredictor`` wraps ``model.to(device)`` and ``torch.cuda.amp.autocast``
  for optional mixed-precision inference.
* ``GET /ml/gpu/status`` returns a JSON response even when torch is not
  installed (``{"available": false, "device": "cpu"}``).
* Requirements: torch is user-provided; this tool adds **no new deps** to
  ``requirements.txt``.

The tool is idempotent: a second run detects ``DeviceManager`` in
``app/ml/gpu/device.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_ml_gpu_inference import add_ml_gpu_inference

    result = add_ml_gpu_inference(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/ml/gpu/device.py", …]
    print(result.next_steps)    # ["Install torch ...", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites


MCP_TOOL = {
    "name": "fastapi_resiliency_add_ml_gpu_inference",
    "description": (
        "Upgrade a FastAPI project with GPU-optimised inference: DeviceManager, "
        "GPUPredictor (mixed precision), MemoryGuard, and GET /ml/gpu/status endpoint. "
        "All torch imports are lazy — app boots without torch installed."
    ),
    "tags": ["extend", "infrastructure", "ml", "gpu"],
    "entry": "add_ml_gpu_inference",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_ml_gpu_inference(inp: ToolInput) -> ToolResult:
    """Add GPU-optimised inference infrastructure to a FastAPI project.

    Creates ``app/ml/gpu/`` package (device manager, GPU predictor, memory
    guard, re-exports), ``app/api/routes/gpu_status.py`` (GET /ml/gpu/status),
    patches ``app/core/config.py`` with 4 GPU settings, and registers the
    gpu_status router in ``app/routes/__init__.py``.

    All generated torch/cuda imports are LAZY — the app boots without torch.

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
                "Generate a base project first or ensure app/core/config.py exists.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: already installed? -------------------------------------
    device_file = app_dir / "ml" / "gpu" / "device.py"
    if device_file.exists() and "DeviceManager" in device_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["DeviceManager already present — GPU inference is already installed, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/ml/gpu/ package (device.py, inference.py, "
                "memory_guard.py, __init__.py).",
                "[dry_run] Would create app/api/routes/gpu_status.py (GET /ml/gpu/status).",
                "[dry_run] Would patch app/core/config.py with GPU_ENABLED, GPU_DEVICE_ID, "
                "GPU_MEMORY_THRESHOLD_PCT, GPU_MIXED_PRECISION.",
                "[dry_run] Would register gpu_status router in app/routes/__init__.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — app/ml/gpu/ package
    gpu_dir = app_dir / "ml" / "gpu"
    gpu_dir.mkdir(parents=True, exist_ok=True)

    # Ensure app/ml/__init__.py exists
    ml_init = app_dir / "ml" / "__init__.py"
    if not ml_init.exists():
        ml_init.write_text('"""Machine-learning sub-package."""\n')
        files_created.append(str(ml_init))

    # Step 2 — gpu/__init__.py (re-exports)
    gpu_init = gpu_dir / "__init__.py"
    if not gpu_init.exists():
        _write_gpu_init(gpu_init)
        files_created.append(str(gpu_init))

    # Step 3 — device.py
    _write_device_module(device_file)
    files_created.append(str(device_file))

    # Step 4 — memory_guard.py
    memory_guard_file = gpu_dir / "memory_guard.py"
    _write_memory_guard(memory_guard_file)
    files_created.append(str(memory_guard_file))

    # Step 5 — inference.py
    inference_file = gpu_dir / "inference.py"
    _write_inference_module(inference_file)
    files_created.append(str(inference_file))

    # Step 6 — gpu_status route
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    gpu_status_file = routes_dir / "gpu_status.py"
    _write_gpu_status_route(gpu_status_file)
    files_created.append(str(gpu_status_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- ast.parse validation loop (INV-03 / BUG-02) -----------------------
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
            "GPU inference layer added: DeviceManager, MemoryGuard, GPUPredictor.",
            "All torch/cuda imports are lazy — app boots without torch installed.",
            "GET /ml/gpu/status returns device info even when torch is absent.",
            "Config patched: GPU_ENABLED, GPU_DEVICE_ID, GPU_MEMORY_THRESHOLD_PCT, "
            "GPU_MIXED_PRECISION.",
            "MemoryGuard raises RuntimeError when GPU memory exceeds "
            "GPU_MEMORY_THRESHOLD_PCT to prevent OOM kills.",
        ],
        next_steps=[
            "Install torch: pip install torch (CPU) or pip install torch --index-url "
            "https://download.pytorch.org/whl/cu121 (CUDA 12.1).",
            "Set GPU_ENABLED=true and GPU_DEVICE_ID=0 in .env to activate GPU inference.",
            "Set GPU_MEMORY_THRESHOLD_PCT (default 0.9) to guard against OOM.",
            "Set GPU_MIXED_PRECISION=true for float16 autocast (requires GPU).",
            "Call DeviceManager().get_device() to get the active torch.device.",
            "Wrap your model with GPUPredictor(model) to get auto device + autocast.",
            "Restart the FastAPI app — GET /ml/gpu/status shows live device info.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_gpu_init(dest: Path) -> None:
    """Write ``app/ml/gpu/__init__.py`` with re-exports.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GPU inference sub-package.

        Re-exports the three public classes so callers can do::

            from app.ml.gpu import DeviceManager, GPUPredictor, MemoryGuard
        \"\"\"

        from app.ml.gpu.device import DeviceManager
        from app.ml.gpu.inference import GPUPredictor
        from app.ml.gpu.memory_guard import MemoryGuard

        __all__ = ["DeviceManager", "GPUPredictor", "MemoryGuard"]
    """))


def _write_device_module(dest: Path) -> None:
    """Write ``app/ml/gpu/device.py`` with ``DeviceManager``.

    All torch/cuda imports are inside function bodies (lazy).

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Device management for ML inference.

        ``DeviceManager`` detects whether CUDA is available at runtime and
        selects the appropriate ``torch.device``.  All torch imports are
        lazy: this module is safe to import on machines without torch.
        \"\"\"

        from __future__ import annotations

        import logging

        from app.core.config import settings

        logger = logging.getLogger(__name__)


        class DeviceManager:
            \"\"\"Detect and expose the active inference device.

            Uses lazy torch imports so the app boots on CPU-only machines or
            when torch is not installed at all.

            Attributes:
                _device: Cached torch.device selected on first call to
                    ``get_device()``.
            \"\"\"

            _device = None  # type: ignore[assignment]

            def get_device(self):
                \"\"\"Return the active ``torch.device``, selecting it on first call.

                If ``GPU_ENABLED`` is False in settings or CUDA is unavailable,
                falls back to CPU with a log warning.  Never raises.

                Returns:
                    A ``torch.device`` instance (``cuda:N`` or ``cpu``).
                \"\"\"
                if self._device is not None:
                    return self._device
                self._device = self._select_device()
                return self._device

            def _select_device(self):
                \"\"\"Select device: GPU when available + enabled, else CPU.

                Returns:
                    A ``torch.device`` instance.
                \"\"\"
                try:
                    import torch  # noqa: PLC0415,F401 (lazy import — intentional)
                    if settings.GPU_ENABLED and torch.cuda.is_available():
                        device_id = settings.GPU_DEVICE_ID
                        device = torch.device(f"cuda:{device_id}")
                        logger.info(
                            "GPU inference enabled",
                            extra={"device": str(device),
                                   "cuda_version": torch.version.cuda},
                        )
                        return device
                    if settings.GPU_ENABLED:
                        logger.warning(
                            "GPU_ENABLED=true but CUDA unavailable; falling back to CPU"
                        )
                except ImportError:
                    logger.warning("torch not installed; inference will use CPU stub")
                    return _CpuDevice()
                try:
                    import torch  # noqa: PLC0415,F401
                    return torch.device("cpu")
                except ImportError:
                    return _CpuDevice()

            def memory_stats(self) -> dict:
                \"\"\"Return GPU memory statistics for the active CUDA device.

                Returns an empty dict on CPU or when torch is absent — callers
                must tolerate missing keys.

                Returns:
                    Dict with ``allocated_bytes``, ``reserved_bytes``,
                    ``utilisation_pct`` keys when CUDA is active, else ``{}``.
                \"\"\"
                try:
                    import torch  # noqa: PLC0415,F401
                    device = self.get_device()
                    if not hasattr(device, "type") or device.type != "cuda":
                        return {}
                    alloc = torch.cuda.memory_allocated(device)
                    reserved = torch.cuda.memory_reserved(device)
                    util = (alloc / reserved) if reserved > 0 else 0.0
                    return {
                        "allocated_bytes": alloc,
                        "reserved_bytes": reserved,
                        "utilisation_pct": round(util * 100, 2),
                    }
                except Exception:  # noqa: BLE001
                    return {}


        class _CpuDevice:
            \"\"\"Minimal stub returned when torch is not installed.\"\"\"

            type = "cpu"

            def __str__(self) -> str:
                \"\"\"Return string representation.\"\"\"
                return "cpu"
    """))


def _write_memory_guard(dest: Path) -> None:
    """Write ``app/ml/gpu/memory_guard.py`` with ``MemoryGuard``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GPU memory guard — prevents OOM by checking utilisation before inference.

        ``MemoryGuard.check()`` must be called before each ``GPUPredictor``
        forward pass.  When memory utilisation exceeds the configured threshold
        it raises ``RuntimeError`` with a clear message; the FastAPI handler
        should catch this and return HTTP 503.

        All torch imports are lazy.
        \"\"\"

        from __future__ import annotations

        import logging

        from app.core.config import settings

        logger = logging.getLogger(__name__)


        class MemoryGuard:
            \"\"\"Check GPU memory utilisation before allowing inference.

            Attributes:
                threshold: Maximum fractional utilisation (0.0–1.0) before
                    inference is blocked.  Configurable via
                    ``settings.GPU_MEMORY_THRESHOLD_PCT``.
            \"\"\"

            def __init__(self, threshold: float | None = None) -> None:
                \"\"\"Initialise the guard with a memory threshold.

                Args:
                    threshold: Override for ``settings.GPU_MEMORY_THRESHOLD_PCT``.
                        When ``None``, reads from settings at call time.
                \"\"\"
                self._threshold = threshold

            @property
            def threshold(self) -> float:
                \"\"\"Active threshold (0.0–1.0).\"\"\"
                if self._threshold is not None:
                    return self._threshold
                return settings.GPU_MEMORY_THRESHOLD_PCT

            def check(self, device=None) -> None:
                \"\"\"Assert GPU memory utilisation is below threshold.

                No-op on CPU or when torch is absent.  Raises ``RuntimeError``
                when utilisation exceeds ``self.threshold``.

                Args:
                    device: A ``torch.device`` to check.  When ``None`` the
                        check is a no-op.

                Raises:
                    RuntimeError: When GPU memory utilisation exceeds the
                        configured threshold.
                \"\"\"
                if device is None:
                    return
                try:
                    if not hasattr(device, "type") or device.type != "cuda":
                        return
                    import torch  # noqa: PLC0415,F401
                    reserved = torch.cuda.memory_reserved(device)
                    if reserved == 0:
                        return
                    allocated = torch.cuda.memory_allocated(device)
                    utilisation = allocated / reserved
                    logger.debug(
                        "GPU memory utilisation",
                        extra={"utilisation_pct": round(utilisation * 100, 2)},
                    )
                    if utilisation > self.threshold:
                        raise RuntimeError(
                            f"GPU memory utilisation {utilisation:.1%} exceeds "
                            f"threshold {self.threshold:.1%} — inference blocked"
                        )
                except RuntimeError:
                    raise
                except Exception:  # noqa: BLE001
                    pass  # Non-OOM errors are non-fatal in the guard
    """))


def _write_inference_module(dest: Path) -> None:
    """Write ``app/ml/gpu/inference.py`` with ``GPUPredictor``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GPU-accelerated model predictor with optional mixed precision.

        ``GPUPredictor`` wraps any torch model and handles:

        * Moving the model to the active device (GPU or CPU) on first call.
        * Optional ``torch.cuda.amp.autocast`` for float16 mixed precision.
        * ``MemoryGuard`` check before each forward pass.

        All torch imports are lazy.
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from app.core.config import settings
        from app.ml.gpu.device import DeviceManager
        from app.ml.gpu.memory_guard import MemoryGuard

        logger = logging.getLogger(__name__)

        _device_manager = DeviceManager()
        _memory_guard = MemoryGuard()


        class GPUPredictor:
            \"\"\"Wrap a torch model for GPU-accelerated inference.

            Handles device placement, mixed-precision autocast, and memory
            guards.  All torch imports inside method bodies — safe on CPU-only
            hosts.

            Attributes:
                model: The wrapped torch model (any ``torch.nn.Module``).
                _device: Cached active device (resolved lazily).
            \"\"\"

            def __init__(self, model: Any) -> None:
                \"\"\"Wrap *model* for GPU inference.

                Args:
                    model: A ``torch.nn.Module`` instance.  Not moved to device
                        yet — movement happens lazily in ``predict()``.
                \"\"\"
                self.model = model
                self._device = None

            def _get_device(self) -> Any:
                \"\"\"Return (and cache) the active torch.device.

                Returns:
                    A ``torch.device`` or ``_CpuDevice`` stub.
                \"\"\"
                if self._device is None:
                    self._device = _device_manager.get_device()
                return self._device

            def _move_model(self) -> None:
                \"\"\"Move the model to the active device (idempotent).\"\"\"
                try:
                    import torch  # noqa: PLC0415,F401
                    device = self._get_device()
                    if hasattr(device, "type"):
                        self.model = self.model.to(device)
                except Exception:  # noqa: BLE001
                    pass

            def predict(self, inputs: Any) -> Any:
                \"\"\"Run inference on *inputs* with optional mixed precision.

                Checks GPU memory, moves the model to device on first call,
                and optionally wraps the forward pass in ``autocast``.

                Args:
                    inputs: Input tensor or dict accepted by ``self.model``.

                Returns:
                    Model output (type matches model return type).

                Raises:
                    RuntimeError: If GPU memory exceeds the configured threshold.
                \"\"\"
                device = self._get_device()
                _memory_guard.check(device)
                self._move_model()
                return self._forward(inputs, device)

            def _forward(self, inputs: Any, device: Any) -> Any:
                \"\"\"Execute the forward pass, optionally with autocast.

                Args:
                    inputs: Input tensor or dict.
                    device: Active torch.device.

                Returns:
                    Model output.
                \"\"\"
                use_amp = (
                    settings.GPU_MIXED_PRECISION
                    and hasattr(device, "type")
                    and device.type == "cuda"
                )
                try:
                    import torch  # noqa: PLC0415,F401
                    if use_amp:
                        with torch.cuda.amp.autocast():
                            return self.model(inputs)
                    return self.model(inputs)
                except Exception:  # noqa: BLE001
                    # Fallback: call without autocast
                    return self.model(inputs)
    """))


def _write_gpu_status_route(dest: Path) -> None:
    """Write ``app/api/routes/gpu_status.py`` with GET /ml/gpu/status.

    Works even when torch is not installed — returns
    ``{"available": false, "device": "cpu"}`` in that case.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"GPU status endpoint.

        ``GET /ml/gpu/status`` returns live device information.  Works even
        when torch is not installed — returns ``{"available": false}`` in
        that case.  No authentication required (device info is not sensitive).
        \"\"\"

        from __future__ import annotations

        import logging
        from typing import Any

        from fastapi import APIRouter
        from fastapi.responses import JSONResponse

        from app.ml.gpu.device import DeviceManager

        logger = logging.getLogger(__name__)

        router = APIRouter(prefix="/ml/gpu", tags=["ml", "gpu"])

        _device_manager = DeviceManager()


        def _build_status_payload() -> dict[str, Any]:
            \"\"\"Build the GPU status dict without raising.

            Performs lazy torch import; returns minimal ``{"available": false}``
            when torch is absent or CUDA is not available.

            Returns:
                Dict with at minimum ``available`` (bool) and ``device`` (str).
            \"\"\"
            try:
                import torch  # noqa: PLC0415,F401
                device = _device_manager.get_device()
                is_cuda = hasattr(device, "type") and device.type == "cuda"
                payload: dict[str, Any] = {
                    "available": is_cuda,
                    "device": str(device),
                    "torch_version": torch.__version__,
                    "cuda_version": torch.version.cuda if is_cuda else None,
                }
                if is_cuda:
                    payload["memory"] = _device_manager.memory_stats()
                return payload
            except ImportError:
                logger.warning("torch not installed; reporting GPU unavailable")
                return {"available": False, "device": "cpu", "torch_version": None,
                        "cuda_version": None}
            except Exception as exc:  # noqa: BLE001
                logger.warning("GPU status check failed: %s", exc)
                return {"available": False, "device": "cpu", "error": str(exc)}


        @router.get("/status", summary="GPU device status")
        async def gpu_status() -> JSONResponse:
            \"\"\"Return current GPU device information.

            Works even when torch is not installed or CUDA is unavailable.

            Returns:
                200 JSON with ``available`` (bool), ``device`` (str),
                ``torch_version``, ``cuda_version``, and optional ``memory``
                stats when CUDA is active.
            \"\"\"
            payload = _build_status_payload()
            return JSONResponse(content=payload)
    """))


# ---------------------------------------------------------------------------
# Patchers
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Inject GPU settings into the ``Settings`` class body.

    Fields are injected at 4-space indent inside the class body, anchoring
    on the ``ACCESS_TOKEN_EXPIRE_MINUTES`` field when present.  Idempotent.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "GPU_ENABLED" in src:
        return

    block = (
        "\n"
        "    # --- GPU inference settings — added by add_ml_gpu_inference tool ---\n"
        "    GPU_ENABLED: bool = False\n"
        "    GPU_DEVICE_ID: int = 0\n"
        "    GPU_MEMORY_THRESHOLD_PCT: float = 0.9\n"
        "    GPU_MIXED_PRECISION: bool = False\n"
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
    """Register the gpu_status router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    import_line = "from app.api.routes.gpu_status import router as gpu_status_router"
    include_line = "api_router.include_router(gpu_status_router)"
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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer (>= 0).
    """
    return max(0, int((time.monotonic() - start) * 1000))
