"""TOOL-069: add_ml_gpu_inference — GPU-optimised inference for FastAPI.

Migrated to per-tool directory + externalized templates (WP-06b).

Creates ``app/ml/gpu/`` (DeviceManager, MemoryGuard, GPUPredictor),
``app/api/routes/gpu_status.py`` (GET /ml/gpu/status), patches
``app/core/config.py`` with 4 GPU settings, and registers the gpu_status
router in ``app/routes/__init__.py``.

All torch/cuda imports in the emitted code are lazy — the app boots
without torch installed (S2 weight-loading safety).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_ml_gpu_inference",
    "description": (
        "Upgrade a FastAPI project with GPU-optimised inference: DeviceManager, "
        "GPUPredictor (mixed precision), MemoryGuard, and GET /ml/gpu/status endpoint. "
        "All torch imports are lazy — app boots without torch installed."
    ),
    "tags": ["extend", "infrastructure", "ml", "gpu"],
    "entry": "add_ml_gpu_inference",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_ml_gpu_inference(inp: ToolInput) -> ToolResult:
    """Add GPU-optimised inference infrastructure to a FastAPI project."""
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

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

    project = Path(inp.project_dir)
    app_dir = project / "app"
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

    files_created: list[str] = list(scaffolded)
    files_modified: list[str] = []

    # Step 1: app/ml/__init__.py + app/ml/gpu/ package
    gpu_dir = app_dir / "ml" / "gpu"
    gpu_dir.mkdir(parents=True, exist_ok=True)
    ml_init = app_dir / "ml" / "__init__.py"
    if not ml_init.exists():
        ml_init.write_text('"""Machine-learning sub-package."""\n')
        files_created.append(str(ml_init))

    gpu_init = gpu_dir / "__init__.py"
    if not gpu_init.exists():
        render_to(_HERE, "gpu_init.py.tmpl", dest=gpu_init, substitutions={})
        files_created.append(str(gpu_init))

    # Step 2: device + memory guard + inference modules
    render_to(_HERE, "device.py.tmpl", dest=device_file, substitutions={})
    files_created.append(str(device_file))

    memory_guard_file = gpu_dir / "memory_guard.py"
    render_to(_HERE, "memory_guard.py.tmpl", dest=memory_guard_file, substitutions={})
    files_created.append(str(memory_guard_file))

    inference_file = gpu_dir / "inference.py"
    render_to(_HERE, "inference.py.tmpl", dest=inference_file, substitutions={})
    files_created.append(str(inference_file))

    # Step 3: gpu_status route
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    gpu_status_file = routes_dir / "gpu_status.py"
    render_to(_HERE, "gpu_status_route.py.tmpl", dest=gpu_status_file, substitutions={})
    files_created.append(str(gpu_status_file))

    # Step 4: patch config + routes_init
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 5: emit project test (P1 #15)
    _emit_project_test(project, files_created)

    # Step 6: ast.parse validation
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


def _patch_config(config_file: Path) -> None:
    """Inject GPU settings into the ``Settings`` class body."""
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
    """Register the gpu_status router in ``app/routes/__init__.py``."""
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


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Emit the project-level test (P1 #15)."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_ml_gpu_inference_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_ml_gpu_inference_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
